"""
Request/response schemas for the /validate-model endpoint.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class ValidateModelRequest(BaseModel):
    """Credentials to test against a provider."""

    provider: str
    modelId: str
    apiKey: Optional[str] = None
    baseUrl: Optional[str] = None
    # AWS Bedrock
    awsAccessKeyId: Optional[str] = None
    awsSecretAccessKey: Optional[str] = None
    awsRegion: Optional[str] = None
    # Vertex AI Express Mode
    vertexApiKey: Optional[str] = None


class ValidateModelResponse(BaseModel):
    """Result of a lightweight credential test."""

    valid: bool
    responseTime: Optional[int] = None
    error: Optional[str] = None
