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


class _FakeResponses:
    """Fake for client.responses.create (OpenAI Responses API)."""

    def __init__(self, calls: list[dict], stream_factory):
        self.calls = calls
        self._stream_factory = stream_factory

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._stream_factory()


class _FakeAsyncOpenAI:
    instances: list["_FakeAsyncOpenAI"] = []
    stream_factory = None
    responses_stream_factory = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls: list[dict] = []
        self.responses_calls: list[dict] = []
        self.chat = _FakeChat(self.calls, self.__class__.stream_factory)
        self.responses = _FakeResponses(
            self.responses_calls,
            self.__class__.responses_stream_factory or self.__class__.stream_factory,
        )
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
        assert available_event["input"]["layout"] == "mxHierarchicalLayout"
        output_event = next(
            event
            for event in parsed_events
            if event["type"] == "tool-output-available"
        )
        assert output_event["toolCallId"] == available_event["toolCallId"]
        assert "Diagram created successfully." in output_event["output"]["message"]
        assert "<mxGraphModel>" in output_event["output"]["xml"]
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
    async def test_stream_chat_uses_responses_api_for_gpt5_models(
        self,
        settings_override,
        monkeypatch,
    ):
        """GPT-5 family models use Responses API with max_output_tokens."""
        service = ChatService(settings_override)

        async def _fake_responses_stream():
            yield SimpleNamespace(type="response.output_text.delta", delta="done", item_id="item_1", output_index=0, content_index=0, sequence_number=1)
            yield SimpleNamespace(
                type="response.completed",
                response=SimpleNamespace(
                    usage=SimpleNamespace(input_tokens=10, output_tokens=5),
                    output=[],
                ),
            )

        _FakeAsyncOpenAI.instances.clear()
        _FakeAsyncOpenAI.responses_stream_factory = _fake_responses_stream
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

        call_kwargs = _FakeAsyncOpenAI.instances[0].responses_calls[0]
        assert call_kwargs["model"] == "gpt-5.4-nano"
        assert call_kwargs["max_output_tokens"] == settings_override.MAX_OUTPUT_TOKENS
        assert call_kwargs["stream"] is True

    @pytest.mark.asyncio
    async def test_stream_chat_passes_reasoning_effort_via_responses_api(
        self,
        settings_override,
        monkeypatch,
    ):
        """Reasoning effort is passed via the Responses API reasoning param."""
        service = ChatService(settings_override)

        async def _fake_responses_stream():
            yield SimpleNamespace(
                type="response.reasoning_summary_text.delta",
                delta="thinking...",
                item_id="item_1",
                output_index=0,
                summary_index=0,
                sequence_number=1,
            )
            yield SimpleNamespace(type="response.output_text.delta", delta="done", item_id="item_2", output_index=1, content_index=0, sequence_number=2)
            yield SimpleNamespace(
                type="response.completed",
                response=SimpleNamespace(
                    usage=SimpleNamespace(input_tokens=10, output_tokens=5),
                    output=[],
                ),
            )

        _FakeAsyncOpenAI.instances.clear()
        _FakeAsyncOpenAI.responses_stream_factory = _fake_responses_stream
        monkeypatch.setattr("app.services.chat_service.AsyncOpenAI", _FakeAsyncOpenAI)

        events = [
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

        call_kwargs = _FakeAsyncOpenAI.instances[0].responses_calls[0]
        assert call_kwargs["reasoning"] == {"effort": "medium", "summary": "auto"}

        # Verify reasoning events are emitted
        parsed = [json.loads(e[6:]) for e in events if e.startswith("data: {")]
        event_types = [e["type"] for e in parsed]
        assert "reasoning-start" in event_types
        assert "reasoning-delta" in event_types
        assert "reasoning-end" in event_types

    @pytest.mark.asyncio
    async def test_stream_chat_marks_complete_tool_input_as_truncated_on_length_finish(
        self,
        settings_override,
        monkeypatch,
    ):
        """Truncation detection works with Chat Completions API (non-reasoning models)."""
        service = ChatService(settings_override)

        async def _fake_stream():
            yield SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(
                            content=None,
                            reasoning_content=None,
                            tool_calls=[
                                SimpleNamespace(
                                    index=0,
                                    id="provider_call_3",
                                    function=SimpleNamespace(
                                        name="display_diagram",
                                        arguments='{"xml":"<mxCell id=\\"2\\" value=\\"A\\"/>"}',
                                    ),
                                )
                            ],
                        ),
                        finish_reason="length",
                    )
                ],
                usage=None,
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

        parsed_events = [
            json.loads(event[6:])
            for event in events
            if event.startswith("data: {")
        ]
        available_event = next(
            event
            for event in parsed_events
            if event["type"] == "tool-input-available"
        )
        assert available_event["input"]["xml"] == '<mxCell id="2" value="A"/>'
        assert available_event["input"]["truncated"] is True


