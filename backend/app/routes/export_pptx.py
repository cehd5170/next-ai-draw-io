"""
POST /export-pptx — convert draw.io XML to a PowerPoint presentation.

Accepts a ``{xml, filename, options}`` JSON body, runs the conversion through
:class:`~app.services.pptx_export_service.PptxExportService`, and returns the
raw PPTX bytes as an ``application/vnd.openxmlformats-...`` attachment.
"""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, Response

from app.config import Settings
from app.dependencies import get_settings
from app.models.export_pptx import ExportPptxRequest
from app.services.pptx_export_service import PptxExportService

router = APIRouter()
logger = logging.getLogger(__name__)

_PPTX_MIME = (
    "application/vnd.openxmlformats-officedocument.presentationml.presentation"
)

# Sanitise Content-Disposition filenames — allow only safe characters
_SAFE_FILENAME_RE = re.compile(r'[^A-Za-z0-9._\- ]')


def _safe_filename(name: str | None) -> str:
    """Return a sanitised filename, falling back to 'diagram.pptx'."""
    candidate = (name or "diagram.pptx").strip()
    # Strip any path separators
    candidate = candidate.replace("/", "").replace("\\", "")
    # Replace unsafe characters
    candidate = _SAFE_FILENAME_RE.sub("_", candidate)
    # Ensure it ends with .pptx
    if not candidate.lower().endswith(".pptx"):
        candidate = candidate + ".pptx"
    return candidate or "diagram.pptx"


@router.post("/export-pptx")
async def export_pptx(
    body: ExportPptxRequest,
    settings: Settings = Depends(get_settings),
) -> Response:
    """
    Convert draw.io XML to a PPTX file and return it as a binary download.

    Status codes
    ------------
    200  Binary PPTX attachment on success
    400  When the XML is empty or invalid
    500  When the conversion library raises an unexpected error
    503  When the drawio2pptx library is not installed
    """
    if not body.xml or not body.xml.strip():
        return JSONResponse(
            status_code=400,
            content={"error": "XML is required and must not be empty"},
        )

    filename = _safe_filename(body.filename)

    service = PptxExportService()
    try:
        pptx_bytes = await service.export(body.xml, filename)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    except RuntimeError as exc:
        msg = str(exc)
        if "not installed" in msg.lower() or "import" in msg.lower():
            return JSONResponse(status_code=503, content={"error": msg})
        logger.error("PPTX export failed: %s", exc, exc_info=True)
        return JSONResponse(status_code=500, content={"error": msg})
    except Exception as exc:  # noqa: BLE001
        logger.error("PPTX export unexpected error: %s", exc, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": "An unexpected error occurred during PPTX export"},
        )

    return Response(
        content=pptx_bytes,
        media_type=_PPTX_MIME,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(pptx_bytes)),
        },
    )
