"""
ChatService — orchestrates streaming LLM calls with tool-use for /chat.

Emits the Vercel AI SDK v6 UIMessageStream protocol so the frontend's
``useChat`` / ``DefaultChatTransport`` can consume the stream directly.

UIMessageStream event format
----------------------------
Every line is ``data: <json>\\n\\n``.  The stream ends with ``data: [DONE]\\n\\n``.

Typical event sequence for a tool-call response::

    data: {"type":"start","messageId":"msg_xxx"}
    data: {"type":"reasoning-start","id":"r_xxx"}          (optional, reasoning models only)
    data: {"type":"reasoning-delta","id":"r_xxx","delta":"…"}
    data: {"type":"reasoning-end","id":"r_xxx"}
    data: {"type":"text-start","id":"text_xxx"}
    data: {"type":"text-delta","id":"text_xxx","delta":"I'll create…"}
    data: {"type":"text-end","id":"text_xxx"}
    data: {"type":"tool-input-start","toolCallId":"call_xxx","toolName":"display_diagram"}
    data: {"type":"tool-input-delta","toolCallId":"call_xxx","inputTextDelta":"…"}
    data: {"type":"tool-input-available","toolCallId":"call_xxx","toolName":"display_diagram","input":{…}}
    data: {"type":"tool-output-available","toolCallId":"call_xxx","output":"…"}
    data: {"type":"finish"}
    data: [DONE]

Tool execution model
--------------------
* ``display_diagram``, ``edit_diagram``, ``append_diagram`` are **client-side**
  tools.  The server emits ``tool-input-available`` and the frontend handles
  execution (calling ``addToolOutput`` afterwards).
* ``get_shape_library`` is a **server-side** tool.  The server executes it,
  emits ``tool-output-available``, then feeds the result back to the LLM for
  another generation round (multi-step).
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import string
import time
from typing import Any, AsyncGenerator

from app.config import Settings
from app.models.chat import ChatRequest
from app.providers.base import ModelConfig
from app.services.json_repair import get_fallback_tool_input, repair_tool_call_json
from app.tools.registry import ToolContext, ToolResult, dispatch_tool, get_tool_definitions

logger = logging.getLogger(__name__)

# Cache tool definitions at module level — the registry never changes at runtime.
_CACHED_TOOL_DEFS: list[dict] = []


def _init_tool_defs() -> None:
    """Populate the cached tool definitions (called once on first import of tools)."""
    global _CACHED_TOOL_DEFS
    if not _CACHED_TOOL_DEFS:
        _CACHED_TOOL_DEFS = get_tool_definitions()

# ---------------------------------------------------------------------------
# Client-side tools — the server only streams tool-input events; the frontend
# is responsible for executing these tools and calling addToolOutput.
# ---------------------------------------------------------------------------
CLIENT_SIDE_TOOLS = {"display_diagram", "edit_diagram", "append_diagram"}

# ---------------------------------------------------------------------------
# ID generation helpers (nanoid-style short random strings)
# ---------------------------------------------------------------------------

_ALPHABET = string.ascii_lowercase + string.digits


def _nanoid(prefix: str, length: int = 12) -> str:
    """Generate a short random id with the given *prefix*."""
    suffix = "".join(random.choices(_ALPHABET, k=length))
    return f"{prefix}{suffix}"


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------


def _sse(payload: dict) -> str:
    """Encode *payload* as a single SSE data line."""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


_SSE_DONE = "data: [DONE]\n\n"

# SSE comment used as keepalive — browsers and proxies ignore it,
# but it resets idle-timeout clocks on every intermediate hop.
_SSE_HEARTBEAT = ": heartbeat\n\n"

# Send a heartbeat if no data has been yielded for this many seconds.
_HEARTBEAT_INTERVAL_SECONDS = 15


def _tool_input_events(
    tool_call_id: str,
    tool_name: str,
    args_json: str,
    parsed_args: dict,
) -> list[str]:
    """Return the three SSE events that announce a tool-call's input to the client."""
    return [
        _sse({"type": "tool-input-start", "toolCallId": tool_call_id, "toolName": tool_name}),
        _sse({"type": "tool-input-delta", "toolCallId": tool_call_id, "inputTextDelta": args_json}),
        _sse({"type": "tool-input-available", "toolCallId": tool_call_id, "toolName": tool_name, "input": parsed_args}),
    ]