class TestApiModeRouting:
    """Tests for OPENAI_API_MODE config routing."""

    @pytest.mark.asyncio
    async def test_api_mode_completions_forces_chat_completions_for_reasoning_model(
        self, settings_override, monkeypatch
    ):
        """OPENAI_API_MODE=completions forces Chat Completions even for reasoning models."""
        settings_override.OPENAI_API_MODE = "completions"
        service = ChatService(settings_override)

        async def _fake_stream():
            yield SimpleNamespace(
                choices=[SimpleNamespace(
                    delta=SimpleNamespace(content="hi", reasoning_content=None, tool_calls=None),
                    finish_reason="stop",
                )],
                usage=SimpleNamespace(prompt_tokens=5, completion_tokens=2, total_tokens=7),
            )

        _FakeAsyncOpenAI.instances.clear()
        _FakeAsyncOpenAI.stream_factory = _fake_stream
        _FakeAsyncOpenAI.responses_stream_factory = None
        monkeypatch.setattr("app.services.chat_service.AsyncOpenAI", _FakeAsyncOpenAI)

        _ = [
            event async for event in service.stream_chat(
                messages=[{"role": "user", "content": "hi"}],
                model_config=ModelConfig(
                    provider="openai", model_id="openai/o3-mini",
                    api_key="test-key", base_url=None,
                ),
                system_prompt="test", xml_context="",
            )
        ]

        # Should use Chat Completions (calls), not Responses API (responses_calls)
        inst = _FakeAsyncOpenAI.instances[0]
        assert len(inst.calls) == 1
        assert len(inst.responses_calls) == 0
        assert inst.calls[0]["model"] == "o3-mini"

    @pytest.mark.asyncio
    async def test_api_mode_responses_forces_responses_api_for_non_reasoning_model(
        self, settings_override, monkeypatch
    ):
        """OPENAI_API_MODE=responses forces Responses API even for non-reasoning models."""
        settings_override.OPENAI_API_MODE = "responses"
        service = ChatService(settings_override)

        async def _fake_responses_stream():
            yield SimpleNamespace(
                type="response.output_text.delta", delta="hi",
                item_id="item_1", output_index=0, content_index=0, sequence_number=1,
            )
            yield SimpleNamespace(
                type="response.completed",
                response=SimpleNamespace(
                    usage=SimpleNamespace(input_tokens=5, output_tokens=2),
                    output=[],
                ),
            )

        _FakeAsyncOpenAI.instances.clear()
        _FakeAsyncOpenAI.responses_stream_factory = _fake_responses_stream
        monkeypatch.setattr("app.services.chat_service.AsyncOpenAI", _FakeAsyncOpenAI)

        _ = [
            event async for event in service.stream_chat(
                messages=[{"role": "user", "content": "hi"}],
                model_config=ModelConfig(
                    provider="openai", model_id="openai/gpt-4o",
                    api_key="test-key", base_url=None,
                ),
                system_prompt="test", xml_context="",
            )
        ]

        # Should use Responses API, not Chat Completions
        inst = _FakeAsyncOpenAI.instances[0]
        assert len(inst.responses_calls) == 1
        assert len(inst.calls) == 0
        assert inst.responses_calls[0]["model"] == "gpt-4o"

    @pytest.mark.asyncio
    async def test_api_mode_auto_uses_completions_for_non_reasoning_model(
        self, settings_override, monkeypatch
    ):
        """OPENAI_API_MODE=auto (default) uses Chat Completions for non-reasoning models."""
        settings_override.OPENAI_API_MODE = "auto"
        service = ChatService(settings_override)

        async def _fake_stream():
            yield SimpleNamespace(
                choices=[SimpleNamespace(
                    delta=SimpleNamespace(content="hi", reasoning_content=None, tool_calls=None),
                    finish_reason="stop",
                )],
                usage=SimpleNamespace(prompt_tokens=5, completion_tokens=2, total_tokens=7),
            )

        _FakeAsyncOpenAI.instances.clear()
        _FakeAsyncOpenAI.stream_factory = _fake_stream
        _FakeAsyncOpenAI.responses_stream_factory = None
        monkeypatch.setattr("app.services.chat_service.AsyncOpenAI", _FakeAsyncOpenAI)

        _ = [
            event async for event in service.stream_chat(
                messages=[{"role": "user", "content": "hi"}],
                model_config=ModelConfig(
                    provider="openai", model_id="openai/gpt-4o",
                    api_key="test-key", base_url=None,
                ),
                system_prompt="test", xml_context="",
            )
        ]

        inst = _FakeAsyncOpenAI.instances[0]
        assert len(inst.calls) == 1
        assert len(inst.responses_calls) == 0


