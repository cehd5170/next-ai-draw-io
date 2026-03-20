"""
Request/response schemas for /log-feedback and /log-save endpoints.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class LogFeedbackRequest(BaseModel):
    messageId: str = Field(min_length=1, max_length=200)
    feedback: Literal["good", "bad"]
    sessionId: Optional[str] = Field(default=None, min_length=1, max_length=200)


class LogSaveRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    format: Literal["drawio", "png", "svg"]
    sessionId: Optional[str] = Field(default=None, min_length=1, max_length=200)


class LogResponse(BaseModel):
    success: bool
    logged: bool = False
    error: Optional[str] = None