# ---------------------------------------------------------------------------
# PDF fallback: extract text when model doesn't support native PDF input
# ---------------------------------------------------------------------------


def _extract_text_from_pdf_data_url(data_url: str) -> str:
    """Best-effort text extraction from a base64-encoded PDF data URL.

    Uses ``pypdf`` (already a project dependency) for extraction.
    Falls back to PyMuPDF or pdfminer if available.
    """
    import base64 as b64mod  # noqa: PLC0415
    import io  # noqa: PLC0415

    try:
        if "," not in data_url:
            return ""
        b64_data = data_url.split(",", 1)[1]
        pdf_bytes = b64mod.b64decode(b64_data)

        # pypdf is a project dependency — try it first.
        try:
            from pypdf import PdfReader  # noqa: PLC0415
            reader = PdfReader(io.BytesIO(pdf_bytes))
            pages = [page.extract_text() or "" for page in reader.pages]
            text = "\n\n".join(pages).strip()
            if text:
                return text
        except Exception:
            pass

        # Fallback: PyMuPDF
        try:
            import fitz  # noqa: PLC0415  (PyMuPDF)
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            pages = [page.get_text() for page in doc]
            doc.close()
            return "\n\n".join(pages).strip()
        except ImportError:
            pass

        return ""
    except Exception:
        logger.warning("Failed to extract text from PDF data URL", exc_info=True)
        return ""


def _convert_pdf_file_blocks_to_text(messages: list[dict[str, Any]]) -> None:
    """
    In-place convert ``file`` content blocks (PDFs) to ``text`` blocks
    with extracted text.  Used when the model doesn't support PDF input.

    Errors during extraction are logged and converted to informative
    placeholder text so the overall request is never silently broken.
    """
    for msg in messages:
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue

        new_content: list[dict[str, Any]] = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "file":
                file_info = part.get("file") or {}
                file_data = file_info.get("file_data", "")
                filename = file_info.get("filename", "document.pdf")

                if not file_data:
                    logger.warning(
                        "PDF file block for '%s' has no file_data; "
                        "replacing with placeholder text.",
                        filename,
                    )
                    new_content.append({
                        "type": "text",
                        "text": f"[Attached PDF: {filename} — no file data provided]",
                    })
                    continue

                try:
                    text = _extract_text_from_pdf_data_url(file_data)
                except Exception:
                    logger.error(
                        "Unexpected error extracting text from PDF '%s'",
                        filename,
                        exc_info=True,
                    )
                    text = ""

                if text:
                    new_content.append({
                        "type": "text",
                        "text": f"[PDF: {filename}]\n{text}",
                    })
                else:
                    logger.warning(
                        "Could not extract any text from PDF '%s'. "
                        "The PDF may be image-only or corrupted.",
                        filename,
                    )
                    new_content.append({
                        "type": "text",
                        "text": (
                            f"[Attached PDF: {filename} — could not extract text. "
                            f"The PDF may be image-only or corrupted.]"
                        ),
                    })
            else:
                new_content.append(part)

        msg["content"] = new_content


# ---------------------------------------------------------------------------
# ChatService
# ---------------------------------------------------------------------------


