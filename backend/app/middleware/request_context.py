"""
Request-scoped context helpers.

Provides a request ID context variable and a logging record factory so every
application log line can include the current request_id when available.
"""

from __future__ import annotations

import logging
import time
from contextvars import ContextVar, Token
from uuid import uuid4

from starlette.types import ASGIApp, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-Id"

_request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
_factory_installed = False


def generate_request_id() -> str:
    """Return a short, collision-resistant request identifier."""
    return uuid4().hex[:12]


def get_request_id() -> str:
    """Return the request ID for the current context, or ``-``."""
    return _request_id_var.get()


def set_request_id(request_id: str) -> Token[str]:
    """Bind *request_id* to the current context and return the reset token."""
    return _request_id_var.set(request_id)


def reset_request_id(token: Token[str]) -> None:
    """Restore the previous request ID binding."""
    _request_id_var.reset(token)


def install_request_id_log_record_factory() -> None:
    """
    Ensure all log records have a ``request_id`` attribute.

    The factory is installed once at process start and reads the active value
    from the context variable on every log emission.
    """
    global _factory_installed
    if _factory_installed:
        return

    old_factory = logging.getLogRecordFactory()

    def record_factory(*args: object, **kwargs: object) -> logging.LogRecord:
        record = old_factory(*args, **kwargs)
        if not hasattr(record, "request_id"):
            record.request_id = get_request_id()
        return record

    logging.setLogRecordFactory(record_factory)
    _factory_installed = True


class RequestContextMiddleware:
    """ASGI middleware that binds request context for the lifetime of a request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {
            key.decode("latin-1"): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        request_id = (
            headers.get(REQUEST_ID_HEADER.lower())
            or headers.get(REQUEST_ID_HEADER)
            or generate_request_id()
        )
        token = set_request_id(request_id)

        state = scope.setdefault("state", {})
        state["request_id"] = request_id
        state["request_started_at"] = time.monotonic()

        async def send_wrapper(message: dict) -> None:
            if message.get("type") == "http.response.start":
                response_headers = list(message.get("headers", []))
                response_headers.append(
                    (REQUEST_ID_HEADER.lower().encode("latin-1"), request_id.encode("latin-1"))
                )
                message["headers"] = response_headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            reset_request_id(token)
