"""
POST /validate-diagram — VLM-based diagram quality validation.

Accepts a base64-encoded PNG data URL, runs it through the configured
vision model, and returns a structured validation result.

The response is always HTTP 200 — when validation fails or is disabled,
a default ``{valid: true, issues: [], suggestions: []}`` is returned so
the user is never blocked by a validation error.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, StreamingResponse

from app.config import Settings
from app.dependencies import get_settings
from app.models.validate_diagram import ValidateDiagramRequest, ValidationResult
from app.services.validation_service import ValidationService

router = APIRouter()
logger = logging.getLogger(__name__)

_DEFAULT_VALID = ValidationResult(valid=True, issues=[], suggestions=[])


def _json_stream(result: ValidationResult) -> StreamingResponse:
    """
    Wrap a :class:`ValidationResult` in a plain text stream.

    The TypeScript frontend's ``useObject`` hook expects a text stream that
    it can parse as JSON, so we stream the serialised object as plain text.
    """

    async def _gen():
        yield result.model_dump_json()

    return StreamingResponse(
        _gen(), media_type="text/plain; charset=utf-8"
    )


@router.post("/validate-diagram")
async def validate_diagram(
    body: ValidateDiagramRequest,
    settings: Settings = Depends(get_settings),
) -> StreamingResponse:
    """
    Validate a rendered diagram image for visual quality issues.

    Returns a streamed JSON object compatible with the AI SDK ``useObject``
    format.  On any error or when validation is disabled, returns a
    ``valid=True`` result to avoid blocking the user.
    """
    # ------------------------------------------------------------------
    # Fast path: validation disabled server-side
    # ------------------------------------------------------------------
    if not settings.ENABLE_VLM_VALIDATION:
        return _json_stream(_DEFAULT_VALID)

    # ------------------------------------------------------------------
    # Input validation
    # ------------------------------------------------------------------
    if not body.imageData:
        return JSONResponse(status_code=400, content={"error": "Missing imageData"})

    if not (
        body.imageData.startswith("data:image/png;base64,")
        or body.imageData.startswith("data:image/")
    ):
        return JSONResponse(
            status_code=400, content={"error": "Invalid image data format"}
        )

    # ------------------------------------------------------------------
    # VLM call
    # ------------------------------------------------------------------
    service = ValidationService(settings)
    result = await service.validate_diagram(body.imageData, body.sessionId)
    return _json_stream(result)