class TestReasoningDeltaHandling:
    """Tests for response.reasoning.delta event parsing."""

    @pytest.mark.asyncio
    async def test_reasoning_delta_string(self, settings_override, monkeypatch):
        """Raw reasoning delta as a plain string."""
        settings_override.OPENAI_API_MODE = "responses"
        service = ChatService(settings_override)

        async def _fake_responses_stream():
            yield SimpleNamespace(type="response.reasoning.delta", delta="thinking about this...")
            yield SimpleNamespace(
                type="response.output_text.delta", delta="done",
                item_id="i1", output_index=0, content_index=0, sequence_number=2,
            )
            yield SimpleNamespace(
                type="response.completed",
                response=SimpleNamespace(
                    usage=SimpleNamespace(input_tokens=5, output_tokens=2), output=[],
                ),
            )

        _FakeAsyncOpenAI.instances.clear()
        _FakeAsyncOpenAI.responses_stream_factory = _fake_responses_stream
        monkeypatch.setattr("app.services.chat_service.AsyncOpenAI", _FakeAsyncOpenAI)

        events = [
            event async for event in service.stream_chat(
                messages=[{"role": "user", "content": "think"}],
                model_config=ModelConfig(
                    provider="openai", model_id="openai/gpt-4o",
                    api_key="test-key", base_url=None,
                ),
                system_prompt="test", xml_context="",
            )
        ]

        parsed = [json.loads(e[6:]) for e in events if e.startswith("data: {")]
        reasoning_deltas = [e for e in parsed if e["type"] == "reasoning-delta"]
        assert len(reasoning_deltas) >= 1
        assert reasoning_deltas[0]["delta"] == "thinking about this..."

    @pytest.mark.asyncio
    async def test_reasoning_delta_dict_with_text(self, settings_override, monkeypatch):
        """Raw reasoning delta as a dict with 'text' key."""
        settings_override.OPENAI_API_MODE = "responses"
        service = ChatService(settings_override)

        async def _fake_responses_stream():
            yield SimpleNamespace(type="response.reasoning.delta", delta={"text": "structured thought"})
            yield SimpleNamespace(
                type="response.completed",
                response=SimpleNamespace(
                    usage=SimpleNamespace(input_tokens=5, output_tokens=2), output=[],
                ),
            )

        _FakeAsyncOpenAI.instances.clear()
        _FakeAsyncOpenAI.responses_stream_factory = _fake_responses_stream
        monkeypatch.setattr("app.services.chat_service.AsyncOpenAI", _FakeAsyncOpenAI)

        events = [
            event async for event in service.stream_chat(
                messages=[{"role": "user", "content": "think"}],
                model_config=ModelConfig(
                    provider="openai", model_id="openai/gpt-4o",
                    api_key="test-key", base_url=None,
                ),
                system_prompt="test", xml_context="",
            )
        ]

        parsed = [json.loads(e[6:]) for e in events if e.startswith("data: {")]
        reasoning_deltas = [e for e in parsed if e["type"] == "reasoning-delta"]
        assert len(reasoning_deltas) >= 1
        assert reasoning_deltas[0]["delta"] == "structured thought"

    @pytest.mark.asyncio
    async def test_reasoning_delta_object_with_text_attr(self, settings_override, monkeypatch):
        """Raw reasoning delta as an object with .text attribute."""
        settings_override.OPENAI_API_MODE = "responses"
        service = ChatService(settings_override)

        async def _fake_responses_stream():
            yield SimpleNamespace(type="response.reasoning.delta", delta=SimpleNamespace(text="object thought"))
            yield SimpleNamespace(
                type="response.completed",
                response=SimpleNamespace(
                    usage=SimpleNamespace(input_tokens=5, output_tokens=2), output=[],
                ),
            )

        _FakeAsyncOpenAI.instances.clear()
        _FakeAsyncOpenAI.responses_stream_factory = _fake_responses_stream
        monkeypatch.setattr("app.services.chat_service.AsyncOpenAI", _FakeAsyncOpenAI)

        events = [
            event async for event in service.stream_chat(
                messages=[{"role": "user", "content": "think"}],
                model_config=ModelConfig(
                    provider="openai", model_id="openai/gpt-4o",
                    api_key="test-key", base_url=None,
                ),
                system_prompt="test", xml_context="",
            )
        ]

        parsed = [json.loads(e[6:]) for e in events if e.startswith("data: {")]
        reasoning_deltas = [e for e in parsed if e["type"] == "reasoning-delta"]
        assert len(reasoning_deltas) >= 1
        assert reasoning_deltas[0]["delta"] == "object thought"

    @pytest.mark.asyncio
    async def test_reasoning_delta_unrecognized_type_skipped(self, settings_override, monkeypatch):
        """Unrecognized reasoning delta type is silently skipped (no crash)."""
        settings_override.OPENAI_API_MODE = "responses"
        service = ChatService(settings_override)

        async def _fake_responses_stream():
            # delta is an int — unrecognized type
            yield SimpleNamespace(type="response.reasoning.delta", delta=42)
            yield SimpleNamespace(
                type="response.output_text.delta", delta="done",
                item_id="i1", output_index=0, content_index=0, sequence_number=2,
            )
            yield SimpleNamespace(
                type="response.completed",
                response=SimpleNamespace(
                    usage=SimpleNamespace(input_tokens=5, output_tokens=2), output=[],
                ),
            )

        _FakeAsyncOpenAI.instances.clear()
        _FakeAsyncOpenAI.responses_stream_factory = _fake_responses_stream
        monkeypatch.setattr("app.services.chat_service.AsyncOpenAI", _FakeAsyncOpenAI)

        events = [
            event async for event in service.stream_chat(
                messages=[{"role": "user", "content": "think"}],
                model_config=ModelConfig(
                    provider="openai", model_id="openai/gpt-4o",
                    api_key="test-key", base_url=None,
                ),
                system_prompt="test", xml_context="",
            )
        ]

        parsed = [json.loads(e[6:]) for e in events if e.startswith("data: {")]
        # Should still complete without crashing — text delta should be present
        event_types = [e["type"] for e in parsed]
        assert "text-delta" in event_types
        # No reasoning delta should be emitted for the unrecognized type
        reasoning_deltas = [e for e in parsed if e["type"] == "reasoning-delta"]
        assert len(reasoning_deltas) == 0


