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
* ``display_diagram``, ``edit_diagram``, and ``append_diagram`` stream their
  input to the frontend for preview, but execution now happens on the server.
* ``get_shape_library`` is also executed on the server and its result is fed
  back to the LLM for another generation round (multi-step).
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
import json
import logging
from pathlib import Path
import random
import string
from dataclasses import dataclass as _dataclass
from dataclasses import field as _field
from typing import Any, AsyncGenerator

from openai import AsyncOpenAI

from app.config import Settings
from app.middleware.request_context import get_request_id
from app.models.chat import ChatRequest
from app.providers.base import ModelConfig
from app.services.json_repair import get_fallback_tool_input, repair_tool_call_json
from app.tools.registry import ToolContext, ToolResult, dispatch_tool, get_tool_definitions
from app.tools.layout_policy import apply_display_diagram_layout_defaults

logger = logging.getLogger(__name__)
_SHAPE_LIBRARY_DIR = str(
    Path(__file__).resolve().parents[2] / "docs" / "shape-libraries"
)

# Cache tool definitions at module level — the registry never changes at runtime.
_CACHED_TOOL_DEFS: list[dict] = []


def _init_tool_defs() -> None:
    """Populate the cached tool definitions (called once on first import of tools)."""
    global _CACHED_TOOL_DEFS
    if not _CACHED_TOOL_DEFS:
        _CACHED_TOOL_DEFS = get_tool_definitions()

# ---------------------------------------------------------------------------
# Diagram tools still stream their input to the frontend so the canvas can
# preview partial XML / operations while the model is generating them.
# Unlike the previous client-executed flow, the server now executes these
# tools itself and returns structured output for the final result.
# ---------------------------------------------------------------------------
STREAMED_INPUT_TOOLS = {"display_diagram", "edit_diagram", "append_diagram"}

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
_HEARTBEAT_INTERVAL_SECONDS = 8

# Coalesce provider tool-call argument fragments before forwarding them to the
# browser. Sending every tiny XML token causes AI SDK partial-JSON reparsing on
# each event, which can starve normal text/reasoning rendering on large diagrams.
_TOOL_INPUT_DELTA_FLUSH_CHARS = 768


def _tool_input_available_event(
    tool_call_id: str,
    tool_name: str,
    parsed_args: dict,
) -> str:
    """Return the finalized tool-input event once the full JSON is available."""
    return _sse(
        {
            "type": "tool-input-available",
            "toolCallId": tool_call_id,
            "toolName": tool_name,
            "input": parsed_args,
        }
    )


def _tool_output_payload(tool_name: str, result: ToolResult) -> Any:
    """Return the UI-facing tool output payload for a completed tool."""
    if tool_name not in STREAMED_INPUT_TOOLS:
        return result.content

    payload: dict[str, Any] = {
        "message": result.content,
        "success": result.success,
        "isTruncated": result.is_truncated,
    }
    if result.xml is not None:
        payload["xml"] = result.xml
    return payload


# ---------------------------------------------------------------------------
# OpenAI Responses API → Chat Completions chunk adapter
# ---------------------------------------------------------------------------
# The stream processing loop in ChatService.stream_chat expects
# Chat-Completions-style chunks with ``chunk.choices[0].delta``.
# This adapter converts Responses API events into that shape so the
# downstream code works unchanged.
# ---------------------------------------------------------------------------


@_dataclass
class _FakeFunction:
    name: str | None = None
    arguments: str | None = None


@_dataclass
class _FakeToolCall:
    index: int = 0
    id: str | None = None
    function: _FakeFunction = _field(default_factory=_FakeFunction)


@_dataclass
class _FakeDelta:
    content: str | None = None
    reasoning_content: str | None = None
    tool_calls: list[_FakeToolCall] | None = None


@_dataclass
class _FakeChoice:
    delta: _FakeDelta = _field(default_factory=_FakeDelta)
    finish_reason: str | None = None


@_dataclass
class _FakeUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@_dataclass
class _FakeChunk:
    choices: list[_FakeChoice] = _field(default_factory=list)
    usage: _FakeUsage | None = None


