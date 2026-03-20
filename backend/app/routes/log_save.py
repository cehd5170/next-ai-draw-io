"""
POST /log-save — record a diagram-save event in Langfuse.

This endpoint is a no-op when Langfuse is not configured — it always returns
``{"success": true}`` in that case.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.config import Settings
from app.dependencies import get_settings
from app.models.feedback import LogResponse, LogSaveRequest
from app.services.langfuse_client import LangfuseWrapper

router = APIRouter()
logger = logging.getLogger(__name__)

_wrapper_cache: dict[int, LangfuseWrapper] = {}


def _get_wrapper(settings: Settings) -> LangfuseWrapper:
    key = id(settings)
    if key not in _wrapper_cache:
        _wrapper_cache[key] = LangfuseWrapper(settings)
    return _wrapper_cache[key]


@router.post("/log-save", response_model=LogResponse)
async def log_save(
    body: LogSaveRequest,
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """
    Attach a 'diagram-saved' event to the most recent Langfuse trace for the
    session.

    - Returns ``{success: true, logged: false}`` when Langfuse is not configured.
    - Returns ``{success: true, logged: false}`` when no ``sessionId`` is provided.
    - Returns ``{success: true, logged: true/false}`` based on whether a trace
      was found for the given session.
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
        wrapper.log_save(
            session_id=body.sessionId,
            filename=body.filename,
            format=body.format,
        )
        return JSONResponse(
            content=LogResponse(success=True, logged=True).model_dump()
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Langfuse save logging failed: %s", exc)
        return JSONResponse(
            status_code=500,
            content=LogResponse(
                success=False, error="Failed to log save"
            ).model_dump(),
        )
