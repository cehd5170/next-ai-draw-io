import asyncio
import json
from types import SimpleNamespace

import pytest

from app.providers.base import ModelConfig
from app.services.chat_service import ChatService


class _FakeCompletions:
    def __init__(self, calls: list[dict], stream_factory):
        self.calls = calls
        self._stream_factory = stream_factory

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._stream_factory()


class _FakeChat:
    def __init__(self, calls: list[dict], stream_factory):
        self.completions = _FakeCompletions(calls, stream_factory)


class _FakeAsyncOpenAI:
    instances: list["_FakeAsyncOpenAI"] = []
    stream_factory = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls: list[dict] = []
        self.chat = _FakeChat(self.calls, self.__class__.stream_factory)
        _FakeAsyncOpenAI.instances.append(self)


class TestChatServiceHeartbeats:
    @pytest.mark.asyncio
    async def test_await_with_sse_heartbeats_emits_heartbeat_before_result(
        self,
        settings_override,
        monkeypatch,
    ):
        monkeypatch.setattr(
            "app.services.chat_service._HEARTBEAT_INTERVAL_SECONDS",
            0.01,
        )
        service = ChatService(settings_override)

        async def _slow_result():
            await asyncio.sleep(0.03)
            return "ready"

        events: list[tuple[str, object]] = []
        async for event_type, payload in service._await_with_sse_heartbeats(
            _slow_result(),
        ):
            events.append((event_type, payload))

        assert any(event_type == "heartbeat" for event_type, _ in events)
        assert events[-1] == ("result", "ready")

    @pytest.mark.asyncio
    async def test_iterate_with_sse_heartbeats_emits_heartbeat_between_chunks(
        self,
        settings_override,
        monkeypatch,
    ):
        monkeypatch.setattr(
            "app.services.chat_service._HEARTBEAT_INTERVAL_SECONDS",
            0.01,
        )
        ChatService(settings_override)

        async def _slow_stream():
            await asyncio.sleep(0.03)
            yield "chunk-1"

        events: list[tuple[str, object]] = []
        async for event_type, payload in ChatService._iterate_with_sse_heartbeats(
            _slow_stream(),
        ):
            events.append((event_type, payload))

        assert any(event_type == "heartbeat" for event_type, _ in events)
        assert ("chunk", "chunk-1") in events