class TestBlockClosingBeforeTools:
    """Tests for reasoning-end/text-end emitted before tool-input-start."""

    @pytest.mark.asyncio
    async def test_reasoning_end_emitted_before_tool_input_start(
        self, settings_override, monkeypatch
    ):
        """reasoning-end is emitted before tool-input-start when model reasons then calls a tool."""
        settings_override.OPENAI_API_MODE = "responses"
        service = ChatService(settings_override)

        async def _fake_responses_stream():
            # Reasoning first
            yield SimpleNamespace(
                type="response.reasoning_summary_text.delta", delta="Let me think...",
                item_id="r1", output_index=0, summary_index=0, sequence_number=1,
            )
            # Then tool call
            yield SimpleNamespace(
                type="response.output_item.added",
                item=SimpleNamespace(type="function_call", id="item_1", call_id="call_1", name="display_diagram"),
            )
            yield SimpleNamespace(
                type="response.function_call_arguments.delta", delta='{"xml":"<test/>"}',
                item_id="item_1", output_index=1, sequence_number=3,
            )
            yield SimpleNamespace(
                type="response.function_call_arguments.done",
                item_id="item_1", name="display_diagram",
            )
            yield SimpleNamespace(
                type="response.completed",
                response=SimpleNamespace(
                    usage=SimpleNamespace(input_tokens=10, output_tokens=5),
                    output=[SimpleNamespace(type="function_call")],
                ),
            )

        _FakeAsyncOpenAI.instances.clear()
        _FakeAsyncOpenAI.responses_stream_factory = _fake_responses_stream
        monkeypatch.setattr("app.services.chat_service.AsyncOpenAI", _FakeAsyncOpenAI)

        events = [
            event async for event in service.stream_chat(
                messages=[{"role": "user", "content": "draw a box"}],
                model_config=ModelConfig(
                    provider="openai", model_id="openai/gpt-4o",
                    api_key="test-key", base_url=None,
                ),
                system_prompt="test", xml_context="",
            )
        ]

        parsed = [json.loads(e[6:]) for e in events if e.startswith("data: {")]
        event_types = [e["type"] for e in parsed]

        assert "reasoning-end" in event_types
        assert "tool-input-start" in event_types
        re_idx = event_types.index("reasoning-end")
        ti_idx = event_types.index("tool-input-start")
        assert re_idx < ti_idx, "reasoning-end must come before tool-input-start"

    @pytest.mark.asyncio
    async def test_text_end_emitted_before_tool_input_start(
        self, settings_override, monkeypatch
    ):
        """text-end is emitted before tool-input-start when model outputs text then calls a tool."""
        service = ChatService(settings_override)

        def _chunk(*, content=None, tool_name=None, arguments=None, finish_reason=None):
            tool_calls = None
            if tool_name is not None or arguments is not None:
                tool_calls = [SimpleNamespace(
                    index=0, id="call_1",
                    function=SimpleNamespace(name=tool_name, arguments=arguments),
                )]
            return SimpleNamespace(
                choices=[SimpleNamespace(
                    delta=SimpleNamespace(
                        content=content, reasoning_content=None, tool_calls=tool_calls,
                    ),
                    finish_reason=finish_reason,
                )],
                usage=None,
            )

        async def _fake_stream():
            yield _chunk(content="I'll create a diagram")
            yield _chunk(tool_name="display_diagram", arguments='{"xml":"<test/>"}', finish_reason="tool_calls")

        _FakeAsyncOpenAI.instances.clear()
        _FakeAsyncOpenAI.stream_factory = _fake_stream
        monkeypatch.setattr("app.services.chat_service.AsyncOpenAI", _FakeAsyncOpenAI)

        events = [
            event async for event in service.stream_chat(
                messages=[{"role": "user", "content": "draw"}],
                model_config=ModelConfig(
                    provider="openai", model_id="openai/gpt-4o",
                    api_key="test-key", base_url=None,
                ),
                system_prompt="test", xml_context="",
            )
        ]

        parsed = [json.loads(e[6:]) for e in events if e.startswith("data: {")]
        event_types = [e["type"] for e in parsed]

        assert "text-end" in event_types
        assert "tool-input-start" in event_types
        te_idx = event_types.index("text-end")
        ti_idx = event_types.index("tool-input-start")
        assert te_idx < ti_idx, "text-end must come before tool-input-start"


