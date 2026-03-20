"""
Request/response schemas for the /validate-diagram endpoint.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel


class ValidateDiagramRequest(BaseModel):
    """Diagram image to validate."""

    imageData: str
    """Base64 PNG data URL, e.g. 'data:image/png;base64,...'"""

    sessionId: Optional[str] = None


class ValidationIssue(BaseModel):
    type: Literal["overlap", "edge_routing", "text", "layout", "rendering"]
    severity: Literal["critical", "warning"]
    description: str


class ValidationResult(BaseModel):
    valid: bool
    issues: list[ValidationIssue] = []
    suggestions: list[str] = []
