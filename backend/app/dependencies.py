"""
FastAPI dependency functions used across route handlers.

Provides:
- get_settings()         – cached Settings singleton
- verify_access_code()   – gate requests behind ACCESS_CODE_LIST
- get_client_overrides() – parse per-request provider override headers
- get_user_id()          – derive a stable user identifier from the request
"""

from __future__ import annotations

import logging
from typing import Annotated, Optional

from fastapi import Depends, Header, HTTPException, Request

from app.config import Settings
from app.config import get_settings as _get_settings
from app.models.chat import ClientOverrides

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Settings dependency
# ---------------------------------------------------------------------------


def get_settings() -> Settings:
    """Return the cached application Settings."""
    return _get_settings()


SettingsDep = Annotated[Settings, Depends(get_settings)]


# ---------------------------------------------------------------------------
# Access-code guard
# ---------------------------------------------------------------------------


async def verify_access_code(
    request: Request,
    settings: SettingsDep,
) -> None:
    """
    Raise HTTP 401 when ACCESS_CODE_LIST is configured and the
    ``x-access-code`` header is missing or does not match any entry.

    When ACCESS_CODE_LIST is not set the check is skipped entirely.
    """
    codes = settings.access_codes
    if not codes:
        # No restriction configured – allow all requests
        return

    provided = request.headers.get("x-access-code", "")
    if not provided or provided not in codes:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing access code. Please configure it in Settings.",
        )


AccessCodeDep = Annotated[None, Depends(verify_access_code)]


# ---------------------------------------------------------------------------
# Client provider overrides
# ---------------------------------------------------------------------------


async def get_client_overrides(request: Request) -> ClientOverrides:
    """
    Extract per-request AI provider override headers sent by the client UI
    and pack them into a :class:`ClientOverrides` dataclass.

    All fields are optional; unset headers become ``None``.
    """
    h = request.headers

    return ClientOverrides(
        provider=h.get("x-ai-provider"),
        base_url=h.get("x-ai-base-url"),
        api_key=h.get("x-ai-api-key"),
        model_id=h.get("x-ai-model"),
        selected_model_id=h.get("x-selected-model-id"),
        # AWS Bedrock credentials
        aws_access_key_id=h.get("x-aws-access-key-id"),
        aws_secret_access_key=h.get("x-aws-secret-access-key"),
        aws_region=h.get("x-aws-region"),
        aws_session_token=h.get("x-aws-session-token"),
        # Vertex AI (Express Mode)
        vertex_api_key=h.get("x-vertex-api-key"),
        # Style preference
        minimal_style=h.get("x-minimal-style", "").lower() == "true",
    )


ClientOverridesDep = Annotated[ClientOverrides, Depends(get_client_overrides)]


# ---------------------------------------------------------------------------
# User ID
# ---------------------------------------------------------------------------


async def get_user_id(request: Request) -> str:
    """
    Derive a user identifier from the request.

    Uses the first IP in ``X-Forwarded-For`` when present (typical in
    reverse-proxy deployments); falls back to the direct client host; and
    returns ``"anonymous"`` when neither is available.
    """
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        # The header may contain a comma-separated list; the leftmost is the
        # original client IP.
        first_ip = forwarded_for.split(",")[0].strip()
        if first_ip:
            return first_ip

    client = request.client
    if client and client.host:
        return client.host

    return "anonymous"


UserIdDep = Annotated[str, Depends(get_user_id)]
