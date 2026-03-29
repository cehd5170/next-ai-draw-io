"""
AgentsService — experimental create_agent-based chat endpoint.

This service leaves the existing ChatService untouched and provides a parallel
implementation behind ``/chat-agents``. OpenAI / OpenAI-compatible models use
LangChain ``create_agent`` orchestration with live SSE streaming. Other
providers fall back to the legacy ChatService so the experimental endpoint can
still be exercised without re-implementing the full multi-provider stack.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from contextlib import suppress
from dataclasses import dataclass
import json
import logging
from pathlib import Path
from typing import Any

from app.config import Settings
from app.models.chat import (
    AppendDiagramInput,
    DisplayDiagramInput,
    EditDiagramInput,
    GetShapeLibraryInput,
)
from app.providers.base import ModelConfig
from app.services.chat_service import (
    ChatService,
    _SSE_DONE,
    _SSE_HEARTBEAT,
    _nanoid,
    _sse,
)
from app.tools.layout_policy import apply_display_diagram_layout_defaults
from app.tools.registry import ToolContext, ToolResult, dispatch_tool

logger = logging.getLogger(__name__)
_SHAPE_LIBRARY_DIR = str(
    Path(__file__).resolve().parents[2] / "docs" / "shape-libraries"
)
_DIAGRAM_TOOLS = {"display_diagram", "edit_diagram", "append_diagram"}
_AGENT_TOOLS = _DIAGRAM_TOOLS | {"get_shape_library"}


@dataclass
class _PendingToolCall:
    tool_name: str
    tool_call_id: str
    stream_key: tuple[str, int] | None = None
    start_emitted: bool = False
    input_available_emitted: bool = False


def _import_langchain_dependencies() -> tuple[Any, Any, Any]:
    """Import LangChain dependencies lazily so the legacy path stays untouched."""
    try:
        from langchain.agents import create_agent
        from langchain.tools import tool
        from langchain_openai import ChatOpenAI
    except ImportError as exc:  # pragma: no cover - exercised via route error handling
        raise RuntimeError(
            "LangChain agents endpoint requires `langchain` and "
            "`langchain-openai` to be installed."
        ) from exc

    return create_agent, tool, ChatOpenAI


def _provider_model_id(model_id: str) -> str:
    return model_id.split("/", 1)[1] if "/" in model_id else model_id


def _coerce_message_text(content: Any) -> str:
    """Best-effort text extraction from LangChain / OpenAI-style message content."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text:
                    parts.append(text)
        return "\n".join(part for part in parts if part)
    return str(content)


