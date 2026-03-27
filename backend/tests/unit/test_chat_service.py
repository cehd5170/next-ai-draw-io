import asyncio

import pytest

from app.services.chat_service import ChatService


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
