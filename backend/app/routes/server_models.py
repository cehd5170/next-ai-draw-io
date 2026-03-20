"""
GET /server-models — return the list of server-defined AI models.

Reads ``AI_MODELS_CONFIG_PATH`` (or falls back to ``ai-models.json`` in the
working directory), validates with Pydantic, and returns a flat list of
models suitable for the client model-picker dropdown.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Optional, Union

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.dependencies import get_settings
from app.models.server_models import ServerModelEntry, ServerModelsResponse

router = APIRouter()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic schemas that mirror the TypeScript ServerModelsConfigSchema
# ---------------------------------------------------------------------------


class _ServerProvider(BaseModel):
    name: str
    provider: str
    models: list[str]
    apiKeyEnv: Optional[Union[str, list[str]]] = None
    baseUrlEnv: Optional[str] = None
    default: Optional[bool] = None


class _ServerModelsConfig(BaseModel):
    providers: list[_ServerProvider]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slugify(name: str) -> str:
    """Convert a provider display name to a URL-safe slug."""
    import re
    return re.sub(r"^-|-$", "", re.sub(r"[^a-z0-9]+", "-", name.lower()))


def _provider_label(provider_name: str, provider_id: str) -> str:
    """Human-readable label for a provider block."""
    _LABELS: dict[str, str] = {
        "openai": "OpenAI",
        "anthropic": "Anthropic",
        "google": "Google",
        "vertexai": "Google Vertex AI",
        "azure": "Azure OpenAI",
        "bedrock": "Amazon Bedrock",
        "ollama": "Ollama",
        "openrouter": "OpenRouter",
        "deepseek": "DeepSeek",
        "siliconflow": "SiliconFlow",
        "sglang": "SGLang",
        "gateway": "AI Gateway",
        "edgeone": "EdgeOne Pages",
        "doubao": "Doubao (ByteDance)",
        "modelscope": "ModelScope",
        "glm": "GLM (Zhipu)",
        "qwen": "Qwen (Alibaba)",
        "kimi": "Kimi (Moonshot)",
        "minimax": "MiniMax",
        "qiniu": "Qiniu",
    }
    return provider_name or _LABELS.get(provider_id, provider_id)


async def _load_config(settings: Settings) -> Optional[_ServerModelsConfig]:
    """
    Load and validate the server models JSON configuration.

    Resolution order:
    1. ``AI_MODELS_CONFIG`` env var (raw JSON string — for cloud deployments)
    2. ``AI_MODELS_CONFIG_PATH`` setting / env var (path to a JSON file)
    3. ``ai-models.json`` in the current working directory
    """
    # Priority 1: inline JSON in env var
    env_json = os.environ.get("AI_MODELS_CONFIG", "").strip()
    if env_json:
        try:
            return _ServerModelsConfig.model_validate(json.loads(env_json))
        except (json.JSONDecodeError, ValidationError) as exc:
            logger.error(
                "Failed to parse AI_MODELS_CONFIG env var: %s", exc
            )
            return None

    # Priority 2 / 3: JSON file
    config_path_str: Optional[str] = settings.AI_MODELS_CONFIG_PATH
    config_path = Path(config_path_str) if config_path_str else Path("ai-models.json")

    if not config_path.is_absolute():
        config_path = Path.cwd() / config_path

    if not config_path.exists():
        return None

    try:
        raw = config_path.read_text(encoding="utf-8")
        return _ServerModelsConfig.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError, OSError) as exc:
        logger.error("Failed to load server models config from %s: %s", config_path, exc)
        return None


def _flatten(cfg: _ServerModelsConfig, settings: Settings) -> list[ServerModelEntry]:
    """Flatten the provider config into a list of :class:`ServerModelEntry`."""
    default_provider = os.environ.get("AI_PROVIDER", settings.AI_PROVIDER or "")
    default_model_id = os.environ.get("AI_MODEL", settings.AI_MODEL or "")

    entries: list[ServerModelEntry] = []
    for provider in cfg.providers:
        slug = _slugify(provider.name)
        label = _provider_label(provider.name, provider.provider)

        for i, model_id in enumerate(provider.models):
            synthetic_id = f"server:{slug}:{model_id}"

            # Determine whether this model is the server default
            is_default = (
                (provider.default is True and i == 0)
                or (
                    bool(default_model_id)
                    and model_id == default_model_id
                    and (not default_provider or default_provider == provider.provider)
                )
            )

            entries.append(
                ServerModelEntry(
                    id=synthetic_id,
                    modelId=model_id,
                    provider=provider.provider,
                    providerLabel=label,
                    isDefault=is_default,
                    apiKeyEnv=provider.apiKeyEnv,
                    baseUrlEnv=provider.baseUrlEnv,
                )
            )

    return entries


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.get("/server-models", response_model=ServerModelsResponse)
async def get_server_models(
    settings: Settings = Depends(get_settings),
) -> ServerModelsResponse:
    """
    Return server-configured AI models for the client model picker.

    Returns an empty list when no config file is found — the client falls
    back to user-configured models in that case.
    """
    cfg = await _load_config(settings)
    if cfg is None:
        return ServerModelsResponse(models=[], hasConfig=False)

    models = _flatten(cfg, settings)
    return ServerModelsResponse(models=models, hasConfig=len(models) > 0)