class TestToolCallIdConsistency:
    """Tests for item_id/call_id aliasing in Responses API adapter."""

    @pytest.mark.asyncio
    async def test_call_id_differs_from_item_id(self, settings_override, monkeypatch):
        """When call_id != item_id, the tool-input-available uses call_id."""
        settings_override.OPENAI_API_MODE = "responses"
        service = ChatService(settings_override)

        async def _fake_responses_stream():
            # .added with different item_id and call_id
            yield SimpleNamespace(
                type="response.output_item.added",
                item=SimpleNamespace(
                    type="function_call", id="item_abc", call_id="call_xyz", name="display_diagram",
                ),
            )
            yield SimpleNamespace(
                type="response.function_call_arguments.delta", delta='{"xml":"<test/>"}',
                item_id="item_abc", output_index=0, sequence_number=2,
            )
            yield SimpleNamespace(
                type="response.function_call_arguments.done",
                item_id="item_abc", name="display_diagram",
            )
            yield SimpleNamespace(
                type="response.completed",
                response=SimpleNamespace(
                    usage=SimpleNamespace(input_tokens=10, output_tokens=5),
                    output=[SimpleNamespace(type="function_call")],
                ),
            )

        _FakeAsyncOpenAI.instances.clear()
        _FakeAsyncOpenAI.responses_stream_factory = _fake_responses_stream
        monkeypatch.setattr("app.services.chat_service.AsyncOpenAI", _FakeAsyncOpenAI)

        events = [
            event async for event in service.stream_chat(
                messages=[{"role": "user", "content": "draw"}],
                model_config=ModelConfig(
                    provider="openai", model_id="openai/gpt-4o",
                    api_key="test-key", base_url=None,
                ),
                system_prompt="test", xml_context="",
            )
        ]

        parsed = [json.loads(e[6:]) for e in events if e.startswith("data: {")]
        # The tool-input-start/available should use call_xyz, not item_abc
        start_events = [e for e in parsed if e["type"] == "tool-input-start"]
        assert len(start_events) >= 1
        assert start_events[0]["toolCallId"] == "call_xyz"

        available_events = [e for e in parsed if e["type"] == "tool-input-available"]
        assert len(available_events) >= 1
        assert available_events[0]["toolCallId"] == "call_xyz"