class ChatService:
    """Main streaming-chat orchestration service."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        _init_tool_defs()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def stream_chat(
        self,
        messages: list[dict],
        model_config: ModelConfig,
        system_prompt: str,
        xml_context: str,
        current_xml: str = "",
    ) -> AsyncGenerator[str, None]:
        """
        Yield UIMessageStream-formatted SSE events for a single chat turn.

        Parameters
        ----------
        messages:
            Conversation message history (already preprocessed).
        model_config:
            Resolved ``ModelConfig`` (model_id, api_key, base_url, …).
        system_prompt:
            The main system prompt text.
        xml_context:
            Current diagram XML to inject as a second system message.
        current_xml:
            Current diagram XML for tool context.
        """
        import litellm  # noqa: PLC0415 (deferred to avoid startup cost)
        single_system = getattr(model_config, "single_system", False)

        messages = self._build_messages(
            system_prompt=system_prompt,
            xml_context=xml_context,
            messages=list(messages or []),
            single_system=single_system,
        )

        # Always extract text from PDFs server-side using pypdf.
        # Native PDF file input (litellm ``file`` content blocks) is
        # unreliable across providers — some models silently hang.
        # Server-side extraction with pypdf is fast and universal.
        _convert_pdf_file_blocks_to_text(messages)

        tool_defs = _CACHED_TOOL_DEFS

        # Shared tool context — xml is updated after each server-side tool call.
        tool_context = ToolContext(
            current_xml=current_xml or "",
            shape_library_dir="",  # filled by route if needed
            settings=self.settings,
        )

        total_usage: dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

        # Generate the top-level message id for this assistant turn.
        message_id = _nanoid("msg_")

        # Emit the stream-start event.
        yield _sse({"type": "start", "messageId": message_id})

        # Queue used to pass heartbeat signals from the background heartbeat
        # task back to this generator so they can be yielded as SSE comments.
        heartbeat_queue: asyncio.Queue[None] = asyncio.Queue()

        for step in range(self.settings.MAX_TOOL_STEPS):
            # ------------------------------------------------------------------
            # Build litellm call kwargs
            # ------------------------------------------------------------------
            call_kwargs: dict[str, Any] = {
                "model": model_config.model_id,
                "messages": messages,
                "stream": True,
                "tools": tool_defs,
                "tool_choice": "auto",
                "max_tokens": self.settings.MAX_OUTPUT_TOKENS,
            }

            if model_config.api_key:
                call_kwargs["api_key"] = model_config.api_key
            if model_config.base_url:
                call_kwargs["api_base"] = model_config.base_url
            if self.settings.TEMPERATURE is not None:
                call_kwargs["temperature"] = self.settings.TEMPERATURE

            # Merge provider-specific extra params (thinking budget, etc.).
            call_kwargs.update(model_config.extra_params)

            # ------------------------------------------------------------------
            # Stream response and collect tool-call fragments
            # ------------------------------------------------------------------
            tool_calls_acc: dict[int, dict] = {}  # index → accumulated call
            finish_reason: str | None = None
            assistant_text = ""

            # Track whether we have opened a text/reasoning block in this step.
            text_id: str | None = None
            text_block_open = False
            reasoning_id: str | None = None
            reasoning_block_open = False

            try:
                # Use a heartbeat task to keep connection alive while waiting
                # for the LLM provider to start streaming.
                response_stream = await self._await_with_heartbeat(
                    litellm.acompletion(**call_kwargs),  # type: ignore[attr-defined]
                    heartbeat_queue,
                )
            except Exception as exc:
                logger.error("litellm.acompletion failed: %s", exc, exc_info=True)
                for event in self._error_events(exc):
                    yield event
                return

            # Drain any heartbeats accumulated during acompletion() await.
            while not heartbeat_queue.empty():
                heartbeat_queue.get_nowait()
                yield _SSE_HEARTBEAT

            try:
                last_data_time = time.monotonic()
                async for chunk in response_stream:
                    # Emit heartbeats if the stream has been idle.
                    now = time.monotonic()
                    if now - last_data_time >= _HEARTBEAT_INTERVAL_SECONDS:
                        yield _SSE_HEARTBEAT
                    last_data_time = now

                    delta = chunk.choices[0].delta if chunk.choices else None
                    if delta is None:
                        continue

                    # Usage may be reported on the final chunk.
                    if hasattr(chunk, "usage") and chunk.usage:
                        usage = chunk.usage
                        total_usage["prompt_tokens"] += (
                            getattr(usage, "prompt_tokens", 0) or 0
                        )
                        total_usage["completion_tokens"] += (
                            getattr(usage, "completion_tokens", 0) or 0
                        )
                        total_usage["total_tokens"] += (
                            getattr(usage, "total_tokens", 0) or 0
                        )

                    finish_reason = chunk.choices[0].finish_reason or finish_reason

                    # ── Reasoning / thinking tokens (optional) ──────────────
                    # AI SDK v6 UIMessageStream uses reasoning-start / reasoning-delta / reasoning-end
                    reasoning_content = getattr(delta, "reasoning_content", None)
                    if reasoning_content:
                        if not reasoning_block_open:
                            reasoning_id = _nanoid("reasoning_")
                            yield _sse({"type": "reasoning-start", "id": reasoning_id})
                            reasoning_block_open = True
                        yield _sse(
                            {
                                "type": "reasoning-delta",
                                "id": reasoning_id,
                                "delta": reasoning_content,
                            }
                        )

                    # ── Text delta ───────────────────────────────────────────
                    if delta.content:
                        if not text_block_open:
                            text_id = _nanoid("text_")
                            yield _sse({"type": "text-start", "id": text_id})
                            text_block_open = True

                        assistant_text += delta.content
                        yield _sse(
                            {"type": "text-delta", "id": text_id, "delta": delta.content}
                        )

                    # ── Tool-call deltas ─────────────────────────────────────
                    if delta.tool_calls:
                        for tc in delta.tool_calls:
                            idx = tc.index if hasattr(tc, "index") else 0
                            if idx not in tool_calls_acc:
                                tool_calls_acc[idx] = {
                                    "id": "",
                                    "name": "",
                                    "arguments_raw": "",
                                }
                            acc = tool_calls_acc[idx]
                            if tc.id:
                                acc["id"] = tc.id
                            if tc.function and tc.function.name:
                                acc["name"] = tc.function.name
                            if tc.function and tc.function.arguments:
                                acc["arguments_raw"] += tc.function.arguments
            except Exception as exc:
                logger.error("Stream processing failed: %s", exc, exc_info=True)
                if reasoning_block_open and reasoning_id:
                    yield _sse({"type": "reasoning-end", "id": reasoning_id})
                if text_block_open and text_id:
                    yield _sse({"type": "text-end", "id": text_id})
                for event in self._error_events(exc):
                    yield event
                return

            # Close open blocks from this step.
            if reasoning_block_open and reasoning_id:
                yield _sse({"type": "reasoning-end", "id": reasoning_id})
                reasoning_block_open = False
            if text_block_open and text_id:
                yield _sse({"type": "text-end", "id": text_id})
                text_block_open = False

            # ------------------------------------------------------------------
            # No tool calls → final text response, exit loop.
            # ------------------------------------------------------------------
            if not tool_calls_acc:
                break

            # ------------------------------------------------------------------
            # Build assistant message with tool-call intents for history.
            # Uses the litellm/OpenAI format: text goes in "content" as a
            # plain string, tool calls go in a top-level "tool_calls" list.
            # ------------------------------------------------------------------
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": assistant_text or "",
            }

            # Parse and validate each tool call's JSON arguments.
            # When the LLM hit max_tokens (finish_reason "length"),
            # tool-call JSON may be truncated beyond repair.
            output_truncated = finish_reason == "length"
            parsed_per_idx: dict[int, dict] = {}
            tool_calls_list: list[dict] = []
            for idx in sorted(tool_calls_acc.keys()):
                acc = tool_calls_acc[idx]
                tool_name = acc["name"]
                raw_args = acc["arguments_raw"]
                parsed_args = self._handle_truncated_tool_call(
                    tool_name, raw_args, output_truncated=output_truncated,
                )
                parsed_per_idx[idx] = parsed_args

                # Ensure the LLM id is set; fall back to a generated one.
                if not acc["id"]:
                    acc["id"] = _nanoid("call_")

                tool_calls_list.append(
                    {
                        "id": acc["id"],
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": json.dumps(parsed_args, ensure_ascii=False),
                        },
                    }
                )

            if tool_calls_list:
                assistant_msg["tool_calls"] = tool_calls_list

            messages.append(assistant_msg)

            # ------------------------------------------------------------------
            # Emit tool events.
            #
            # Client-side tools (display_diagram, edit_diagram, append_diagram)
            # are NOT executed server-side.  The server only emits
            # tool-input events so the frontend can render and execute them.
            # Server-side tools are executed here and their output is fed
            # back to the LLM for another generation round.
            # ------------------------------------------------------------------
            needs_another_round = False

            for idx in sorted(tool_calls_acc.keys()):
                acc = tool_calls_acc[idx]
                tool_name = acc["name"]
                tool_call_id = acc["id"]
                parsed_args = parsed_per_idx[idx]
                args_json = json.dumps(parsed_args, ensure_ascii=False)

                if tool_name in CLIENT_SIDE_TOOLS:
                    # Client-side tool — just emit SSE events for the
                    # frontend; no server-side execution.
                    for event in _tool_input_events(tool_call_id, tool_name, args_json, parsed_args):
                        yield event

                else:
                    # Server-side tool — emit input events, execute,
                    # then emit output.
                    for event in _tool_input_events(tool_call_id, tool_name, args_json, parsed_args):
                        yield event

                    result = await self._execute_tool(
                        name=tool_name,
                        arguments=parsed_args,
                        context=tool_context,
                    )

                    needs_another_round = True
                    if result.success:
                        yield _sse(
                            {
                                "type": "tool-output-available",
                                "toolCallId": tool_call_id,
                                "output": result.content,
                            }
                        )
                    else:
                        yield _sse(
                            {
                                "type": "tool-output-error",
                                "toolCallId": tool_call_id,
                                "errorText": result.content,
                            }
                        )

                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "name": tool_name,
                            "content": result.content,
                        }
                    )

            # If nothing requires another LLM round, we are done.
            if not needs_another_round:
                break

        # ------------------------------------------------------------------
        # Emit finish + sentinel
        # ------------------------------------------------------------------
        yield _sse({"type": "finish"})
        yield _SSE_DONE

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_messages(
        self,
        system_prompt: str,
        xml_context: str,
        messages: list[Any],
        single_system: bool,
    ) -> list[dict]:
        """
        Construct the final messages list for litellm.

        When *single_system* is True (e.g. MiniMax, GLM), the main system
        prompt and the XML context are concatenated into a single system
        message at the top of the conversation.  Otherwise two separate
        system messages are used so that providers supporting prompt caching
        can cache the static system prompt independently.
        """
        result: list[dict] = []

        if single_system:
            combined = system_prompt
            if xml_context and xml_context.strip():
                combined = f"{system_prompt}\n\n## Current Diagram XML\n{xml_context}"
            result.append({"role": "system", "content": combined})
        else:
            result.append({"role": "system", "content": system_prompt})
            if xml_context and xml_context.strip():
                result.append(
                    {
                        "role": "system",
                        "content": f"## Current Diagram XML\n{xml_context}",
                    }
                )

        # Append conversation history (skip any leading system messages from
        # the client — we already injected ours above).
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            if msg.get("role") == "system":
                continue
            result.append(msg)

        return result

    async def _execute_tool(
        self,
        name: str,
        arguments: dict,
        context: ToolContext,
    ) -> ToolResult:
        """Dispatch a tool call, update shared XML context, and return the result."""
        try:
            result = await dispatch_tool(name, arguments, context)
            if result.xml is not None:
                context.current_xml = result.xml
            return result
        except Exception as exc:  # noqa: BLE001
            logger.error("Tool '%s' raised an exception: %s", name, exc, exc_info=True)
            return ToolResult(
                success=False,
                content=f"Tool '{name}' failed with an internal error: {exc}",
            )

    @staticmethod
    async def _await_with_heartbeat(
        coro: Any,
        queue: asyncio.Queue[None],
    ) -> Any:
        """
        Await *coro* while pushing heartbeat signals into *queue* every
        ``_HEARTBEAT_INTERVAL_SECONDS``.  The caller (an async generator)
        drains the queue and yields SSE heartbeat comments to keep the
        HTTP connection alive through proxies and load balancers.
        """
        async def _heartbeat_producer() -> None:
            while True:
                await asyncio.sleep(_HEARTBEAT_INTERVAL_SECONDS)
                await queue.put(None)

        heartbeat_task = asyncio.create_task(_heartbeat_producer())
        try:
            return await coro
        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

    @staticmethod
    def _error_events(exc: Exception) -> list[str]:
        """Return SSE events that display *exc* as a chat error and close the stream."""
        error_msg = str(exc)
        for prefix in (
            "litellm.BadRequestError: ",
            "litellm.AuthenticationError: ",
            "litellm.RateLimitError: ",
        ):
            if error_msg.startswith(prefix):
                error_msg = error_msg[len(prefix):]
                break
        tid = _nanoid("text_")
        return [
            _sse({"type": "text-start", "id": tid}),
            _sse({"type": "text-delta", "id": tid, "delta": f"⚠️ Error: {error_msg}"}),
            _sse({"type": "text-end", "id": tid}),
            _sse({"type": "finish"}),
            _SSE_DONE,
        ]

    def _handle_truncated_tool_call(
        self,
        name: str,
        raw_json: str,
        *,
        output_truncated: bool = False,
    ) -> dict:
        """
        Attempt JSON repair on *raw_json* (potentially truncated tool-call
        arguments from a streaming LLM response).

        When *output_truncated* is True (finish_reason "length"), the LLM hit
        max_tokens while generating the tool call.  If JSON repair fails we
        extract whatever partial XML we can rather than returning an empty
        fallback — the validation loop will detect the truncation and ask the
        LLM to continue via ``append_diagram``.

        Returns the parsed dict on success, or a safe fallback on failure.
        """
        if not raw_json or not raw_json.strip():
            return get_fallback_tool_input(name)

        repaired = repair_tool_call_json(raw_json)
        if repaired is not None:
            return repaired

        # JSON repair failed.  If the LLM hit max_tokens while emitting a
        # diagram tool call, try to salvage the partial XML from the raw
        # JSON fragment so that display_diagram / append_diagram can detect
        # truncation and the LLM can continue.
        if output_truncated and name in ("display_diagram", "append_diagram"):
            partial_xml = self._extract_partial_xml(raw_json)
            if partial_xml:
                logger.info(
                    "Salvaged %d chars of partial XML from truncated '%s' tool call",
                    len(partial_xml),
                    name,
                )
                return {"xml": partial_xml}

        logger.warning(
            "Could not repair JSON for tool '%s'; using fallback input. "
            "Raw args (first 200 chars): %.200s",
            name,
            raw_json,
        )
        return get_fallback_tool_input(name)

    @staticmethod
    def _extract_partial_xml(raw_json: str) -> str | None:
        """
        Best-effort extraction of partial XML from a truncated JSON string.

        Handles the common pattern ``{"xml": "<mxCell ...``  where the JSON
        string and object were never closed.
        """
        # Look for the start of the XML value after "xml":
        import re  # noqa: PLC0415

        m = re.search(r'"xml"\s*:\s*"', raw_json)
        if not m:
            return None

        # Everything after the opening quote is (escaped) XML content.
        content = raw_json[m.end():]

        # Unescape JSON string escapes.
        content = (
            content
            .replace('\\"', '"')
            .replace("\\n", "\n")
            .replace("\\t", "\t")
            .replace("\\\\", "\\")
        )

        # Strip any trailing incomplete escape or quote.
        content = content.rstrip("\\").rstrip('"').rstrip()

        # Must contain at least one mxCell to be useful.
        if "<mxCell" not in content:
            return None

        return content
