"""
Request/response schemas for the /config endpoint.
"""

from __future__ import annotations

from pydantic import BaseModel


class ConfigResponse(BaseModel):
    """Public configuration surfaced to the frontend."""

    accessCodeRequired: bool
    dailyRequestLimit: int
    dailyTokenLimit: int
    tpmLimit: int
    maxFileSize: int
    maxFiles: int
    maxImageSize: int
    enableVlmValidation: bool