class _ResponsesStreamAdapter:
    """
    Wraps an OpenAI Responses API async stream and yields
    Chat-Completions-compatible ``_FakeChunk`` objects.
    """

    def __init__(self, stream: Any) -> None:
        self._stream = stream
        # Track tool call indices by item_id (and call_id aliases)
        self._tool_indices: dict[str, int] = {}
        self._tool_call_ids: dict[str, str] = {}  # item_id → call_id
        self._next_tool_idx = 0

    def _ensure_tool_index(self, item_id: str) -> int:
        """Register an item_id in the tool index map, returning its index."""
        if item_id and item_id not in self._tool_indices:
            self._tool_indices[item_id] = self._next_tool_idx
            self._next_tool_idx += 1
        return self._tool_indices.get(item_id, 0)

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self) -> AsyncGenerator[_FakeChunk, None]:
        async for event in self._stream:
            event_type = getattr(event, "type", "")
            if event_type not in (
                "response.function_call_arguments.delta",
                "response.reasoning.delta",
                "response.reasoning_summary_text.delta",
                "response.output_text.delta",
            ):
                logger.debug("[Responses API event] type=%s data=%s", event_type, repr(event)[:300])

            # ── Reasoning (all reasoning-related events) ────────────
            if event_type == "response.reasoning_summary_text.delta":
                delta = _FakeDelta(reasoning_content=event.delta)
                yield _FakeChunk(choices=[_FakeChoice(delta=delta)])

            elif event_type == "response.reasoning.delta":
                # Raw reasoning delta — may be a string or structured object
                raw = event.delta
                text = None
                if isinstance(raw, str):
                    text = raw
                elif isinstance(raw, dict):
                    text = raw.get("text") or raw.get("content")
                elif hasattr(raw, "text"):
                    text = raw.text
                if text:
                    delta = _FakeDelta(reasoning_content=text)
                    yield _FakeChunk(choices=[_FakeChoice(delta=delta)])

            # ── Text delta ───────────────────────────────────────────
            elif event_type == "response.output_text.delta":
                delta = _FakeDelta(content=event.delta)
                yield _FakeChunk(choices=[_FakeChoice(delta=delta)])

            # ── Function call arguments delta ────────────────────────
            elif event_type == "response.function_call_arguments.delta":
                item_id = getattr(event, "item_id", "")
                idx = self._ensure_tool_index(item_id)
                tc = _FakeToolCall(
                    index=idx,
                    function=_FakeFunction(arguments=event.delta),
                )
                delta = _FakeDelta(tool_calls=[tc])
                yield _FakeChunk(choices=[_FakeChoice(delta=delta)])

            # ── Function call done — emit tool name + call_id ────────
            elif event_type == "response.function_call_arguments.done":
                item_id = getattr(event, "item_id", "")
                idx = self._ensure_tool_index(item_id)
                # Use the call_id registered by .added, falling back to item_id
                call_id = self._tool_call_ids.get(item_id, item_id) or _nanoid("call_")
                tc = _FakeToolCall(
                    index=idx,
                    id=call_id,
                    function=_FakeFunction(
                        name=getattr(event, "name", ""),
                    ),
                )
                delta = _FakeDelta(tool_calls=[tc])
                yield _FakeChunk(choices=[_FakeChoice(delta=delta)])

            # ── Output item added — capture function name + call_id ──
            elif event_type == "response.output_item.added":
                item = getattr(event, "item", None)
                if item and getattr(item, "type", "") == "function_call":
                    # Use item.id as key — this matches event.item_id in subsequent events
                    item_id = getattr(item, "id", "")
                    call_id = getattr(item, "call_id", "") or item_id
                    fn_name = getattr(item, "name", "")
                    idx = self._ensure_tool_index(item_id)
                    # Map call_id → same index and store the call_id for later lookup
                    self._tool_call_ids[item_id] = call_id
                    if call_id and call_id != item_id and call_id not in self._tool_indices:
                        self._tool_indices[call_id] = self._tool_indices.get(item_id, 0)
                    tc = _FakeToolCall(
                        index=idx,
                        id=call_id,
                        function=_FakeFunction(name=fn_name),
                    )
                    delta = _FakeDelta(tool_calls=[tc])
                    yield _FakeChunk(choices=[_FakeChoice(delta=delta)])

            # ── Completed — emit finish_reason + usage ───────────────
            elif event_type in ("response.completed", "response.failed", "response.incomplete"):
                finish_reason = "stop"
                if event_type == "response.incomplete":
                    finish_reason = "length"
                usage_obj = None
                resp = getattr(event, "response", None)
                if resp:
                    resp_usage = getattr(resp, "usage", None)
                    if resp_usage:
                        usage_obj = _FakeUsage(
                            prompt_tokens=getattr(resp_usage, "input_tokens", 0) or 0,
                            completion_tokens=getattr(resp_usage, "output_tokens", 0) or 0,
                            total_tokens=(getattr(resp_usage, "input_tokens", 0) or 0)
                            + (getattr(resp_usage, "output_tokens", 0) or 0),
                        )
                    # Check if any function calls present → finish_reason = "tool_calls"
                    output = getattr(resp, "output", []) or []
                    for item in output:
                        if getattr(item, "type", "") == "function_call":
                            finish_reason = "tool_calls"
                            break
                yield _FakeChunk(
                    choices=[_FakeChoice(finish_reason=finish_reason)],
                    usage=usage_obj,
                )

            # ── Error event ──────────────────────────────────────────
            elif event_type == "response.error":
                error = getattr(event, "error", None)
                msg = str(error) if error else "Unknown Responses API error"
                raise RuntimeError(msg)


