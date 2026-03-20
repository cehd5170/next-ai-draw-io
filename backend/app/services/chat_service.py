"""
ChatService — orchestrates streaming LLM calls with tool-use for /chat.

Emits the Vercel AI SDK v6 UIMessageStream protocol so the frontend's
``useChat`` / ``DefaultChatTransport`` can consume the stream directly.

UIMessageStream event format
----------------------------
Every line is ``data: <json>\\n\\n``.  The stream ends with ``data: [DONE]\\n\\n``.

Typical event sequence for a tool-call response::

    data: {"type":"start","messageId":"msg_xxx"}
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

import json
import logging
import random
import string
from typing import Any, AsyncGenerator

from app.config import Settings
from app.models.chat import ChatRequest
from app.providers.base import ModelConfig
from app.services.json_repair import get_fallback_tool_input, repair_tool_call_json
from app.tools.registry import ToolContext, dispatch_tool, get_tool_definitions

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

            # Track whether we have opened a text block in this step.
            text_id: str | None = None
            text_block_open = False

            try:
                response_stream = await litellm.acompletion(**call_kwargs)  # type: ignore[attr-defined]
            except Exception as exc:
                logger.error("litellm.acompletion failed: %s", exc, exc_info=True)
                raise

            async for chunk in response_stream:
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

                # ── Reasoning / thinking tokens (optional) ──────────────────
                reasoning_content = getattr(delta, "reasoning_content", None)
                if reasoning_content:
                    yield _sse(
                        {
                            "type": "reasoning",
                            "id": _nanoid("reasoning_"),
                            "delta": reasoning_content,
                        }
                    )

                # ── Text delta ───────────────────────────────────────────────
                if delta.content:
                    if not text_block_open:
                        text_id = _nanoid("text_")
                        yield _sse({"type": "text-start", "id": text_id})
                        text_block_open = True

                    assistant_text += delta.content
                    yield _sse(
                        {"type": "text-delta", "id": text_id, "delta": delta.content}
                    )

                # ── Tool-call deltas ─────────────────────────────────────────
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

            # Close the text block if one was opened during this step.
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
            # ------------------------------------------------------------------
            assistant_msg: dict[str, Any] = {"role": "assistant", "content": []}
            if assistant_text:
                assistant_msg["content"].append(
                    {"type": "text", "text": assistant_text}
                )

            # Parse and validate each tool call's JSON arguments.
            parsed_per_idx: dict[int, dict] = {}
            for idx in sorted(tool_calls_acc.keys()):
                acc = tool_calls_acc[idx]
                tool_name = acc["name"]
                raw_args = acc["arguments_raw"]
                parsed_args = self._handle_truncated_tool_call(tool_name, raw_args)
                parsed_per_idx[idx] = parsed_args

                # Ensure the LLM id is set; fall back to a generated one.
                if not acc["id"]:
                    acc["id"] = _nanoid("call_")

                assistant_msg["content"].append(
                    {
                        "type": "tool_call",
                        "tool_call_id": acc["id"],
                        "name": tool_name,
                        "input": parsed_args,
                    }
                )

            messages.append(assistant_msg)

            # ------------------------------------------------------------------
            # Emit tool events and execute server-side tools.
            # ------------------------------------------------------------------
            # We need another LLM round only if at least one server-side tool
            # was called and executed.
            has_server_side_tool = False

            for idx in sorted(tool_calls_acc.keys()):
                acc = tool_calls_acc[idx]
                tool_name = acc["name"]
                tool_call_id = acc["id"]
                parsed_args = parsed_per_idx[idx]
                args_json = json.dumps(parsed_args, ensure_ascii=False)

                # tool-input-start
                yield _sse(
                    {
                        "type": "tool-input-start",
                        "toolCallId": tool_call_id,
                        "toolName": tool_name,
                    }
                )

                # tool-input-delta (stream the full serialised args as one delta)
                yield _sse(
                    {
                        "type": "tool-input-delta",
                        "toolCallId": tool_call_id,
                        "inputTextDelta": args_json,
                    }
                )

                # tool-input-available (full input now available)
                yield _sse(
                    {
                        "type": "tool-input-available",
                        "toolCallId": tool_call_id,
                        "toolName": tool_name,
                        "input": parsed_args,
                    }
                )

                if tool_name in CLIENT_SIDE_TOOLS:
                    # Client-side tool: the frontend handles execution.
                    # Do NOT append a tool-result message; the client will call
                    # addToolOutput and the conversation ends here for this turn.
                    logger.debug("Client-side tool '%s' — skipping server execution", tool_name)
                else:
                    # Server-side tool: execute it now.
                    has_server_side_tool = True
                    try:
                        result = await self._execute_tool(
                            name=tool_name,
                            arguments=parsed_args,
                            context=tool_context,
                        )
                        yield _sse(
                            {
                                "type": "tool-output-available",
                                "toolCallId": tool_call_id,
                                "output": result,
                            }
                        )
                    except Exception as exc:  # noqa: BLE001
                        error_msg = f"Tool '{tool_name}' failed: {exc}"
                        logger.error(error_msg, exc_info=True)
                        yield _sse(
                            {
                                "type": "tool-output-error",
                                "toolCallId": tool_call_id,
                                "error": error_msg,
                            }
                        )
                        result = error_msg

                    # Append the tool result so the LLM sees it in the next round.
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "name": tool_name,
                            "content": result,
                        }
                    )

            # If no server-side tools were executed there is nothing to feed
            # back to the LLM — break out of the loop.
            if not has_server_side_tool:
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
    ) -> str:
        """Dispatch a tool call and return its result as a string."""
        try:
            result = await dispatch_tool(name, arguments, context)
            # Update shared XML context if the tool modified the diagram.
            if result.xml is not None:
                context.current_xml = result.xml
            return result.content
        except Exception as exc:  # noqa: BLE001
            logger.error("Tool '%s' raised an exception: %s", name, exc, exc_info=True)
            return f"Tool '{name}' failed with an internal error: {exc}"

    def _handle_truncated_tool_call(self, name: str, raw_json: str) -> dict:
        """
        Attempt JSON repair on *raw_json* (potentially truncated tool-call
        arguments from a streaming LLM response).

        Returns the parsed dict on success, or a safe fallback on failure.
        """
        if not raw_json or not raw_json.strip():
            return get_fallback_tool_input(name)

        repaired = repair_tool_call_json(raw_json)
        if repaired is not None:
            return repaired

        logger.warning(
            "Could not repair JSON for tool '%s'; using fallback input. "
            "Raw args (first 200 chars): %.200s",
            name,
            raw_json,
        )
        return get_fallback_tool_input(name)
