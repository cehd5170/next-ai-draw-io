"""
POST /verify-access-code — validate an access code supplied in the header.

Returns ``{"valid": true}`` when:
- No ACCESS_CODE_LIST is configured (unrestricted server)
- The ``x-access-code`` header matches one of the configured codes

Returns HTTP 401 with ``{"valid": false, "message": ...}`` otherwise.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.config import Settings
from app.dependencies import get_settings

router = APIRouter()


@router.post("/verify-access-code")
async def verify_access_code(
    raw_request: Request,
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """
    Test whether the caller's access code is accepted.

    This endpoint is intentionally unauthenticated so the client can use it
    to verify credentials before making substantive requests.
    """
    codes = settings.access_codes

    # No restriction configured — always valid
    if not codes:
        return JSONResponse(
            content={"valid": True, "message": "No access code required"}
        )

    provided = raw_request.headers.get("x-access-code", "")

    if not provided:
        return JSONResponse(
            status_code=401,
            content={"valid": False, "message": "Access code is required"},
        )

    if provided not in codes:
        return JSONResponse(
            status_code=401,
            content={"valid": False, "message": "Invalid access code"},
        )

    return JSONResponse(content={"valid": True, "message": "Access code is valid"})
