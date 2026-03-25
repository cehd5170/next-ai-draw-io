"""
AI provider factory – main entry points consumed by the rest of the backend.

All LLM calls go through litellm, which provides a unified interface across
every provider.  This module is responsible for resolving credentials, base
URLs, and provider-specific litellm parameters, then packaging everything
into a :class:`~app.providers.base.ModelConfig` that the calling code can
pass straight to ``litellm.completion()`` / ``litellm.acompletion()``.

Usage example::

    from app.providers.factory import get_ai_model
    import litellm

    cfg = get_ai_model()
    response = await litellm.acompletion(
        model=cfg.model_id,
        messages=messages,
        api_key=cfg.api_key,
        base_url=cfg.base_url,
        **cfg.extra_params,
    )
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from app.providers.base import ModelConfig
from app.providers.helpers import (
    auto_detect_provider,
    get_litellm_model_string,
    normalize_minimax_base_url,
    resolve_base_url,
)
from app.providers.registry import PROVIDER_REGISTRY

if TYPE_CHECKING:
    from app.config import Settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal helpers – provider-specific extra-param builders
# ---------------------------------------------------------------------------


def _get_setting(settings: "Settings | None", attr: str) -> any:
    """Read an uppercase attribute from the Settings model, or None."""
    if settings is None:
        return None
    return getattr(settings, attr, None)


def _get_int_setting(
    settings: "Settings | None",
    attr: str,
    min_val: int | None = None,
    max_val: int | None = None,
) -> int | None:
    """Read an int setting, validating range.  Returns None when unset."""
    val = _get_setting(settings, attr)
    if val is None:
        return None
    val = int(val)
    if min_val is not None and val < min_val:
        raise ValueError(f"{attr} must be >= {min_val}, got: {val}")
    if max_val is not None and val > max_val:
        raise ValueError(f"{attr} must be <= {max_val}, got: {val}")
    return val


def _build_openai_params(model_id: str, settings: "Settings | None") -> dict:
    """Build OpenAI provider-specific litellm extra params."""
    params: dict = {}

    reasoning_effort = _get_setting(settings, "OPENAI_REASONING_EFFORT")
    reasoning_summary = _get_setting(settings, "OPENAI_REASONING_SUMMARY")

    lower_id = model_id.lower()
    is_reasoning_model = any(
        tok in lower_id for tok in ("o1", "o3", "o4", "gpt-5")
    )

    # Only send reasoning params to reasoning models — non-reasoning
    # models (e.g. gpt-4o) reject unknown parameters.
    if is_reasoning_model:
        if reasoning_effort:
            params["reasoning_effort"] = reasoning_effort
        if reasoning_summary:
            params["reasoning_summary"] = reasoning_summary

    return params


def _build_anthropic_params(settings: "Settings | None") -> dict:
    """Build Anthropic extended-thinking params."""
    params: dict = {}

    budget = _get_int_setting(
        settings, "ANTHROPIC_THINKING_BUDGET_TOKENS", min_val=1024, max_val=64000
    )

    if budget:
        thinking_type = _get_setting(settings, "ANTHROPIC_THINKING_TYPE") or "enabled"
        params["thinking"] = {
            "type": thinking_type,
            "budget_tokens": budget,
        }

    return params


def _build_google_params(
    model_id: str,
    settings: "Settings | None",
    *,
    budget_attr: str = "GOOGLE_THINKING_BUDGET",
    level_attr: str = "GOOGLE_THINKING_LEVEL",
) -> dict:
    """
    Build Google Gemini provider-specific params.

    Also used for Vertex AI by passing different ``budget_attr`` / ``level_attr``.
    """
    params: dict = {}

    lower_id = model_id.lower()
    is_gemini2 = any(tok in lower_id for tok in ("gemini-2", "gemini2"))
    is_gemini25 = any(tok in lower_id for tok in ("2.5", "2-5"))
    is_gemini3 = any(tok in lower_id for tok in ("gemini-3", "gemini3"))

    thinking_budget = _get_int_setting(settings, budget_attr, min_val=1024, max_val=100000)
    thinking_level = _get_setting(settings, level_attr)
    reasoning_effort = _get_setting(settings, "GOOGLE_REASONING_EFFORT")

    if is_gemini2 or is_gemini3:
        thinking_config: dict = {"include_thoughts": True}

        if is_gemini25 and thinking_budget:
            thinking_config["thinking_budget"] = thinking_budget
        elif is_gemini3 and thinking_level:
            thinking_config["thinking_level"] = thinking_level

        params["thinking_config"] = thinking_config
    elif reasoning_effort:
        params["reasoning_effort"] = reasoning_effort

    # Sampling parameters
    candidate_count = _get_int_setting(settings, "GOOGLE_CANDIDATE_COUNT", min_val=1, max_val=8)
    if candidate_count:
        params["candidate_count"] = candidate_count

    top_k = _get_int_setting(settings, "GOOGLE_TOP_K", min_val=1, max_val=100)
    if top_k:
        params["top_k"] = top_k

    top_p = _get_setting(settings, "GOOGLE_TOP_P")
    if top_p is not None:
        top_p = float(top_p)
        if not (0.0 <= top_p <= 1.0):
            raise ValueError(f"GOOGLE_TOP_P must be between 0 and 1, got: {top_p!r}")
        params["top_p"] = top_p

    return params


def _build_bedrock_params(model_id: str, settings: "Settings | None") -> dict:
    """Build Amazon Bedrock reasoning params."""
    params: dict = {}

    budget = _get_int_setting(
        settings, "BEDROCK_REASONING_BUDGET_TOKENS", min_val=1024, max_val=64000
    )
    effort = _get_setting(settings, "BEDROCK_REASONING_EFFORT")

    lower_id = model_id.lower()
    is_claude = "claude" in lower_id or "anthropic" in lower_id
    is_nova = "nova" in lower_id or lower_id.startswith("amazon")

    if (budget or effort) and (is_claude or is_nova):
        reasoning_config: dict = {"type": "enabled"}

        if is_claude and budget:
            reasoning_config["budget_tokens"] = budget
        elif is_nova and effort:
            reasoning_config["max_reasoning_effort"] = effort

        params["reasoning_config"] = reasoning_config

    return params


def _build_ollama_params(settings: "Settings | None") -> dict:
    """Build Ollama-specific params."""
    params: dict = {}

    if _get_setting(settings, "OLLAMA_ENABLE_THINKING"):
        params["think"] = True

    return params


# ---------------------------------------------------------------------------
# Credential / URL resolution helpers (private)
# ---------------------------------------------------------------------------


def _resolve_api_key(config_key_env: str | None, user_api_key: str | None) -> str | None:
    """Return the first available API key: user override > env var."""
    if user_api_key:
        return user_api_key
    if config_key_env:
        return os.environ.get(config_key_env) or None
    return None


def _resolve_provider_base_url(
    provider: str,
    user_api_key: str | None,
    user_base_url: str | None,
) -> str | None:
    """
    Resolve the effective base URL for *provider* using the standard
    security-aware priority chain.
    """
    cfg = PROVIDER_REGISTRY[provider]
    server_base_url = (
        os.environ.get(cfg.base_url_env) if cfg.base_url_env else None
    )
    return resolve_base_url(
        user_api_key=user_api_key,
        user_base_url=user_base_url,
        server_base_url=server_base_url,
        default_base_url=cfg.default_base_url,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_ai_model(
    provider: str | None = None,
    model_id: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    settings: "Settings | None" = None,
    **extra_params,
) -> ModelConfig:
    """
    Build a :class:`~app.providers.base.ModelConfig` for making LLM calls
    via litellm.

    Resolution priority for each dimension:

    1. **Explicit parameters** passed to this function (e.g. from a request
       with user-supplied credentials).
    2. **Settings object** attributes (populated from env vars via
       pydantic-settings).
    3. **Environment variables** read directly (for params not captured by
       the Settings model).
    4. **Provider defaults** from :data:`~app.providers.registry.PROVIDER_REGISTRY`.

    Parameters
    ----------
    provider:
        Provider name, e.g. ``"openai"``, ``"anthropic"``, ``"bedrock"``.
        If *None*, falls back to ``AI_PROVIDER`` env var, then auto-detection.
    model_id:
        Model identifier as understood by the provider, e.g. ``"gpt-4o"``.
        Falls back to ``AI_MODEL`` env var.
    api_key:
        User-supplied API key (overrides server env-var keys).
    base_url:
        User-supplied base URL override.
    settings:
        Optional :class:`~app.config.Settings` instance.  When provided,
        its attributes are consulted before raw ``os.environ`` reads.
    **extra_params:
        Any additional litellm call parameters (e.g. ``temperature``,
        ``max_tokens``) are merged into the returned ``ModelConfig.extra_params``.

    Raises
    ------
    ValueError
        When required configuration is missing or the provider is unknown.
    """
    # ------------------------------------------------------------------
    # 1.  Resolve model_id
    # ------------------------------------------------------------------
    effective_model_id: str | None = (
        model_id
        or _get_setting(settings, "AI_MODEL")
        or os.environ.get("AI_MODEL")
    )
    if not effective_model_id:
        raise ValueError(
            "No model specified.  Set AI_MODEL env var or pass model_id."
        )

    # ------------------------------------------------------------------
    # 2.  Resolve provider
    # ------------------------------------------------------------------
    effective_provider: str | None = (
        provider
        or _get_setting(settings, "AI_PROVIDER")
        or os.environ.get("AI_PROVIDER")
    )
    if not effective_provider:
        effective_provider = auto_detect_provider()
        if effective_provider:
            logger.info("[AI Provider] Auto-detected provider: %s", effective_provider)

    if not effective_provider:
        raise ValueError(
            "No AI provider configured.  Set AI_PROVIDER env var or configure "
            "exactly one provider's API key so auto-detection can work."
        )

    if effective_provider not in PROVIDER_REGISTRY:
        raise ValueError(
            f"Unknown provider: {effective_provider!r}.  "
            f"Supported: {sorted(PROVIDER_REGISTRY)}"
        )

    cfg = PROVIDER_REGISTRY[effective_provider]
    logger.info(
        "[AI Provider] Initialising %s with model: %s",
        effective_provider,
        effective_model_id,
    )

    # ------------------------------------------------------------------
    # 3.  Resolve API key
    # ------------------------------------------------------------------
    resolved_api_key: str | None = _resolve_api_key(cfg.api_key_env, api_key)

    # Bedrock uses AWS credential chain – no single key variable.
    # We leave api_key=None and let litellm / boto3 handle auth.

    # ------------------------------------------------------------------
    # 4.  Resolve base URL
    # ------------------------------------------------------------------
    resolved_base_url: str | None

    if effective_provider == "minimax":
        raw_url = _resolve_provider_base_url(effective_provider, api_key, base_url)
        if not raw_url:
            raise ValueError(
                "MiniMax base URL could not be resolved.  "
                "Set MINIMAX_BASE_URL or configure a base URL in settings."
            )
        resolved_base_url, _ = normalize_minimax_base_url(raw_url)

    elif effective_provider == "azure":
        resolved_base_url = _resolve_provider_base_url(effective_provider, api_key, base_url)
        # If neither AZURE_BASE_URL nor a user base_url, try constructing from AZURE_RESOURCE_NAME
        if not resolved_base_url:
            resource_name = os.environ.get("AZURE_RESOURCE_NAME")
            if resource_name:
                resolved_base_url = (
                    f"https://{resource_name}.openai.azure.com/openai/v1"
                )

    elif effective_provider == "edgeone":
        # EdgeOne uses a relative path served by the same host
        resolved_base_url = base_url or os.environ.get("EDGEONE_BASE_URL") or "/api/edgeai"

    else:
        resolved_base_url = _resolve_provider_base_url(effective_provider, api_key, base_url)

    # ------------------------------------------------------------------
    # 5.  Build litellm model string
    # ------------------------------------------------------------------
    litellm_model = get_litellm_model_string(effective_provider, effective_model_id)

    # ------------------------------------------------------------------
    # 6.  Build provider-specific extra params
    # ------------------------------------------------------------------
    provider_params: dict = {}

    if effective_provider == "openai" or effective_provider == "azure":
        provider_params.update(_build_openai_params(effective_model_id, settings))

    elif effective_provider == "anthropic":
        provider_params.update(_build_anthropic_params(settings))

    elif effective_provider == "google":
        provider_params.update(_build_google_params(effective_model_id, settings))

    elif effective_provider == "vertexai":
        # Vertex shares Gemini models — reuse Google builder with Vertex env var names.
        provider_params.update(_build_google_params(
            effective_model_id,
            settings,
            budget_attr="GOOGLE_VERTEX_THINKING_BUDGET",
            level_attr="GOOGLE_VERTEX_THINKING_LEVEL",
        ))

    elif effective_provider == "bedrock":
        provider_params.update(_build_bedrock_params(effective_model_id, settings))

    elif effective_provider == "ollama":
        provider_params.update(_build_ollama_params(settings))

    # Merge any caller-supplied overrides last (highest priority)
    merged_params = {**provider_params, **extra_params}

    return ModelConfig(
        provider=effective_provider,
        model_id=litellm_model,
        api_key=resolved_api_key,
        base_url=resolved_base_url,
        extra_params=merged_params,
    )


def get_validation_model(settings: "Settings | None" = None) -> ModelConfig:
    """
    Return a :class:`~app.providers.base.ModelConfig` for VLM diagram
    validation.

    The validation model must support vision / image input.

    Resolution order:
    1. ``VALIDATION_MODEL`` env var
    2. ``AI_MODEL`` env var

    Raises
    ------
    ValueError
        When no model is configured or the resolved model does not support
        image input.
    """
    model_id: str | None = (
        _get_setting(settings, "VALIDATION_MODEL")
        or os.environ.get("VALIDATION_MODEL")
        or _get_setting(settings, "AI_MODEL")
        or os.environ.get("AI_MODEL")
    )

    if not model_id:
        raise ValueError(
            "No validation model configured.  Set VALIDATION_MODEL or AI_MODEL."
        )

    if not supports_image_input(model_id):
        raise ValueError(
            f'Validation requires a vision-capable model.  '
            f'Model "{model_id}" does not support image input.  '
            f'Set VALIDATION_MODEL to a vision-capable model.'
        )

    return get_ai_model(model_id=model_id, settings=settings)


def supports_image_input(model_id: str) -> bool:
    """
    Return ``True`` when *model_id* is expected to accept image/vision input.

    Conservative heuristics (matches the TypeScript implementation):

    * **DeepSeek** text models return ``False``; ``"vision"`` / ``"vl"``
      variants return ``True``.
    * **Qwen** text models return ``False``; ``"vl"`` / ``"qwen3.5-plus"``
      variants return ``True``.
    * **Kimi K2** (but not K2.5) returns ``False``; vision/vl/k2.5 variants
      return ``True``.
    * Everything else (Claude, GPT-4o, Gemini, Nova, …) returns ``True``.
    """
    lower = model_id.lower()
    has_vision_indicator = "vision" in lower or "vl" in lower

    # Kimi K2 text models (K2.5 supports vision)
    if (
        ("kimi-k2" in lower or "kimi_k2" in lower)
        and not has_vision_indicator
        and "2.5" not in lower
        and "k2.5" not in lower
    ):
        return False

    # DeepSeek text models
    if "deepseek" in lower and not has_vision_indicator:
        return False

    # Qwen text models
    if (
        "qwen" in lower
        and not has_vision_indicator
        and "qwen3.5-plus" not in lower
    ):
        return False

    return True


def supports_prompt_caching(model_id: str) -> bool:
    """
    Return ``True`` when *model_id* supports Anthropic-style prompt caching.

    Covers:
    - Direct Anthropic API models (``"claude-*"``)
    - Bedrock cross-region inference prefixes (``"us.anthropic.*"``,
      ``"eu.anthropic.*"``)
    - Any model whose ID contains ``"anthropic"``
    """
    lower = model_id.lower()
    return (
        "claude" in lower
        or "anthropic" in lower
        or lower.startswith("us.anthropic")
        or lower.startswith("eu.anthropic")
    )
