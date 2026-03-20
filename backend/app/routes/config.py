"""
GET /config — return public server configuration to the frontend.

The response tells the client:
- Whether an access code is required
- Rate-limit thresholds (so the UI can show meaningful error messages)
- File-size and file-count limits
- Whether VLM diagram validation is enabled
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.config import Settings
from app.dependencies import get_settings
from app.models.config import ConfigResponse

router = APIRouter()


@router.get("/config", response_model=ConfigResponse)
async def get_config(settings: Settings = Depends(get_settings)) -> ConfigResponse:
    """Return the public server configuration."""
    return ConfigResponse(
        accessCodeRequired=bool(settings.ACCESS_CODE_LIST),
        dailyRequestLimit=settings.DAILY_REQUEST_LIMIT,
        dailyTokenLimit=settings.DAILY_TOKEN_LIMIT,
        tpmLimit=settings.TPM_LIMIT,
        maxFileSize=settings.MAX_FILE_SIZE_BYTES,
        maxFiles=settings.MAX_FILES_PER_MESSAGE,
        maxImageSize=settings.MAX_IMAGE_SIZE_BYTES,
        enableVlmValidation=settings.ENABLE_VLM_VALIDATION,
    )