class TestReasoningEffortWithTools:
    """Tests for reasoning_effort handling on Chat Completions path."""

    @pytest.mark.asyncio
    async def test_reasoning_effort_auto_upgrades_to_responses_when_tools_present(
        self, settings_override, monkeypatch
    ):
        """Direct OpenAI + reasoning model + tools + reasoning_effort auto-upgrades to Responses API."""
        settings_override.OPENAI_API_MODE = "completions"
        service = ChatService(settings_override)

        async def _fake_responses_stream():
            yield SimpleNamespace(type="response.output_text.delta", delta="ok", item_id="item_1", output_index=0, content_index=0, sequence_number=1)
            yield SimpleNamespace(
                type="response.completed",
                response=SimpleNamespace(
                    usage=SimpleNamespace(input_tokens=5, output_tokens=2),
                    output=[],
                ),
            )

        _FakeAsyncOpenAI.instances.clear()
        _FakeAsyncOpenAI.responses_stream_factory = _fake_responses_stream
        monkeypatch.setattr("app.services.chat_service.AsyncOpenAI", _FakeAsyncOpenAI)

        _ = [
            event async for event in service.stream_chat(
                messages=[{"role": "user", "content": "draw"}],
                model_config=ModelConfig(
                    provider="openai", model_id="openai/o3-mini",
                    api_key="test-key", base_url=None,  # direct OpenAI
                    extra_params={"reasoning_effort": "high"},
                ),
                system_prompt="test", xml_context="",
            )
        ]

        # Direct OpenAI + reasoning + tools → auto-upgrades to Responses API
        assert len(_FakeAsyncOpenAI.instances[0].responses_calls) == 1
        call_kwargs = _FakeAsyncOpenAI.instances[0].responses_calls[0]
        assert call_kwargs["reasoning"] == {"effort": "high", "summary": "auto"}

    @pytest.mark.asyncio
    async def test_reasoning_effort_kept_when_proxy_with_tools(
        self, settings_override, monkeypatch
    ):
        """reasoning_effort IS passed when using a proxy (base_url set), even with tools."""
        settings_override.OPENAI_API_MODE = "completions"
        service = ChatService(settings_override)

        async def _fake_stream():
            yield SimpleNamespace(
                choices=[SimpleNamespace(
                    delta=SimpleNamespace(content="ok", reasoning_content=None, tool_calls=None),
                    finish_reason="stop",
                )],
                usage=SimpleNamespace(prompt_tokens=5, completion_tokens=2, total_tokens=7),
            )

        _FakeAsyncOpenAI.instances.clear()
        _FakeAsyncOpenAI.stream_factory = _fake_stream
        monkeypatch.setattr("app.services.chat_service.AsyncOpenAI", _FakeAsyncOpenAI)

        _ = [
            event async for event in service.stream_chat(
                messages=[{"role": "user", "content": "draw"}],
                model_config=ModelConfig(
                    provider="openai", model_id="openai/gemini-3-flash",
                    api_key="test-key", base_url="http://localhost:4000",  # LiteLLM proxy
                    extra_params={"reasoning_effort": "high"},
                ),
                system_prompt="test", xml_context="",
            )
        ]

        # Proxy + tools → reasoning_effort should be passed through
        call_kwargs = _FakeAsyncOpenAI.instances[0].calls[0]
        assert call_kwargs.get("reasoning_effort") == "high"

    @pytest.mark.asyncio
    async def test_reasoning_effort_passed_when_no_tools(
        self, settings_override, monkeypatch
    ):
        """reasoning_effort is passed to Chat Completions API when no tools are present."""
        settings_override.OPENAI_API_MODE = "completions"
        service = ChatService(settings_override)

        async def _fake_stream():
            yield SimpleNamespace(
                choices=[SimpleNamespace(
                    delta=SimpleNamespace(content="ok", reasoning_content=None, tool_calls=None),
                    finish_reason="stop",
                )],
                usage=SimpleNamespace(prompt_tokens=5, completion_tokens=2, total_tokens=7),
            )

        _FakeAsyncOpenAI.instances.clear()
        _FakeAsyncOpenAI.stream_factory = _fake_stream
        monkeypatch.setattr("app.services.chat_service.AsyncOpenAI", _FakeAsyncOpenAI)
        # Empty tool defs so the "not tools" branch triggers
        monkeypatch.setattr("app.services.chat_service._CACHED_TOOL_DEFS", [])

        _ = [
            event async for event in service.stream_chat(
                messages=[{"role": "user", "content": "explain something"}],
                model_config=ModelConfig(
                    provider="openai", model_id="openai/o3-mini",
                    api_key="test-key", base_url=None,
                    extra_params={"reasoning_effort": "high"},
                ),
                system_prompt="test", xml_context="",
            )
        ]

        call_kwargs = _FakeAsyncOpenAI.instances[0].calls[0]
        assert call_kwargs.get("reasoning_effort") == "high"


