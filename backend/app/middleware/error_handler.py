"""
Global exception handler middleware for the FastAPI application.

Responsibilities:
- Map litellm / provider exceptions to appropriate HTTP status codes.
- Scrub sensitive keywords from error messages before they reach the client.
- Return structured ``ErrorResponse`` JSON bodies.
- Log full tracebacks at DEBUG level (or always when log level <= DEBUG).
"""

from __future__ import annotations

import logging
import os
import traceback
from typing import Callable

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sensitive keyword scrubbing
# ---------------------------------------------------------------------------

_SENSITIVE_PATTERNS = frozenset(
    {
        "key",
        "token",
        "secret",
        "password",
        "credential",
        "sig",
        "signature",
        "bearer",
        "auth",
        "passwd",
    }
)

_SAFE_AUTH_MESSAGE = "Authentication failed. Please check your credentials."


def _contains_sensitive_keyword(message: str) -> bool:
    """Return True if the error message may contain sensitive data."""
    lower = message.lower()
    return any(kw in lower for kw in _SENSITIVE_PATTERNS)


def _safe_message(original: str) -> str:
    """
    Return a sanitised version of *original*.

    If the message contains any sensitive keyword it is replaced entirely
    with a generic authentication error string so that API keys, tokens,
    or secrets are never echoed back to the caller.
    """
    if _contains_sensitive_keyword(original):
        return _SAFE_AUTH_MESSAGE
    return original


# ---------------------------------------------------------------------------
# LiteLLM / provider HTTP status mapping
# ---------------------------------------------------------------------------

# (import is deferred to avoid a hard dependency at module load time when
# litellm is not installed during testing)

def _status_from_litellm(exc: Exception) -> int:
    """
    Inspect a litellm exception and return an appropriate HTTP status code.

    litellm surfaces a ``status_code`` attribute on most of its exception
    types.  We fall back to a mapping based on class name when that is
    absent.
    """
    # Check for explicit status_code attribute (all litellm APIError subclasses)
    if hasattr(exc, "status_code") and isinstance(exc.status_code, int):
        return exc.status_code

    cls_name = type(exc).__name__

    # litellm-specific exception types → HTTP status
    _LITELLM_STATUS_MAP: dict[str, int] = {
        "AuthenticationError": 401,
        "NotFoundError": 404,
        "BadRequestError": 400,
        "RateLimitError": 429,
        "ServiceUnavailableError": 503,
        "Timeout": 504,
        "APIConnectionError": 502,
        "APIError": 502,
        "ContextWindowExceededError": 400,
        "ContentPolicyViolationError": 400,
        "InternalServerError": 500,
        "UnprocessableEntityError": 422,
        "PermissionDeniedError": 403,
        "NotImplementedError": 501,
        "BudgetExceededError": 429,
    }

    for key, status in _LITELLM_STATUS_MAP.items():
        if cls_name.endswith(key):
            return status

    return 500


# ---------------------------------------------------------------------------
# FastAPI exception handlers
# ---------------------------------------------------------------------------

_is_debug = os.getenv("LOG_LEVEL", "").upper() in ("DEBUG", "TRACE") or (
    os.getenv("NODE_ENV", "") == "development"
)


def _build_response(exc: Exception, status: int) -> JSONResponse:
    """
    Build a structured JSON error response.

    In debug mode a ``detail`` field containing the raw exception message is
    included to assist local development.  In production the ``detail`` field
    is suppressed when the message contains sensitive keywords.
    """
    raw_message = str(exc)
    client_message = _safe_message(raw_message)

    body: dict[str, str | None] = {"error": client_message}

    if _is_debug:
        # Even in debug we don't expose sanitised messages as detail –
        # we expose the original so developers can see what went wrong.
        body["detail"] = raw_message

    return JSONResponse(status_code=status, content=body)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Catch-all handler for unhandled exceptions.

    Registered on the FastAPI app instance so that every unhandled exception
    is converted into a structured JSON response rather than a plain 500.
    """
    status = _status_from_litellm(exc)

    if _is_debug:
        logger.debug(
            "Unhandled exception on %s %s:\n%s",
            request.method,
            request.url.path,
            "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
        )
    else:
        logger.error(
            "Unhandled exception [%d] on %s %s: %s",
            status,
            request.method,
            request.url.path,
            type(exc).__name__,
        )

    return _build_response(exc, status)


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Handler for FastAPI ``HTTPException`` instances.

    Converts them to the standard ``ErrorResponse`` shape so the client
    always receives a consistent JSON structure.
    """
    from fastapi import HTTPException  # noqa: PLC0415

    if isinstance(exc, HTTPException):
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        body: dict[str, str | None] = {"error": detail}
        return JSONResponse(status_code=exc.status_code, content=body)

    # Fallback: treat as unhandled
    return await unhandled_exception_handler(request, exc)