class TestChatServiceToolStreaming:
    @pytest.mark.asyncio
    async def test_stream_chat_emits_incremental_tool_input_deltas(
        self,
        settings_override,
        monkeypatch,
    ):
        service = ChatService(settings_override)

        def _chunk(*, tool_name=None, arguments=None, finish_reason=None):
            tool_calls = None
            if tool_name is not None or arguments is not None:
                tool_calls = [
                    SimpleNamespace(
                        index=0,
                        id="provider_call_1",
                        function=SimpleNamespace(
                            name=tool_name,
                            arguments=arguments,
                        ),
                    )
                ]

            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(
                            content=None,
                            reasoning_content=None,
                            tool_calls=tool_calls,
                        ),
                        finish_reason=finish_reason,
                    )
                ],
                usage=None,
            )

        async def _fake_stream():
            yield _chunk(
                tool_name="display_diagram",
                arguments='{"xml":"<mxCell id=\\"2\\" ',
            )
            yield _chunk(
                tool_name="display_diagram",
                arguments='value=\\"A\\"/>"}',
                finish_reason="tool_calls",
            )

        _FakeAsyncOpenAI.instances.clear()
        _FakeAsyncOpenAI.stream_factory = _fake_stream
        monkeypatch.setattr("app.services.chat_service.AsyncOpenAI", _FakeAsyncOpenAI)

        events = [
            event
            async for event in service.stream_chat(
                messages=[{"role": "user", "content": "draw a diagram"}],
                model_config=ModelConfig(
                    provider="openai",
                    model_id="openai/gpt-4o",
                    api_key="test-key",
                    base_url=None,
                ),
                system_prompt="You are a diagram assistant.",
                xml_context="",
            )
        ]

        parsed_events = []
        for event in events:
            if not event.startswith("data: {"):
                continue
            parsed_events.append(json.loads(event[6:]))

        event_types = [event["type"] for event in parsed_events]
        assert "tool-input-start" in event_types
        assert event_types.count("tool-input-delta") == 2
        assert "tool-input-available" in event_types

        start_index = event_types.index("tool-input-start")
        available_index = event_types.index("tool-input-available")
        assert start_index < available_index

        delta_events = [
            event for event in parsed_events if event["type"] == "tool-input-delta"
        ]
        assert delta_events[0]["inputTextDelta"] == '{"xml":"<mxCell id=\\"2\\" '
        assert delta_events[1]["inputTextDelta"] == 'value=\\"A\\"/>"}'

        available_event = parsed_events[available_index]
        assert available_event["toolName"] == "display_diagram"
        assert available_event["input"]["xml"] == '<mxCell id="2" value="A"/>'
        assert _FakeAsyncOpenAI.instances[0].calls[0]["model"] == "gpt-4o"

    @pytest.mark.asyncio
    async def test_stream_chat_coalesces_many_small_tool_input_deltas(
        self,
        settings_override,
        monkeypatch,
    ):
        service = ChatService(settings_override)

        def _chunk(arguments=None, finish_reason=None):
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(
                            content=None,
                            reasoning_content=None,
                            tool_calls=[
                                SimpleNamespace(
                                    index=0,
                                    id="provider_call_2",
                                    function=SimpleNamespace(
                                        name="display_diagram",
                                        arguments=arguments,
                                    ),
                                )
                            ],
                        ),
                        finish_reason=finish_reason,
                    )
                ],
                usage=None,
            )

        async def _fake_stream():
            yield _chunk(arguments='{"xml":"')
            yield _chunk(arguments="<mxCell ")
            yield _chunk(arguments='id=\\"2\\" ')
            yield _chunk(arguments='value=\\"A\\"/>"}', finish_reason="tool_calls")

        _FakeAsyncOpenAI.instances.clear()
        _FakeAsyncOpenAI.stream_factory = _fake_stream
        monkeypatch.setattr("app.services.chat_service.AsyncOpenAI", _FakeAsyncOpenAI)

        events = [
            event
            async for event in service.stream_chat(
                messages=[{"role": "user", "content": "draw a diagram"}],
                model_config=ModelConfig(
                    provider="openai",
                    model_id="openai/gpt-4o",
                    api_key="test-key",
                    base_url=None,
                ),
                system_prompt="You are a diagram assistant.",
                xml_context="",
            )
        ]

        parsed_events = [
            json.loads(event[6:])
            for event in events
            if event.startswith("data: {")
        ]
        delta_events = [
            event for event in parsed_events if event["type"] == "tool-input-delta"
        ]

        # First delta starts streaming quickly; later tiny fragments are merged.
        assert len(delta_events) == 2
        assert delta_events[0]["inputTextDelta"] == '{"xml":"'
        assert delta_events[1]["inputTextDelta"] == '<mxCell id=\\"2\\" value=\\"A\\"/>"}'

    @pytest.mark.asyncio
    async def test_stream_chat_uses_max_completion_tokens_for_gpt5_models(
        self,
        settings_override,
        monkeypatch,
    ):
        service = ChatService(settings_override)

        async def _fake_stream():
            yield SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(
                            content="done",
                            reasoning_content=None,
                            tool_calls=None,
                        ),
                        finish_reason="stop",
                    )
                ],
                usage=None,
            )

        _FakeAsyncOpenAI.instances.clear()
        _FakeAsyncOpenAI.stream_factory = _fake_stream
        monkeypatch.setattr("app.services.chat_service.AsyncOpenAI", _FakeAsyncOpenAI)

        _ = [
            event
            async for event in service.stream_chat(
                messages=[{"role": "user", "content": "say hi"}],
                model_config=ModelConfig(
                    provider="openai",
                    model_id="openai/gpt-5.4-nano",
                    api_key="test-key",
                    base_url=None,
                ),
                system_prompt="You are a diagram assistant.",
                xml_context="",
            )
        ]

        call_kwargs = _FakeAsyncOpenAI.instances[0].calls[0]
        assert call_kwargs["model"] == "gpt-5.4-nano"
        assert call_kwargs["max_completion_tokens"] == settings_override.MAX_OUTPUT_TOKENS
        assert "max_tokens" not in call_kwargs

    @pytest.mark.asyncio
    async def test_stream_chat_omits_reasoning_effort_when_tools_are_enabled(
        self,
        settings_override,
        monkeypatch,
    ):
        service = ChatService(settings_override)

        async def _fake_stream():
            yield SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(
                            content="done",
                            reasoning_content=None,
                            tool_calls=None,
                        ),
                        finish_reason="stop",
                    )
                ],
                usage=None,
            )

        _FakeAsyncOpenAI.instances.clear()
        _FakeAsyncOpenAI.stream_factory = _fake_stream
        monkeypatch.setattr("app.services.chat_service.AsyncOpenAI", _FakeAsyncOpenAI)

        _ = [
            event
            async for event in service.stream_chat(
                messages=[{"role": "user", "content": "say hi"}],
                model_config=ModelConfig(
                    provider="openai",
                    model_id="openai/gpt-5.4",
                    api_key="test-key",
                    base_url=None,
                    extra_params={"reasoning_effort": "medium"},
                ),
                system_prompt="You are a diagram assistant.",
                xml_context="",
            )
        ]

        call_kwargs = _FakeAsyncOpenAI.instances[0].calls[0]
        assert "reasoning_effort" not in call_kwargs
