"""
POST /log-feedback — record user feedback (thumbs-up / thumbs-down) in Langfuse.

This endpoint is a no-op when Langfuse is not configured — it always returns
``{"success": true}`` in that case so the client does not need to handle
missing observability infrastructure.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.config import Settings
from app.dependencies import get_settings, get_user_id
from app.models.feedback import LogFeedbackRequest, LogResponse
from app.services.langfuse_client import LangfuseWrapper

router = APIRouter()
logger = logging.getLogger(__name__)

# Cache the wrapper per settings instance (settings is a singleton)
_wrapper_cache: dict[int, LangfuseWrapper] = {}


def _get_wrapper(settings: Settings) -> LangfuseWrapper:
    key = id(settings)
    if key not in _wrapper_cache:
        _wrapper_cache[key] = LangfuseWrapper(settings)
    return _wrapper_cache[key]


@router.post("/log-feedback", response_model=LogResponse)
async def log_feedback(
    body: LogFeedbackRequest,
    raw_request: Request,
    settings: Settings = Depends(get_settings),
    user_id: str = Depends(get_user_id),
) -> JSONResponse:
    """
    Forward a user feedback score to Langfuse.

    - Returns ``{success: true, logged: false}`` when Langfuse is not configured.
    - Returns ``{success: true, logged: false}`` when no ``sessionId`` is provided
      (to prevent attaching scores to the wrong trace).
    - Returns ``{success: true, logged: true}`` on successful ingestion.
    - Returns ``{success: false, error: ...}`` with HTTP 500 if ingestion fails.
    """
    wrapper = _get_wrapper(settings)

    if not settings.langfuse_enabled:
        return JSONResponse(
            content=LogResponse(success=True, logged=False).model_dump()
        )

    if not body.sessionId:
        return JSONResponse(
            content=LogResponse(success=True, logged=False).model_dump()
        )

    try:
        wrapper.feedback_score(
            message_id=body.messageId,
            feedback=body.feedback,
            session_id=body.sessionId,
            user_id=user_id,
        )
        return JSONResponse(
            content=LogResponse(success=True, logged=True).model_dump()
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Langfuse feedback logging failed: %s", exc)
        return JSONResponse(
            status_code=500,
            content=LogResponse(
                success=False, error="Failed to log feedback"
            ).model_dump(),
        )
