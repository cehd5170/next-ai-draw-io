"""
DeepAgentsService — diagram agent built on LangChain deepagents + SKILL.md.

Uses ``create_deep_agent`` from the deepagents library. Skills are loaded from
``backend/app/skills/`` as SKILL.md files (progressive disclosure).

Backend strategy (production-safe):
- Main backend: StateBackend — file tools (ls/read_file/write_file/…) operate on
  ephemeral in-memory state, never touching the server filesystem. execute always
  returns an error (requires LocalShellBackend which is unsuitable for production).
- Skills backend: FilesystemBackend (virtual_mode=True) — read-only access to the
  app/skills/ directory for loading SKILL.md files.
- CompositeBackend routes /skills/ → FilesystemBackend, everything else → StateBackend.

Falls back to AgentsService for providers not supported by init_chat_model.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from contextlib import suppress
from dataclasses import dataclass
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
from app.services.agents_service import (
    AgentsService,
    _PendingToolCall,
    _DIAGRAM_TOOLS,
    _AGENT_TOOLS,
    _coerce_message_text,
    _extract_text_delta,
    _extract_tool_call_chunks,
    _extract_final_response,
    _simplify_messages,
    _tool_call_args_delta,
    _tool_output_payload,
)
from app.tools.layout_policy import apply_display_diagram_layout_defaults
from app.tools.registry import ToolContext, ToolResult, dispatch_tool

logger = logging.getLogger(__name__)

_SKILLS_DIR = Path(__file__).resolve().parents[1] / "skills"
_SHAPE_LIBRARY_DIR = str(Path(__file__).resolve().parents[2] / "docs" / "shape-libraries")

# Providers mappable to langchain init_chat_model provider strings
_PROVIDER_MAP = {
    "openai": "openai",
    "anthropic": "anthropic",
    "google": "google_genai",
    "azure": "azure_openai",
}


def _import_deepagents():
    try:
        from deepagents import create_deep_agent
        from deepagents.backends import CompositeBackend, StateBackend
        from deepagents.backends.filesystem import FilesystemBackend
        from langchain.tools import tool
        from langchain.chat_models import init_chat_model
    except ImportError as exc:
        raise RuntimeError(
            "DeepAgents endpoint requires `deepagents` and `langchain` to be installed."
        ) from exc
    return create_deep_agent, CompositeBackend, StateBackend, FilesystemBackend, tool, init_chat_model


def _langchain_provider(provider: str) -> str | None:
    return _PROVIDER_MAP.get(provider)


class DeepAgentsService:
    """Diagram agent orchestrated via deepagents + SKILL.md skills."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._fallback = AgentsService(settings)

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
        lc_provider = _langchain_provider(model_config.provider)
        if lc_provider is None:
            logger.info(
                "DeepAgentsService: provider %r not supported, falling back to AgentsService",
                model_config.provider,
            )
            async for event in self._fallback.stream_chat(
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

        (
            create_deep_agent,
            CompositeBackend,
            StateBackend,
            FilesystemBackend,
            tool,
            init_chat_model,
        ) = _import_deepagents()

        raw_model_id = model_config.model_id.split("/", 1)[-1]
        model_str = f"{lc_provider}:{raw_model_id}"

        model_kwargs: dict[str, Any] = {
            "max_tokens": self.settings.MAX_OUTPUT_TOKENS,
        }
        if model_config.api_key:
            model_kwargs["api_key"] = model_config.api_key
        if model_config.base_url:
            model_kwargs["base_url"] = model_config.base_url
        if self.settings.TEMPERATURE is not None:
            model_kwargs["temperature"] = self.settings.TEMPERATURE

        llm = init_chat_model(model_str, **model_kwargs)

        tool_context = ToolContext(
            current_xml=current_xml or "",
            shape_library_dir=shape_library_dir,
            settings=self.settings,
        )

        pending_by_stream_key: dict[tuple[str, int], _PendingToolCall] = {}
        pending_by_tool_name: dict[str, deque[_PendingToolCall]] = defaultdict(deque)
        event_queue: asyncio.Queue[Any] = asyncio.Queue()
        queue_done = object()
        text_id: str | None = None
        text_open = False

        async def _emit(event: dict[str, Any]) -> None:
            await event_queue.put(_sse(event))

        async def _emit_raw(raw: str) -> None:
            await event_queue.put(raw)

        async def _close_text() -> None:
            nonlocal text_open, text_id
            if text_open and text_id:
                await _emit({"type": "text-end", "id": text_id})
                text_open = False
                text_id = None

        async def _ensure_tool_start(state: _PendingToolCall) -> None:
            if not state.start_emitted:
                await _close_text()
                await _emit({"type": "tool-input-start", "toolCallId": state.tool_call_id, "toolName": state.tool_name})
                state.start_emitted = True

        async def _claim_pending(name: str) -> _PendingToolCall:
            q = pending_by_tool_name[name]
            if q:
                state = q.popleft()
            else:
                state = _PendingToolCall(tool_name=name, tool_call_id=_nanoid("call_"))
            await _ensure_tool_start(state)
            return state

        async def _run_tool(name: str, arguments: dict[str, Any]) -> ToolResult:
            arguments = apply_display_diagram_layout_defaults(name, arguments)
            state = await _claim_pending(name)
            if not state.input_available_emitted:
                await _close_text()
                await _emit({"type": "tool-input-available", "toolCallId": state.tool_call_id, "toolName": name, "input": arguments})
                state.input_available_emitted = True
            result = await dispatch_tool(name, arguments, tool_context)
            if result.xml is not None:
                tool_context.current_xml = result.xml
            await _close_text()
            if result.success and not result.is_truncated:
                await _emit({"type": "tool-output-available", "toolCallId": state.tool_call_id, "output": _tool_output_payload(name, result)})
            else:
                await _emit({"type": "tool-output-error", "toolCallId": state.tool_call_id, "errorText": result.content})
            return result

        @tool(args_schema=DisplayDiagramInput)
        async def display_diagram(xml: str, layout: str | None = None) -> str:
            """Create a new diagram from raw mxCell XML."""
            return (await _run_tool("display_diagram", {"xml": xml, "layout": layout})).content

        @tool(args_schema=EditDiagramInput)
        async def edit_diagram(operations: list[dict[str, Any]]) -> str:
            """Apply targeted edit operations to the current diagram."""
            return (await _run_tool("edit_diagram", {"operations": operations})).content

        @tool(args_schema=AppendDiagramInput)
        async def append_diagram(xml: str) -> str:
            """Continue a truncated diagram generation."""
            return (await _run_tool("append_diagram", {"xml": xml})).content

        @tool(args_schema=GetShapeLibraryInput)
        async def get_shape_library(library: str) -> str:
            """Load documentation for a draw.io shape library."""
            return (await _run_tool("get_shape_library", {"library": library})).content

        base_prompt = system_prompt
        if xml_context.strip():
            base_prompt += f"\n\n## Current Diagram XML\n{xml_context}"
        if preferred_shape_library:
            base_prompt += f"\n\nThis request strongly suggests the `{preferred_shape_library}` shape library. Consult it first."
        if force_diagram_tool:
            base_prompt += "\n\nThe request requires a real diagram change — you must call a diagram tool."

        # Skills are on real disk; everything else stays in ephemeral in-memory state.
        # CompositeBackend routes /skills/ → FilesystemBackend (read SKILL.md),
        # all other paths → StateBackend (safe for production web apps).
        skills_fs = FilesystemBackend(root_dir=str(_SKILLS_DIR), virtual_mode=True)
        backend = CompositeBackend(
            default=StateBackend(),
            routes={"/skills/": skills_fs},
        )
        skill_sources = [
            f"/skills/{d.name}/"
            for d in sorted(_SKILLS_DIR.iterdir())
            if d.is_dir() and (d / "SKILL.md").exists()
        ]

        agent = create_deep_agent(
            model=llm,
            tools=[display_diagram, edit_diagram, append_diagram, get_shape_library],
            system_prompt=base_prompt,
            skills=skill_sources,
            backend=backend,
        )

        agent_messages = _simplify_messages(messages)
        message_id = _nanoid("msg_")
        yield _sse({"type": "start", "messageId": message_id})

        async def _handle_text_token(token: Any) -> None:
            nonlocal text_open, text_id
            delta = _extract_text_delta(token)
            if not delta:
                return
            if not text_open:
                text_id = _nanoid("text_")
                await _emit({"type": "text-start", "id": text_id})
                text_open = True
            await _emit({"type": "text-delta", "id": text_id, "delta": delta})

        async def _handle_tool_chunks(token: Any, agent_name: str) -> None:
            for chunk in _extract_tool_call_chunks(token):
                tool_name = chunk.get("name")
                if not isinstance(tool_name, str) or tool_name not in _AGENT_TOOLS:
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
                    state = _PendingToolCall(tool_name=tool_name, tool_call_id=tool_call_id, stream_key=stream_key)
                    pending_by_stream_key[stream_key] = state
                    pending_by_tool_name[tool_name].append(state)
                await _ensure_tool_start(state)
                args_delta = _tool_call_args_delta(chunk.get("args"))
                if args_delta and tool_name in _DIAGRAM_TOOLS:
                    await _emit({"type": "tool-input-delta", "toolCallId": state.tool_call_id, "inputTextDelta": args_delta})

        async def _stream_agent() -> None:
            try:
                async for chunk in agent.astream(
                    {"messages": agent_messages},
                    config={"recursion_limit": max(self.settings.MAX_TOOL_STEPS * 4, 8)},
                    stream_mode="messages",
                    subgraphs=True,
                    version="v2",
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
                    await _handle_text_token(token)

                await _close_text()
                await _emit({"type": "finish"})
                await _emit_raw(_SSE_DONE)
            except Exception as exc:
                logger.error("DeepAgentsService streaming failed: %s", exc, exc_info=True)
                await _close_text()
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