class TestMultiTurnToolRoundTrip:
    """Test multi-turn tool use via Responses API (second-turn continuation)."""

    @pytest.mark.asyncio
    async def test_multi_turn_server_tool_roundtrip_via_responses_api(
        self, settings_override, monkeypatch
    ):
        """A server-side tool round-trip: model calls get_shape_library, server executes,
        model gets result and responds with text on a second turn."""
        settings_override.OPENAI_API_MODE = "responses"
        service = ChatService(settings_override)
        call_count = 0

        async def _fake_responses_stream_factory():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call: model calls get_shape_library (server-side tool)
                yield SimpleNamespace(
                    type="response.output_item.added",
                    item=SimpleNamespace(
                        type="function_call", id="item_1", call_id="call_1",
                        name="get_shape_library",
                    ),
                )
                yield SimpleNamespace(
                    type="response.function_call_arguments.delta",
                    delta='{"category":"flowchart"}',
                    item_id="item_1", output_index=0, sequence_number=2,
                )
                yield SimpleNamespace(
                    type="response.function_call_arguments.done",
                    item_id="item_1", name="get_shape_library",
                )
                yield SimpleNamespace(
                    type="response.completed",
                    response=SimpleNamespace(
                        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
                        output=[SimpleNamespace(type="function_call")],
                    ),
                )
            else:
                # Second call: after tool output, model produces text
                yield SimpleNamespace(
                    type="response.output_text.delta", delta="Here is your diagram.",
                    item_id="item_2", output_index=0, content_index=0, sequence_number=1,
                )
                yield SimpleNamespace(
                    type="response.completed",
                    response=SimpleNamespace(
                        usage=SimpleNamespace(input_tokens=20, output_tokens=10),
                        output=[],
                    ),
                )

        _FakeAsyncOpenAI.instances.clear()
        _FakeAsyncOpenAI.responses_stream_factory = _fake_responses_stream_factory
        monkeypatch.setattr("app.services.chat_service.AsyncOpenAI", _FakeAsyncOpenAI)

        events = [
            event async for event in service.stream_chat(
                messages=[{"role": "user", "content": "draw a flowchart"}],
                model_config=ModelConfig(
                    provider="openai", model_id="openai/gpt-4o",
                    api_key="test-key", base_url=None,
                ),
                system_prompt="test", xml_context="",
            )
        ]

        parsed = [json.loads(e[6:]) for e in events if e.startswith("data: {")]
        event_types = [e["type"] for e in parsed]

        # get_shape_library is server-side, so tool-input-available is emitted (not tool-input-start)
        assert "tool-input-available" in event_types

        # Server-side tool produces either tool-output-available or tool-output-error
        assert ("tool-output-available" in event_types or "tool-output-error" in event_types)

        # Should have text from second turn (after tool round-trip)
        assert "text-delta" in event_types

        # Tool round-trip triggers at least one additional API call
        assert call_count >= 2

        # Find the second responses call that includes the tool output
        all_responses_calls = []
        for inst in _FakeAsyncOpenAI.instances:
            all_responses_calls.extend(inst.responses_calls)
        assert len(all_responses_calls) >= 2, "Should have at least 2 Responses API calls"

        # The second call should include function_call_output in the input
        second_call = all_responses_calls[1]
        input_items = second_call.get("input", [])
        has_tool_output = any(
            item.get("type") == "function_call_output"
            for item in input_items
            if isinstance(item, dict)
        )
        assert has_tool_output, "Second Responses API call should include function_call_output in input"


