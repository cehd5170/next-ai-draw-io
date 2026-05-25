from __future__ import annotations

import io
import re

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse

from app.tools.table_pptx import get_pptx

router = APIRouter()

_TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")

PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


@router.get("/download/{token}", summary="Download a previously generated PPTX file")
async def download(token: str):
    if not _TOKEN_RE.match(token):
        return JSONResponse(status_code=400, content={"error": "Invalid token."})

    data = get_pptx(token)
    if data is None:
        return JSONResponse(status_code=404, content={"error": "File not found or expired."})

    return StreamingResponse(
        io.BytesIO(data),
        media_type=PPTX_MIME,
        headers={"Content-Disposition": "attachment; filename=table.pptx"},
    )
