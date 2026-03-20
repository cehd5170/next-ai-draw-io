"""
Request/response schemas for the /parse-url endpoint.
"""

from __future__ import annotations

from pydantic import BaseModel


class ParseUrlRequest(BaseModel):
    url: str


class ParseUrlResponse(BaseModel):
    title: str
    content: str
    charCount: int