# ---------------------------------------------------------------------------
# PDF fallback: extract text when model doesn't support native PDF input
# ---------------------------------------------------------------------------


def _extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    """Best-effort text extraction from raw PDF bytes.

    Uses ``pypdf`` (already a project dependency) for extraction.
    Falls back to PyMuPDF if available.
    """
    import io  # noqa: PLC0415

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


def _extract_text_from_pdf_data_url(data_url: str) -> str:
    """Extract text from a base64-encoded PDF data URL."""
    import base64 as b64mod  # noqa: PLC0415

    try:
        if "," not in data_url:
            return ""
        b64_data = data_url.split(",", 1)[1]
        pdf_bytes = b64mod.b64decode(b64_data)
        return _extract_text_from_pdf_bytes(pdf_bytes)
    except Exception:
        logger.warning("Failed to extract text from PDF data URL", exc_info=True)
        return ""


def _fetch_pdf_bytes(url: str) -> bytes:
    """Download PDF from *url* synchronously.  Raises on failure."""
    import httpx  # noqa: PLC0415

    resp = httpx.get(url, follow_redirects=True, timeout=30)
    resp.raise_for_status()
    return resp.content


def _convert_pdf_file_blocks_to_text(messages: list[dict[str, Any]]) -> None:
    """
    In-place convert ``file`` content blocks (PDFs) to ``text`` blocks
    with extracted text.  Used when the model doesn't support PDF input.

    Handles three kinds of PDF file blocks:
    - ``file_data``: base64 data-URL  → decode and extract text
    - ``file_url``:  regular HTTP URL  → download, then extract text
    - ``text_fallback``: pre-extracted text → use directly as last resort

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
                file_url = file_info.get("file_url", "")
                text_fallback = file_info.get("text_fallback", "").strip()
                filename = file_info.get("filename", "document.pdf")

                text = ""

                # 1. Base64 data URL
                if file_data:
                    try:
                        text = _extract_text_from_pdf_data_url(file_data)
                    except Exception:
                        logger.error(
                            "Unexpected error extracting text from PDF '%s'",
                            filename,
                            exc_info=True,
                        )

                # 2. Regular HTTP URL — download then extract
                if not text and file_url:
                    try:
                        pdf_bytes = _fetch_pdf_bytes(file_url)
                        text = _extract_text_from_pdf_bytes(pdf_bytes)
                    except Exception:
                        logger.error(
                            "Failed to download/extract PDF from URL '%s'",
                            file_url,
                            exc_info=True,
                        )

                # 3. Pre-extracted text fallback
                if not text and text_fallback:
                    text = text_fallback

                if text:
                    new_content.append({
                        "type": "text",
                        "text": f"[PDF: {filename}]\n{text}",
                    })
                elif not file_data and not file_url:
                    logger.warning(
                        "PDF file block for '%s' has no file_data or file_url; "
                        "replacing with placeholder text.",
                        filename,
                    )
                    new_content.append({
                        "type": "text",
                        "text": f"[Attached PDF: {filename} — no file data provided]",
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


def _resolve_pdf_url_blocks(messages: list[dict[str, Any]]) -> None:
    """
    In-place convert ``file_url`` PDF blocks to ``file_data`` blocks by
    downloading the PDF and encoding as a base64 data URL.

    Used in ``base64`` pdf_mode so that litellm receives inline data it
    can forward to any provider.  Blocks that already have ``file_data``
    are left untouched.
    """
    import base64 as b64mod  # noqa: PLC0415

    for msg in messages:
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue

        for part in content:
            if not isinstance(part, dict) or part.get("type") != "file":
                continue
            file_info = part.get("file")
            if not isinstance(file_info, dict):
                continue
            # Already has inline data — nothing to do.
            if file_info.get("file_data"):
                continue
            file_url = file_info.get("file_url", "")
            if not file_url:
                continue

            filename = file_info.get("filename", "document.pdf")
            try:
                pdf_bytes = _fetch_pdf_bytes(file_url)
                b64_str = b64mod.b64encode(pdf_bytes).decode()
                file_info["file_data"] = f"data:application/pdf;base64,{b64_str}"
                file_info.pop("file_url", None)
                file_info.pop("text_fallback", None)
            except Exception:
                logger.error(
                    "Failed to download PDF '%s' from %s for base64 mode; "
                    "falling back to text_fallback if available.",
                    filename,
                    file_url,
                    exc_info=True,
                )
                text_fallback = file_info.get("text_fallback", "").strip()
                if text_fallback:
                    part["type"] = "text"
                    part["text"] = f"[PDF: {filename}]\n{text_fallback}"
                    part.pop("file", None)


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
        pdf_mode: str = "text",
        shape_library_dir: str = _SHAPE_LIBRARY_DIR,
        preferred_shape_library: str | None = None,
        force_diagram_tool: bool = False,
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
        single_system = getattr(model_config, "single_system", False)

        messages = self._build_messages(
            system_prompt=system_prompt,
            xml_context=xml_context,
            messages=list(messages or []),
            single_system=single_system,
        )

        # PDF delivery mode is request-controlled:
        # - "text": extract text server-side with pypdf and send plain text
        # - "base64": keep the original file block and let the model endpoint
        #   handle the PDF natively if it supports it.
        if pdf_mode == "text":
            _convert_pdf_file_blocks_to_text(messages)
        else:
            # base64 mode — resolve any file_url blocks by downloading
            # and converting to base64 data URLs that litellm can handle.
            _resolve_pdf_url_blocks(messages)

        tool_defs = _CACHED_TOOL_DEFS

        # Shared tool context — xml is updated after each server-side tool call.
        tool_context = ToolContext(
            current_xml=current_xml or "",
            shape_library_dir=shape_library_dir,
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
        diagram_retry_used = False
        shape_library_consulted = preferred_shape_library is None
        diagram_tool_emitted = False
        consecutive_truncations = 0

        for step in range(self.settings.MAX_TOOL_STEPS):
            # ------------------------------------------------------------------
            # Stream response and collect tool-call fragments
            # ------------------------------------------------------------------
            tool_calls_acc: dict[int, dict[str, Any]] = {}  # index → accumulated call
            finish_reason: str | None = None
            assistant_text = ""

            # Track whether we have opened a text/reasoning block in this step.
            text_id: str | None = None
            text_block_open = False
            reasoning_id: str | None = None
            reasoning_block_open = False
            step_stats = {
                "text_chars": 0,
                "reasoning_chars": 0,
                "tool_calls_started": 0,
                "tool_delta_events": 0,
                "tool_delta_chars": 0,
            }

            try:
                response_stream = None
                tool_choice_val = self._select_tool_choice(
                    step=step,
                    force_diagram_tool=force_diagram_tool,
                    preferred_shape_library=preferred_shape_library,
                    shape_library_consulted=shape_library_consulted,
                    diagram_tool_emitted=diagram_tool_emitted,
                )
                async for event_type, payload in self._await_with_sse_heartbeats(
                    self._create_provider_stream(
                        model_config=model_config,
                        messages=messages,
                        tools=tool_defs,
                        tool_choice=tool_choice_val,
                    ),
                ):
                    if event_type == "heartbeat":
                        yield _SSE_HEARTBEAT
                        continue
                    response_stream = payload
                    break
            except Exception as exc:
                logger.error("Provider stream initialization failed: %s", exc, exc_info=True)
                for event in self._error_events(exc):
                    yield event
                return

            try:
                async for event_type, payload in self._iterate_with_sse_heartbeats(
                    response_stream,
                ):
                    if event_type == "heartbeat":
                        yield _SSE_HEARTBEAT
                        continue

                    chunk = payload
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
                        step_stats["reasoning_chars"] += len(reasoning_content)

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
                        step_stats["text_chars"] += len(delta.content)

                    # ── Tool-call deltas ─────────────────────────────────────
                    # Close reasoning/text blocks before tool events start
                    # (AI SDK expects reasoning-end before tool-input-start)
                    if delta.tool_calls:
                        if reasoning_block_open and reasoning_id:
                            yield _sse({"type": "reasoning-end", "id": reasoning_id})
                            reasoning_block_open = False
                        if text_block_open and text_id:
                            yield _sse({"type": "text-end", "id": text_id})
                            text_block_open = False
                        for tc in delta.tool_calls:
                            idx = tc.index if hasattr(tc, "index") else 0
                            if idx not in tool_calls_acc:
                                tool_calls_acc[idx] = {
                                    "id": tc.id or _nanoid("call_"),
                                    "name": "",
                                    "arguments_raw": "",
                                    "input_started": False,
                                    "has_emitted_delta": False,
                                    "pending_arguments_delta": "",
                                }
                            acc = tool_calls_acc[idx]
                            if tc.id and not acc["id"]:
                                acc["id"] = tc.id
                            if tc.function and tc.function.name:
                                acc["name"] = tc.function.name
                            arguments_delta = ""
                            if tc.function and tc.function.arguments:
                                arguments_delta = tc.function.arguments
                                acc["arguments_raw"] += arguments_delta
                                acc["pending_arguments_delta"] += arguments_delta

                            if (
                                acc["name"] in STREAMED_INPUT_TOOLS
                                and not acc["input_started"]
                            ):
                                yield _sse(
                                    {
                                        "type": "tool-input-start",
                                        "toolCallId": acc["id"],
                                        "toolName": acc["name"],
                                    }
                                )
                                acc["input_started"] = True
                                step_stats["tool_calls_started"] += 1

                            should_flush_delta = (
                                acc["name"] in STREAMED_INPUT_TOOLS
                                and acc["input_started"]
                                and acc["pending_arguments_delta"]
                                and (
                                    not acc["has_emitted_delta"]
                                    or len(acc["pending_arguments_delta"])
                                    >= _TOOL_INPUT_DELTA_FLUSH_CHARS
                                )
                            )
                            if should_flush_delta:
                                yield _sse(
                                    {
                                        "type": "tool-input-delta",
                                        "toolCallId": acc["id"],
                                        "inputTextDelta": acc[
                                            "pending_arguments_delta"
                                        ],
                                    }
                                )
                                step_stats["tool_delta_events"] += 1
                                step_stats["tool_delta_chars"] += len(
                                    acc["pending_arguments_delta"]
                                )
                                acc["pending_arguments_delta"] = ""
                                acc["has_emitted_delta"] = True
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
                if (
                    not diagram_retry_used
                    and self._should_retry_for_missing_diagram(
                        messages=messages,
                        current_xml=tool_context.current_xml,
                        assistant_text=assistant_text,
                    )
                ):
                    diagram_retry_used = True
                    messages.append(
                        {
                            "role": "assistant",
                            "content": assistant_text or "",
                        }
                    )
                    messages.append(
                        {
                            "role": "system",
                            "content": (
                                "You responded with text only, but this request still requires "
                                "an actual diagram tool call. In your next response, call "
                                "`display_diagram` to create a new diagram or `edit_diagram` "
                                "to modify the existing one. Do not stop at explanation alone."
                            ),
                        }
                    )
                    continue
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
                parsed_args = apply_display_diagram_layout_defaults(
                    tool_name,
                    parsed_args,
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

            # Compact diagram tool arguments in the history message we
            # just appended.  The full XML is already tracked in
            # tool_context.current_xml; keeping it in conversation
            # history wastes context and accelerates truncation in
            # subsequent steps (especially during append_diagram loops).
            _DIAGRAM_TOOLS = {"display_diagram", "edit_diagram", "append_diagram"}
            if assistant_msg.get("tool_calls"):
                for tc in assistant_msg["tool_calls"]:
                    fn = tc.get("function", {})
                    if fn.get("name") in _DIAGRAM_TOOLS:
                        fn["arguments"] = json.dumps(
                            {"placeholder": "[XML stored in diagram context]"},
                            ensure_ascii=False,
                        )

            # ------------------------------------------------------------------
            # Emit tool events.
            #
            # Diagram tools stream partial input for frontend preview, but all
            # tools are executed on the server. Only tools that need another
            # model round (e.g. get_shape_library, truncated/error recovery)
            # loop back into the LLM.
            # ------------------------------------------------------------------
            needs_another_round = False

            for idx in sorted(tool_calls_acc.keys()):
                acc = tool_calls_acc[idx]
                tool_name = acc["name"]
                tool_call_id = acc["id"]
                parsed_args = parsed_per_idx[idx]

                if (
                    tool_name in STREAMED_INPUT_TOOLS
                    and acc["input_started"]
                    and acc["pending_arguments_delta"]
                ):
                    yield _sse(
                        {
                            "type": "tool-input-delta",
                            "toolCallId": tool_call_id,
                            "inputTextDelta": acc["pending_arguments_delta"],
                        }
                    )
                    step_stats["tool_delta_events"] += 1
                    step_stats["tool_delta_chars"] += len(
                        acc["pending_arguments_delta"]
                    )
                    acc["pending_arguments_delta"] = ""
                    acc["has_emitted_delta"] = True

                if tool_name in STREAMED_INPUT_TOOLS:
                    diagram_tool_emitted = True
                yield _tool_input_available_event(
                    tool_call_id,
                    tool_name,
                    parsed_args,
                )

                result = await self._execute_tool(
                    name=tool_name,
                    arguments=parsed_args,
                    context=tool_context,
                )
                if tool_name == "get_shape_library" and result.success:
                    shape_library_consulted = True

                needs_followup = (
                    tool_name == "get_shape_library"
                    or result.is_truncated
                    or not result.success
                )
                needs_another_round = needs_another_round or needs_followup

                if result.success and not result.is_truncated:
                    yield _sse(
                        {
                            "type": "tool-output-available",
                            "toolCallId": tool_call_id,
                            "output": _tool_output_payload(tool_name, result),
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

            logger.info(
                "[chat stream] request_id=%s step=%s finish_reason=%s text_chars=%s reasoning_chars=%s tool_calls_started=%s tool_delta_events=%s tool_delta_chars=%s tool_calls_total=%s",
                get_request_id(),
                step,
                finish_reason,
                step_stats["text_chars"],
                step_stats["reasoning_chars"],
                step_stats["tool_calls_started"],
                step_stats["tool_delta_events"],
                step_stats["tool_delta_chars"],
                len(tool_calls_acc),
            )

            # Track consecutive truncations.  If append keeps failing,
            # force-complete with whatever XML we have rather than
            # looping until MAX_TOOL_STEPS (each iteration grows the
            # conversation history, leaving the LLM less output budget).
            step_had_truncation = any(
                acc["name"] in ("display_diagram", "append_diagram")
                for acc in tool_calls_acc.values()
            ) and needs_another_round
            if step_had_truncation:
                consecutive_truncations += 1
            else:
                consecutive_truncations = 0

            if consecutive_truncations >= 3 and tool_context.current_xml:
                from app.tools._xml_utils import (  # noqa: PLC0415
                    add_mxgraph_wrapper,
                    has_mxcell,
                    recover_partial_xml,
                )

                partial = tool_context.current_xml
                recovered = recover_partial_xml(partial)
                if recovered and has_mxcell(recovered):
                    full_xml = add_mxgraph_wrapper(recovered)
                    tool_context.current_xml = full_xml
                    logger.warning(
                        "[chat stream] force-completing diagram after %d "
                        "consecutive truncations (%d chars recovered)",
                        consecutive_truncations,
                        len(recovered),
                    )
                    yield _sse(
                        {
                            "type": "tool-output-available",
                            "toolCallId": "force_complete",
                            "output": {
                                "message": (
                                    "Diagram was too large to generate completely. "
                                    "Displaying what was generated so far."
                                ),
                                "xml": full_xml,
                            },
                        }
                    )
                    break

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

    @staticmethod
    def _is_openai_reasoning_model(model_id: str) -> bool:
        """Return True when *model_id* is an OpenAI reasoning-capable model."""
        lower = (model_id or "").lower()
        return any(tok in lower for tok in ("o1", "o3", "o4", "gpt-5"))

    def _create_provider_stream(
        self,
        *,
        model_config: ModelConfig,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: str | dict[str, Any],
    ) -> Any:
        """Create the provider streaming request for the current step."""
        if model_config.provider == "openai":
            client_kwargs: dict[str, Any] = {}
            if model_config.api_key:
                client_kwargs["api_key"] = model_config.api_key
            if model_config.base_url:
                client_kwargs["base_url"] = model_config.base_url
            if self.settings.OPENAI_ORGANIZATION:
                client_kwargs["organization"] = self.settings.OPENAI_ORGANIZATION
            if self.settings.OPENAI_PROJECT:
                client_kwargs["project"] = self.settings.OPENAI_PROJECT

            client = AsyncOpenAI(**client_kwargs)
            raw_model = self._provider_model_id(model_config.model_id)
            reasoning_effort = model_config.extra_params.get("reasoning_effort")
            reasoning_summary = model_config.extra_params.get("reasoning_summary")

            api_mode = self.settings.OPENAI_API_MODE  # "auto" | "completions" | "responses"
            is_direct_openai = not model_config.base_url
            is_reasoning_model = self._is_openai_reasoning_model(raw_model)

            # Auto-upgrade to Responses API when needed:
            # 1. Explicitly set to "responses"
            # 2. "auto" mode with a reasoning model
            # 3. Direct OpenAI + reasoning model + tools + reasoning_effort
            #    (Chat Completions does not support this combo)
            use_responses = (
                api_mode == "responses"
                or (api_mode == "auto" and is_reasoning_model)
                or (is_direct_openai and is_reasoning_model and tools and reasoning_effort)
            )

            if use_responses:
                return self._create_openai_responses_stream(
                    client=client,
                    model=raw_model,
                    messages=messages,
                    tools=tools,
                    tool_choice=tool_choice,
                    reasoning_effort=reasoning_effort,
                    reasoning_summary=reasoning_summary,
                )

            # Chat Completions API
            call_kwargs: dict[str, Any] = {
                "model": raw_model,
                "messages": messages,
                "stream": True,
                "stream_options": {"include_usage": True},
                "tools": tools,
                "tool_choice": tool_choice,
            }
            call_kwargs.update(
                self._openai_token_limit_kwargs(raw_model, self.settings.MAX_OUTPUT_TOKENS)
            )

            if self.settings.TEMPERATURE is not None:
                call_kwargs["temperature"] = self.settings.TEMPERATURE
            # OpenAI's native Chat Completions API does not support
            # reasoning_effort + tools together.  However, proxy endpoints
            # (LiteLLM, etc.) translate reasoning_effort for providers that
            # DO support both (e.g. Gemini thinking + tools).  We only
            # suppress reasoning_effort when hitting OpenAI directly.
            if reasoning_effort:
                if is_direct_openai and tools:
                    logger.warning(
                        "reasoning_effort=%s ignored: OpenAI Chat Completions API does not "
                        "support reasoning_effort with tools. Use OPENAI_API_MODE=responses.",
                        reasoning_effort,
                    )
                else:
                    call_kwargs["reasoning_effort"] = reasoning_effort

            return client.chat.completions.create(**call_kwargs)

        import litellm  # noqa: PLC0415

        call_kwargs = {
            "model": model_config.model_id,
            "messages": messages,
            "stream": True,
            "tools": tools,
            "tool_choice": tool_choice,
            "max_tokens": self.settings.MAX_OUTPUT_TOKENS,
        }
        if model_config.api_key:
            call_kwargs["api_key"] = model_config.api_key
        if model_config.base_url:
            call_kwargs["api_base"] = model_config.base_url
        if self.settings.TEMPERATURE is not None:
            call_kwargs["temperature"] = self.settings.TEMPERATURE
        call_kwargs.update(model_config.extra_params)

        return litellm.acompletion(**call_kwargs)  # type: ignore[attr-defined]

    async def _create_openai_responses_stream(
        self,
        *,
        client: AsyncOpenAI,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: str | dict[str, Any],
        reasoning_effort: str | None = None,
        reasoning_summary: str | None = None,
    ) -> "_ResponsesStreamAdapter":
        """
        Create an OpenAI Responses API stream and return an adapter that
        yields Chat-Completions-compatible chunks so the caller's stream
        processing loop works unchanged.
        """
        # Convert Chat Completions tool defs → Responses API format
        resp_tools: list[dict[str, Any]] = []
        for td in tools:
            fn = td.get("function", {})
            resp_tools.append({
                "type": "function",
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
                "parameters": fn.get("parameters", {}),
                "strict": False,
            })

        # Convert tool_choice format
        resp_tool_choice: Any = tool_choice
        if isinstance(tool_choice, dict):
            # {"type": "function", "function": {"name": "x"}} → {"type": "function", "name": "x"}
            fn_info = tool_choice.get("function", {})
            if fn_info.get("name"):
                resp_tool_choice = {"type": "function", "name": fn_info["name"]}

        # Convert messages: system role → developer role for Responses API
        # Content parts need type remapping: text→input_text, image_url→input_image, file→input_file
        resp_input: list[dict[str, Any]] = []
        for msg in messages:
            role = msg.get("role", "user")
            if role == "system":
                role = "developer"

            # Preserve tool_calls / tool_call_id for multi-turn
            if msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    fn = tc.get("function", {})
                    resp_input.append({
                        "type": "function_call",
                        "call_id": tc.get("id", ""),
                        "name": fn.get("name", ""),
                        "arguments": fn.get("arguments", "{}"),
                    })
                if msg.get("content"):
                    resp_input.append({"role": role, "content": msg["content"]})
                continue
            if role == "tool":
                resp_input.append({
                    "type": "function_call_output",
                    "call_id": msg.get("tool_call_id", ""),
                    "output": msg.get("content", ""),
                })
                continue

            content = msg.get("content", "")
            if isinstance(content, list):
                converted_parts: list[dict[str, Any]] = []
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    ptype = part.get("type", "")
                    if ptype == "text":
                        converted_parts.append({"type": "input_text", "text": part.get("text", "")})
                    elif ptype == "image_url":
                        image_url = part.get("image_url", {})
                        url = image_url.get("url", "") if isinstance(image_url, dict) else str(image_url)
                        converted_parts.append({"type": "input_image", "image_url": url})
                    elif ptype == "file":
                        file_info = part.get("file", {})
                        converted_parts.append({
                            "type": "input_file",
                            "file_data": file_info.get("file_data", ""),
                            "filename": file_info.get("filename", "file"),
                        })
                    else:
                        converted_parts.append(part)
                content = converted_parts
            resp_input.append({"role": role, "content": content})

        call_kwargs: dict[str, Any] = {
            "model": model,
            "input": resp_input,
            "stream": True,
            "tools": resp_tools,
            "tool_choice": resp_tool_choice,
            "max_output_tokens": self.settings.MAX_OUTPUT_TOKENS,
        }

        if reasoning_effort:
            reasoning_cfg: dict[str, Any] = {"effort": reasoning_effort}
            # Default summary to "auto" so reasoning is visible in the frontend
            reasoning_cfg["summary"] = reasoning_summary or "auto"
            call_kwargs["reasoning"] = reasoning_cfg

        if self.settings.TEMPERATURE is not None:
            call_kwargs["temperature"] = self.settings.TEMPERATURE

        logger.info("[OpenAI Responses API] model=%s, reasoning=%s", model, call_kwargs.get("reasoning"))
        stream = await client.responses.create(**call_kwargs)
        return _ResponsesStreamAdapter(stream)

    @staticmethod
    def _provider_model_id(model_id: str) -> str:
        """Strip the litellm provider prefix when calling the official SDK."""
        return model_id.split("/", 1)[1] if "/" in model_id else model_id

    @staticmethod
    def _openai_token_limit_kwargs(
        model_id: str,
        max_output_tokens: int,
    ) -> dict[str, int]:
        """
        OpenAI reasoning / GPT-5 family models require ``max_completion_tokens``
        instead of ``max_tokens`` on the Chat Completions API.
        """
        lower = (model_id or "").lower()
        if any(token in lower for token in ("gpt-5", "o1", "o3", "o4")):
            return {"max_completion_tokens": max_output_tokens}
        return {"max_tokens": max_output_tokens}

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

    @staticmethod
    def _should_retry_for_missing_diagram(
        messages: list[dict],
        current_xml: str,
        assistant_text: str,
    ) -> bool:
        return bool(assistant_text.strip()) and ChatService._expects_diagram_tool(
            messages=messages,
            current_xml=current_xml,
        )

    @staticmethod
    def _expects_diagram_tool(
        messages: list[dict],
        current_xml: str,
    ) -> bool:
        latest_user_text = ""
        has_attachment = False
        for msg in reversed(messages):
            if not isinstance(msg, dict) or msg.get("role") != "user":
                continue
            content = msg.get("content")
            if isinstance(content, list):
                text_parts: list[str] = []
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    if part.get("type") == "text":
                        text = str(part.get("text", "")).strip()
                        if text:
                            text_parts.append(text)
                    if part.get("type") in {"image_url", "file"}:
                        has_attachment = True
                latest_user_text = "\n".join(text_parts).strip()
            elif isinstance(content, str):
                latest_user_text = content.strip()
            break

        prompt_text = f" {latest_user_text.lower()} "
        create_keywords = (
            " draw ",
            " create ",
            " build ",
            " generate ",
            " make ",
            " show me ",
            " convert ",
            " visualize ",
            " illustrate ",
            " replicate ",
            " reproduce ",
        )
        diagram_keywords = (
            " diagram ",
            " draw.io ",
            " flowchart ",
            " architecture ",
            " workflow ",
            " pipeline ",
            " network ",
            " system design ",
            " sequence ",
            " uml ",
            " erd ",
            " chart ",
            " aws ",
            " azure ",
            " gcp ",
            " kubernetes ",
            " k8s ",
        )
        edit_keywords = (
            " edit ",
            " update ",
            " modify ",
            " revise ",
            " add ",
            " remove ",
            " rearrange ",
            " relayout ",
            " layout ",
        )

        expects_diagram = has_attachment or any(
            keyword in prompt_text for keyword in create_keywords + diagram_keywords
        )
        if not expects_diagram:
            if current_xml and "<mxCell" in current_xml:
                return any(keyword in prompt_text for keyword in edit_keywords)
            return False

        # If there is already a meaningful diagram on the canvas, allow
        # explanatory text-only turns unless the user explicitly asked to draw.
        if (
            current_xml
            and "<mxCell" in current_xml
            and not any(keyword in prompt_text for keyword in create_keywords + edit_keywords)
        ):
            return False

        return True

    @staticmethod
    def _select_tool_choice(
        *,
        step: int,
        force_diagram_tool: bool,
        preferred_shape_library: str | None,
        shape_library_consulted: bool,
        diagram_tool_emitted: bool,
    ) -> Any:
        if preferred_shape_library and not shape_library_consulted:
            return {"type": "function", "function": {"name": "get_shape_library"}}

        if force_diagram_tool and not diagram_tool_emitted:
            return "required"

        return "auto"

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
    async def _await_with_sse_heartbeats(
        awaitable: Any,
    ) -> AsyncGenerator[tuple[str, Any], None]:
        """
        Yield heartbeat ticks while awaiting a single provider call result.

        This keeps the HTTP SSE connection active even before the provider has
        returned the streaming iterator.
        """
        task = asyncio.ensure_future(awaitable)
        try:
            while True:
                done, _ = await asyncio.wait(
                    {task},
                    timeout=_HEARTBEAT_INTERVAL_SECONDS,
                )
                if done:
                    yield ("result", await task)
                    return
                yield ("heartbeat", None)
        finally:
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    @staticmethod
    async def _iterate_with_sse_heartbeats(
        stream: Any,
    ) -> AsyncGenerator[tuple[str, Any], None]:
        """
        Yield heartbeat ticks while waiting for the next provider stream chunk.

        Providers can pause for long thinking/tool-planning intervals between
        chunks.  During those gaps we still need to emit SSE comments so
        browsers and proxies do not treat the connection as idle.
        """
        iterator = stream.__aiter__()
        while True:
            next_chunk_task = asyncio.ensure_future(iterator.__anext__())
            try:
                while True:
                    done, _ = await asyncio.wait(
                        {next_chunk_task},
                        timeout=_HEARTBEAT_INTERVAL_SECONDS,
                    )
                    if done:
                        break
                    yield ("heartbeat", None)

                try:
                    chunk = await next_chunk_task
                except StopAsyncIteration:
                    return

                yield ("chunk", chunk)
            finally:
                if not next_chunk_task.done():
                    next_chunk_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await next_chunk_task

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
            if output_truncated and name in ("display_diagram", "append_diagram"):
                repaired["truncated"] = True
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
                return {"xml": partial_xml, "truncated": True}

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
