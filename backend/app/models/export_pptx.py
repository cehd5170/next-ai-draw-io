"""
Request/response schemas for the /export-pptx endpoint.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class ExportOptions(BaseModel):
    """Optional slide dimension overrides for PPTX export."""

    slide_width: Optional[int] = Field(
        default=None,
        description="Slide width in EMUs (English Metric Units). Default: python-pptx default.",
        ge=1,
    )
    slide_height: Optional[int] = Field(
        default=None,
        description="Slide height in EMUs. Default: python-pptx default.",
        ge=1,
    )


class ExportPptxRequest(BaseModel):
    xml: str = Field(..., description="draw.io XML to convert to PPTX.")
    filename: Optional[str] = Field(
        default="diagram.pptx",
        description="Output filename for the Content-Disposition header.",
        max_length=255,
    )
    options: Optional[ExportOptions] = Field(
        default=None,
        description="Optional slide dimension overrides.",
    )