class TestResponsesApiDiagramGeneration:
    """Regression test: reasoning model generates reasoning, then calls display_diagram via Responses API.
    This reproduces the exact failure scenario from #S250 where diagrams stopped rendering."""

    @pytest.mark.asyncio
    async def test_reasoning_then_diagram_tool_call_produces_correct_event_sequence(
        self, settings_override, monkeypatch
    ):
        """Full flow: reasoning tokens → text → display_diagram tool call.
        Verifies the SSE event sequence is correct for the frontend AI SDK."""
        settings_override.OPENAI_API_MODE = "responses"
        service = ChatService(settings_override)

        async def _fake_responses_stream():
            # 1. Reasoning summary
            yield SimpleNamespace(
                type="response.reasoning_summary_text.delta",
                delta="I need to create a flowchart with two boxes.",
                item_id="rs_1", output_index=0, summary_index=0, sequence_number=1,
            )
            yield SimpleNamespace(
                type="response.reasoning_summary_text.delta",
                delta=" Let me use the display_diagram tool.",
                item_id="rs_1", output_index=0, summary_index=0, sequence_number=2,
            )
            # 2. Tool call added
            yield SimpleNamespace(
                type="response.output_item.added",
                item=SimpleNamespace(
                    type="function_call", id="fc_item_001",
                    call_id="call_abc123", name="display_diagram",
                ),
            )
            # 3. Tool call arguments (streamed in chunks like real API)
            xml_part1 = '{"xml":"<mxGraphModel><root><mxCell id=\\\\"0\\\\"/>'
            xml_part2 = '<mxCell id=\\\\"1\\\\" parent=\\\\"0\\\\"/>'
            xml_part3 = '<mxCell id=\\\\"2\\\\" value=\\\\"Start\\\\" style=\\\\"rounded=1;\\\\" vertex=\\\\"1\\\\" parent=\\\\"1\\\\"/>'
            xml_part4 = '</root></mxGraphModel>"}'
            yield SimpleNamespace(
                type="response.function_call_arguments.delta",
                delta=xml_part1, item_id="fc_item_001", output_index=1, sequence_number=3,
            )
            yield SimpleNamespace(
                type="response.function_call_arguments.delta",
                delta=xml_part2, item_id="fc_item_001", output_index=1, sequence_number=4,
            )
            yield SimpleNamespace(
                type="response.function_call_arguments.delta",
                delta=xml_part3, item_id="fc_item_001", output_index=1, sequence_number=5,
            )
            yield SimpleNamespace(
                type="response.function_call_arguments.delta",
                delta=xml_part4, item_id="fc_item_001", output_index=1, sequence_number=6,
            )
            # 4. Tool call done
            yield SimpleNamespace(
                type="response.function_call_arguments.done",
                item_id="fc_item_001",
            )
            # 5. Response completed with function_call in output
            yield SimpleNamespace(
                type="response.completed",
                response=SimpleNamespace(
                    usage=SimpleNamespace(input_tokens=500, output_tokens=200),
                    output=[SimpleNamespace(type="function_call")],
                ),
            )

        _FakeAsyncOpenAI.instances.clear()
        _FakeAsyncOpenAI.responses_stream_factory = _fake_responses_stream
        monkeypatch.setattr("app.services.chat_service.AsyncOpenAI", _FakeAsyncOpenAI)

        events = [
            event async for event in service.stream_chat(
                messages=[{"role": "user", "content": "draw a flowchart with Start and End boxes"}],
                model_config=ModelConfig(
                    provider="openai", model_id="openai/o3",
                    api_key="test-key", base_url=None,
                    extra_params={"reasoning_effort": "medium"},
                ),
                system_prompt="You are a diagram assistant.", xml_context="",
            )
        ]

        parsed = [json.loads(e[6:]) for e in events if e.startswith("data: {")]
        event_types = [e["type"] for e in parsed]

        # === Verify correct event ordering ===

        # 1. Stream starts
        assert event_types[0] == "start"

        # 2. Reasoning block: start → delta(s) → end
        assert "reasoning-start" in event_types
        assert "reasoning-delta" in event_types
        assert "reasoning-end" in event_types
        re_start = event_types.index("reasoning-start")
        re_end = event_types.index("reasoning-end")
        assert re_start < re_end

        # 3. Reasoning block MUST close before tool events
        assert "tool-input-start" in event_types
        ti_start = event_types.index("tool-input-start")
        assert re_end < ti_start, (
            f"reasoning-end (idx {re_end}) must come before tool-input-start (idx {ti_start})"
        )

        # 4. Tool input deltas are streamed
        assert event_types.count("tool-input-delta") >= 1

        # 5. tool-input-available is emitted with correct tool name and call_id
        assert "tool-input-available" in event_types
        available = next(e for e in parsed if e["type"] == "tool-input-available")
        assert available["toolName"] == "display_diagram"
        assert available["toolCallId"] == "call_abc123"
        assert "xml" in available["input"]

        # 6. Finish event
        assert "finish" in event_types

        # === Verify the tool-input-start also has the correct IDs ===
        start_evt = next(e for e in parsed if e["type"] == "tool-input-start")
        assert start_evt["toolCallId"] == "call_abc123"
        assert start_evt["toolName"] == "display_diagram"
