"""
Request/response schemas for the /server-models endpoint.
"""

from __future__ import annotations

from typing import Optional, Union

from pydantic import BaseModel, Field


class ServerModelEntry(BaseModel):
    """A single flattened server-defined model ready for the client dropdown."""

    id: str = Field(description="Synthetic ID: 'server:<slug>:<modelId>'")
    modelId: str
    provider: str
    providerLabel: str
    isDefault: bool = False
    apiKeyEnv: Optional[Union[str, list[str]]] = None
    baseUrlEnv: Optional[str] = None


class ServerModelsResponse(BaseModel):
    """Response from GET /server-models."""

    models: list[ServerModelEntry]
    hasConfig: bool
