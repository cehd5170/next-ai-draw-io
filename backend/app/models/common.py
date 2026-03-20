"""
Shared Pydantic models used across multiple endpoints.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    """Standard error response body returned by the global exception handler."""

    error: str = Field(..., description="Human-readable error summary")
    detail: Optional[str] = Field(
        default=None,
        description="Additional context (only populated in development mode)",
    )


class TokenUsage(BaseModel):
    """
    Cumulative token accounting for a complete request / multi-step agentic run.

    Field names mirror the AI SDK / LiteLLM conventions so they can be forwarded
    to the client without transformation.
    """

    inputTokens: int = Field(default=0, description="Prompt tokens consumed", ge=0)
    outputTokens: int = Field(default=0, description="Completion tokens generated", ge=0)
    cachedInputTokens: int = Field(
        default=0,
        description="Prompt tokens served from the provider cache (reduces cost)",
        ge=0,
    )
    cacheWriteTokens: int = Field(
        default=0,
        description="Prompt tokens written to the provider cache (charged at higher rate)",
        ge=0,
    )

    @property
    def total_tokens(self) -> int:
        """Sum of all token categories."""
        return self.inputTokens + self.outputTokens + self.cachedInputTokens + self.cacheWriteTokens
