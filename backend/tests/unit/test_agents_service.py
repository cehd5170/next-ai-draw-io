import json
from types import SimpleNamespace

import pytest

from app.providers.base import ModelConfig
from app.services.agents_service import AgentsService


def _fake_tool(*decorator_args, **_decorator_kwargs):
    if decorator_args and callable(decorator_args[0]):
        fn = decorator_args[0]
        fn.name = fn.__name__
        return fn

    def _wrap(fn):
        fn.name = fn.__name__
        return fn

    return _wrap


class _FakeChatOpenAI:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _FakeAgent:
    def __init__(self, tools):
        self.tools = {
            getattr(tool, "name", getattr(tool, "__name__", "")): tool
            for tool in tools
        }

    async def ainvoke(self, payload, config=None):
        _ = payload
        _ = config

        if "delegate_diagram_work" in self.tools:
            await self.tools["delegate_diagram_work"]("draw a simple box diagram")
            return {"messages": [SimpleNamespace(content="Supervisor complete.")]}

        if "display_diagram" in self.tools:
            await self.tools["display_diagram"](
                '<mxCell id="2" value="A" vertex="1" parent="1"/>'
            )
            return {"messages": [SimpleNamespace(content="Diagram specialist complete.")]}

        if "get_shape_library" in self.tools:
            await self.tools["get_shape_library"]("flowchart")
            return {"messages": [SimpleNamespace(content="Library specialist complete.")]}

        return {"messages": [SimpleNamespace(content="Done.")]}


class _FakeStreamingAgent(_FakeAgent):
    async def astream(self, payload, **kwargs):
        _ = payload
        _ = kwargs

        if "delegate_diagram_work" in self.tools:
            await self.tools["delegate_diagram_work"]("draw a simple box diagram")
            yield {
                "type": "messages",
                "data": (
                    SimpleNamespace(text="Supervisor streamed.", tool_call_chunks=[]),
                    {"lc_agent_name": "supervisor"},
                ),
            }


def _fake_create_agent(_model, tools, system_prompt=None):
    _ = system_prompt
    return _FakeAgent(tools)


def _fake_streaming_create_agent(_model, tools, system_prompt=None):
    _ = system_prompt
    return _FakeStreamingAgent(tools)


class TestAgentsService:
    @pytest.mark.asyncio
    async def test_stream_chat_emits_structured_diagram_tool_output(
        self,
        settings_override,
        monkeypatch,
    ):
        monkeypatch.setattr(
            "app.services.agents_service._import_langchain_dependencies",
            lambda: (_fake_create_agent, _fake_tool, _FakeChatOpenAI),
        )

        service = AgentsService(settings_override)
        events = [
            event
            async for event in service.stream_chat(
                messages=[{"role": "user", "content": "draw a box"}],
                model_config=ModelConfig(
                    provider="openai",
                    model_id="openai/gpt-4o",
                    api_key="test-key",
                    base_url=None,
                ),
                system_prompt="You are a diagram assistant.",
                xml_context="",
                current_xml="",
            )
        ]

        parsed = [json.loads(e[6:]) for e in events if e.startswith("data: {")]
        event_types = [event["type"] for event in parsed]

        assert event_types[0] == "start"
        assert "tool-input-start" in event_types
        assert "tool-input-available" in event_types
        assert "tool-output-available" in event_types
        assert "text-delta" in event_types
        assert event_types[-1] == "finish"

        output_event = next(
            event for event in parsed if event["type"] == "tool-output-available"
        )
        input_event = next(
            event for event in parsed if event["type"] == "tool-input-available"
        )
        assert input_event["input"]["layout"] == "mxHierarchicalLayout"
        assert "Diagram created successfully." in output_event["output"]["message"]
        assert "<mxGraphModel>" in output_event["output"]["xml"]

    @pytest.mark.asyncio
    async def test_stream_chat_uses_langchain_astream_when_available(
        self,
        settings_override,
        monkeypatch,
    ):
        monkeypatch.setattr(
            "app.services.agents_service._import_langchain_dependencies",
            lambda: (_fake_streaming_create_agent, _fake_tool, _FakeChatOpenAI),
        )

        service = AgentsService(settings_override)
        events = [
            event
            async for event in service.stream_chat(
                messages=[{"role": "user", "content": "draw a box"}],
                model_config=ModelConfig(
                    provider="openai",
                    model_id="openai/gpt-4o",
                    api_key="test-key",
                    base_url=None,
                ),
                system_prompt="You are a diagram assistant.",
                xml_context="",
                current_xml="",
            )
        ]

        parsed = [json.loads(e[6:]) for e in events if e.startswith("data: {")]
        text_delta = next(event for event in parsed if event["type"] == "text-delta")

        assert text_delta["delta"] == "Supervisor streamed."
        assert any(
            event["type"] == "tool-output-available" for event in parsed
        )

    @pytest.mark.asyncio
    async def test_stream_chat_falls_back_to_legacy_chat_service_for_non_openai(
        self,
        settings_override,
        monkeypatch,
    ):
        service = AgentsService(settings_override)
        captured: dict[str, object] = {}

        async def _fake_stream_chat(**kwargs):
            captured.update(kwargs)
            yield "data: fallback\n\n"

        monkeypatch.setattr(
            service._fallback_chat_service,
            "stream_chat",
            _fake_stream_chat,
        )

        events = [
            event
            async for event in service.stream_chat(
                messages=[{"role": "user", "content": "draw a box"}],
                model_config=ModelConfig(
                    provider="anthropic",
                    model_id="anthropic/claude-3-7-sonnet",
                    api_key="test-key",
                    base_url=None,
                ),
                system_prompt="You are a diagram assistant.",
                xml_context="",
                current_xml="",
            )
        ]

        assert events == ["data: fallback\n\n"]
        assert isinstance(captured["model_config"], ModelConfig)
        assert captured["model_config"].provider == "anthropic"