def _simplify_messages(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Convert stored conversation history into plain role/content messages."""
    simplified: list[dict[str, str]] = []

    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "")
        if role not in {"user", "assistant", "tool"}:
            continue

        content = msg.get("content")
        text = _coerce_message_text(content)
        if not text.strip():
            continue

        simplified.append({"role": role, "content": text})

    return simplified


def _tool_output_payload(tool_name: str, result: ToolResult) -> Any:
    if tool_name not in _DIAGRAM_TOOLS:
        return result.content

    payload: dict[str, Any] = {
        "message": result.content,
        "success": result.success,
        "isTruncated": result.is_truncated,
    }
    if result.xml is not None:
        payload["xml"] = result.xml
    if result.layout is not None:
        payload["layout"] = result.layout
    return payload


def _extract_text_delta(token: Any) -> str:
    text = getattr(token, "text", None)
    if isinstance(text, str) and text:
        return text

    content_blocks = getattr(token, "content_blocks", None)
    if isinstance(content_blocks, list):
        parts: list[str] = []
        for block in content_blocks:
            if not isinstance(block, dict):
                continue
            if block.get("type") != "text":
                continue
            block_text = block.get("text")
            if isinstance(block_text, str) and block_text:
                parts.append(block_text)
        if parts:
            return "".join(parts)

    content = getattr(token, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            item.get("text", "")
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        )

    return ""


def _extract_tool_call_chunks(token: Any) -> list[dict[str, Any]]:
    raw_chunks = getattr(token, "tool_call_chunks", None) or []
    normalized: list[dict[str, Any]] = []

    for chunk in raw_chunks:
        if isinstance(chunk, dict):
            item = chunk
        else:
            item = {
                "name": getattr(chunk, "name", None),
                "args": getattr(chunk, "args", None),
                "id": getattr(chunk, "id", None),
                "index": getattr(chunk, "index", None),
            }
        normalized.append(item)

    return normalized


def _tool_call_args_delta(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _extract_final_response(result: Any) -> str:
    if hasattr(result, "value"):
        result = result.value

    if not isinstance(result, dict):
        return ""

    msgs = result.get("messages", [])
    for msg in reversed(msgs):
        content = getattr(msg, "content", None)
        if content is None and isinstance(msg, dict):
            content = msg.get("content")
        text = _coerce_message_text(content)
        if text.strip():
            return text
    return ""


def _create_named_agent(
    create_agent: Any,
    model: Any,
    tools: list[Any],
    *,
    system_prompt: str,
    name: str,
) -> Any:
    try:
        return create_agent(
            model,
            tools=tools,
            system_prompt=system_prompt,
            name=name,
        )
    except TypeError as exc:
        if "name" not in str(exc):
            raise
        return create_agent(
            model,
            tools=tools,
            system_prompt=system_prompt,
        )


class AgentsService:
    """Experimental LangChain create_agent-based orchestration."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._fallback_chat_service = ChatService(settings)

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        model_config: ModelConfig,
        system_prompt: str,
        xml_context: str,
        current_xml: str = "",
        shape_library_dir: str = _SHAPE_LIBRARY_DIR,
        preferred_shape_library: str | None = None,
        force_diagram_tool: bool = False,
    ):
        if model_config.provider != "openai":
            async for event in self._fallback_chat_service.stream_chat(
                messages=messages,
                model_config=model_config,
                system_prompt=system_prompt,
                xml_context=xml_context,
                current_xml=current_xml,
                shape_library_dir=shape_library_dir,
                preferred_shape_library=preferred_shape_library,
                force_diagram_tool=force_diagram_tool,
            ):
                yield event
            return

        create_agent, tool, ChatOpenAI = _import_langchain_dependencies()

        model_kwargs: dict[str, Any] = {
            "model": _provider_model_id(model_config.model_id),
            "max_tokens": self.settings.MAX_OUTPUT_TOKENS,
            "streaming": True,
        }
        if model_config.api_key:
            model_kwargs["api_key"] = model_config.api_key
        if model_config.base_url:
            model_kwargs["base_url"] = model_config.base_url
        if self.settings.TEMPERATURE is not None:
            model_kwargs["temperature"] = self.settings.TEMPERATURE

        model = ChatOpenAI(**model_kwargs)

        tool_context = ToolContext(
            current_xml=current_xml or "",
            shape_library_dir=shape_library_dir,
            settings=self.settings,
        )

        pending_by_stream_key: dict[tuple[str, int], _PendingToolCall] = {}
        pending_by_tool_name: dict[str, deque[_PendingToolCall]] = defaultdict(deque)

        event_queue: asyncio.Queue[Any] = asyncio.Queue()
        queue_done = object()
        supervisor_text_id: str | None = None
        supervisor_text_open = False

        async def _emit_event(event: dict[str, Any]) -> None:
            await event_queue.put(_sse(event))

        async def _emit_raw(raw: str) -> None:
            await event_queue.put(raw)

        async def _close_supervisor_text() -> None:
            nonlocal supervisor_text_open, supervisor_text_id
            if supervisor_text_open and supervisor_text_id:
                await _emit_event({"type": "text-end", "id": supervisor_text_id})
                supervisor_text_open = False
                supervisor_text_id = None

        async def _ensure_tool_start(state: _PendingToolCall) -> None:
            if state.tool_name not in _DIAGRAM_TOOLS or state.start_emitted:
                return
            await _close_supervisor_text()
            await _emit_event(
                {
                    "type": "tool-input-start",
                    "toolCallId": state.tool_call_id,
                    "toolName": state.tool_name,
                }
            )
            state.start_emitted = True

        async def _claim_pending_tool_call(tool_name: str) -> _PendingToolCall:
            queue = pending_by_tool_name.get(tool_name)
            state = queue.popleft() if queue else None

            if state is None:
                state = _PendingToolCall(
                    tool_name=tool_name,
                    tool_call_id=_nanoid("call_"),
                )

            if state.stream_key is not None:
                pending_by_stream_key.pop(state.stream_key, None)
                state.stream_key = None

            await _ensure_tool_start(state)
            return state

        async def _run_registry_tool(name: str, arguments: dict[str, Any]) -> ToolResult:
            arguments = apply_display_diagram_layout_defaults(name, arguments)
            state = await _claim_pending_tool_call(name)

            if not state.input_available_emitted:
                await _close_supervisor_text()
                await _emit_event(
                    {
                        "type": "tool-input-available",
                        "toolCallId": state.tool_call_id,
                        "toolName": name,
                        "input": arguments,
                    }
                )
                state.input_available_emitted = True

            result = await dispatch_tool(name, arguments, tool_context)
            if result.xml is not None:
                tool_context.current_xml = result.xml
            if result.layout is not None:
                tool_context.display_layout = result.layout

            await _close_supervisor_text()
            if result.success and not result.is_truncated:
                await _emit_event(
                    {
                        "type": "tool-output-available",
                        "toolCallId": state.tool_call_id,
                        "output": _tool_output_payload(name, result),
                    }
                )
            else:
                await _emit_event(
                    {
                        "type": "tool-output-error",
                        "toolCallId": state.tool_call_id,
                        "errorText": result.content,
                    }
                )

            return result

        @tool(args_schema=DisplayDiagramInput)
        async def display_diagram(
            xml: str,
            layout: str | None = None,
        ) -> str:
            """Create a new diagram from raw mxCell XML."""
            result = await _run_registry_tool(
                "display_diagram",
                {"xml": xml, "layout": layout},
            )
            return result.content

        @tool(args_schema=EditDiagramInput)
        async def edit_diagram(operations: list[dict[str, Any]]) -> str:
            """Apply targeted edit operations to the current diagram."""
            result = await _run_registry_tool(
                "edit_diagram",
                {"operations": operations},
            )
            return result.content

        @tool(args_schema=AppendDiagramInput)
        async def append_diagram(xml: str) -> str:
            """Continue a truncated diagram generation."""
            result = await _run_registry_tool("append_diagram", {"xml": xml})
            return result.content

        @tool(args_schema=GetShapeLibraryInput)
        async def get_shape_library(library: str) -> str:
            """Load documentation for a draw.io shape library."""
            result = await _run_registry_tool(
                "get_shape_library",
                {"library": library},
            )
            return result.content

        diagram_prompt = (
            "You are the diagram specialist. You own all diagram mutations.\n"
            "Use `display_diagram` to create a fresh diagram, `edit_diagram` to "
            "change an existing one, and `append_diagram` only when a previous "
            "diagram tool response explicitly says the XML was truncated.\n"
            "Never answer with explanation alone when an actual diagram change is "
            "required.\n"
        )
        if xml_context.strip():
            diagram_prompt += f"\n## Current Diagram XML\n{xml_context}"

        library_prompt = (
            "You are the shape-library specialist. Your only job is to consult "
            "`get_shape_library` and return the relevant guidance back to the supervisor."
        )

        diagram_agent = _create_named_agent(
            create_agent,
            model,
            tools=[display_diagram, edit_diagram, append_diagram],
            system_prompt=diagram_prompt,
            name="diagram_specialist",
        )
        library_agent = _create_named_agent(
            create_agent,
            model,
            tools=[get_shape_library],
            system_prompt=library_prompt,
            name="shape_library_specialist",
        )

        @tool
        async def delegate_diagram_work(request: str) -> str:
            """Handle all diagram creation and editing requests."""
            result = await diagram_agent.ainvoke(
                {"messages": [{"role": "user", "content": request}]}
            )
            return _extract_final_response(result)

        @tool
        async def consult_shape_library(request: str) -> str:
            """Consult shape-library documentation before creating icon-heavy diagrams."""
            result = await library_agent.ainvoke(
                {"messages": [{"role": "user", "content": request}]}
            )
            return _extract_final_response(result)

        supervisor_prompt = (
            f"{system_prompt}\n\n"
            "You are the supervisor of a diagram agent team.\n"
            "Use `consult_shape_library` when the request needs concrete icon/library "
            "guidance. Use `delegate_diagram_work` when the user needs an actual "
            "diagram created or edited.\n"
            "If a request involves both shape-library lookup and diagram generation, "
            "consult the library specialist first, then delegate diagram work.\n"
            "Return a concise final answer after the necessary work is complete."
        )
        if preferred_shape_library:
            supervisor_prompt += (
                f"\nThis request strongly suggests the `{preferred_shape_library}` "
                "shape library. Prefer consulting the shape-library specialist first."
            )
        if force_diagram_tool:
            supervisor_prompt += (
                "\nThe request requires a real diagram change. Do not stop at text-only "
                "guidance. You must delegate to the diagram specialist."
            )

        supervisor_agent = _create_named_agent(
            create_agent,
            model,
            tools=[delegate_diagram_work, consult_shape_library],
            system_prompt=supervisor_prompt,
            name="supervisor",
        )

        agent_messages = _simplify_messages(messages)
        message_id = _nanoid("msg_")
        yield _sse({"type": "start", "messageId": message_id})

        async def _handle_supervisor_token(token: Any) -> None:
            nonlocal supervisor_text_id, supervisor_text_open
            text_delta = _extract_text_delta(token)
            if not text_delta:
                return
            if not supervisor_text_open:
                supervisor_text_id = _nanoid("text_")
                await _emit_event({"type": "text-start", "id": supervisor_text_id})
                supervisor_text_open = True
            await _emit_event(
                {
                    "type": "text-delta",
                    "id": supervisor_text_id,
                    "delta": text_delta,
                }
            )

        async def _handle_tool_chunks(token: Any, agent_name: str) -> None:
            for chunk in _extract_tool_call_chunks(token):
                tool_name = chunk.get("name")
                if not isinstance(tool_name, str):
                    continue
                if tool_name not in _AGENT_TOOLS:
                    continue

                index = chunk.get("index")
                if not isinstance(index, int):
                    continue

                stream_key = (agent_name, index)
                state = pending_by_stream_key.get(stream_key)
                if state is None:
                    tool_call_id = chunk.get("id")
                    if not isinstance(tool_call_id, str) or not tool_call_id:
                        tool_call_id = _nanoid("call_")
                    state = _PendingToolCall(
                        tool_name=tool_name,
                        tool_call_id=tool_call_id,
                        stream_key=stream_key,
                    )
                    pending_by_stream_key[stream_key] = state
                    pending_by_tool_name[tool_name].append(state)

                await _ensure_tool_start(state)

                args_delta = _tool_call_args_delta(chunk.get("args"))
                if args_delta and tool_name in _DIAGRAM_TOOLS:
                    await _emit_event(
                        {
                            "type": "tool-input-delta",
                            "toolCallId": state.tool_call_id,
                            "inputTextDelta": args_delta,
                        }
                    )

        async def _stream_agent() -> None:
            try:
                stream_kwargs = {
                    "config": {
                        "recursion_limit": max(
                            self.settings.MAX_TOOL_STEPS * 4,
                            8,
                        )
                    },
                    "stream_mode": "messages",
                    "subgraphs": True,
                    "version": "v2",
                }

                if hasattr(supervisor_agent, "astream"):
                    async for chunk in supervisor_agent.astream(
                        {"messages": agent_messages},
                        **stream_kwargs,
                    ):
                        if not isinstance(chunk, dict) or chunk.get("type") != "messages":
                            continue
                        data = chunk.get("data")
                        if not isinstance(data, (list, tuple)) or len(data) != 2:
                            continue
                        token, metadata = data
                        metadata = metadata if isinstance(metadata, dict) else {}
                        agent_name = (
                            metadata.get("lc_agent_name")
                            or metadata.get("langgraph_node")
                            or ""
                        )
                        await _handle_tool_chunks(token, str(agent_name))
                        if agent_name == "supervisor":
                            await _handle_supervisor_token(token)
                else:
                    invocation = await supervisor_agent.ainvoke(
                        {"messages": agent_messages},
                        config={
                            "recursion_limit": max(
                                self.settings.MAX_TOOL_STEPS * 4,
                                8,
                            )
                        },
                    )
                    final_text = _extract_final_response(invocation)
                    if final_text.strip():
                        await _handle_supervisor_token(
                            type("Token", (), {"text": final_text})()
                        )

                await _close_supervisor_text()
                await _emit_event({"type": "finish"})
                await _emit_raw(_SSE_DONE)
            except Exception as exc:
                logger.error(
                    "Agents endpoint streaming failed: %s",
                    exc,
                    exc_info=True,
                )
                await _close_supervisor_text()
                for event in ChatService._error_events(exc):
                    await _emit_raw(event)
            finally:
                await event_queue.put(queue_done)

        task = asyncio.create_task(_stream_agent())

        try:
            while True:
                try:
                    item = await asyncio.wait_for(event_queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    if task.done():
                        break
                    yield _SSE_HEARTBEAT
                    continue

                if item is queue_done:
                    break
                yield item
        finally:
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
