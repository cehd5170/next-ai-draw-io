"""
Utility helpers for the AI provider factory.

These are pure functions that do not depend on FastAPI request context or
application state – they can be called from anywhere in the codebase.
"""

from __future__ import annotations

import logging
import os

from app.providers.registry import PROVIDER_REGISTRY, AWS_CREDENTIAL_PROVIDERS, KEYLESS_PROVIDERS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# litellm model-string mappings
# ---------------------------------------------------------------------------

# Providers that map directly to a first-class litellm provider prefix.
# For everything else we fall back to the "openai/" prefix with a custom
# base_url (OpenAI-compatible API).
_LITELLM_PREFIX_MAP: dict[str, str] = {
    "openai": "openai",
    "anthropic": "anthropic",
    "google": "gemini",        # litellm uses "gemini/" for Google GenAI
    "vertexai": "vertex_ai",   # litellm uses "vertex_ai/" for Vertex
    "bedrock": "bedrock",
    "azure": "azure",
    "ollama": "ollama",
    "openrouter": "openrouter",
    "deepseek": "deepseek",
}


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def resolve_base_url(
    user_api_key: str | None,
    user_base_url: str | None,
    server_base_url: str | None,
    default_base_url: str | None = None,
) -> str | None:
    """
    Decide which base URL to use, applying the security rule that a user who
    provides their *own* API key must never have their credentials forwarded
    to a *server-configured* endpoint they did not explicitly opt into.

    Priority when **user supplies their own key**:
        user_base_url  >  default_base_url

    Priority when **no user key** (server key or implicit auth):
        user_base_url  >  server_base_url  >  default_base_url

    Returns ``None`` when no URL can be resolved (litellm will use its own
    built-in default for that provider).
    """
    if user_api_key:
        # User owns the key – only honour the URL they explicitly specified.
        return user_base_url or default_base_url or None

    # No user key – fall back through server config.
    return user_base_url or server_base_url or default_base_url or None


def normalize_minimax_base_url(raw_url: str) -> tuple[str, bool]:
    """
    Normalise a MiniMax base URL and detect which API flavour to use.

    MiniMax exposes two compatible endpoints:

    * **Anthropic-compatible**: ``https://api.minimaxi.com/anthropic/v1``
    * **OpenAI-compatible**:    ``https://api.minimaxi.com/v1``

    The function ensures the URL ends with the correct path suffix and
    returns ``(normalised_url, is_anthropic_compatible)``.

    Examples::

        normalize_minimax_base_url("https://api.minimaxi.com/anthropic")
        # → ("https://api.minimaxi.com/anthropic/v1", True)

        normalize_minimax_base_url("https://api.minimaxi.com/anthropic/v1")
        # → ("https://api.minimaxi.com/anthropic/v1", True)

        normalize_minimax_base_url("https://api.minimaxi.com")
        # → ("https://api.minimaxi.com/v1", False)

        normalize_minimax_base_url("https://api.minimaxi.com/v1")
        # → ("https://api.minimaxi.com/v1", False)
    """
    is_anthropic_compatible = "/anthropic" in raw_url
    base_url = raw_url.rstrip("/")

    if is_anthropic_compatible:
        if not base_url.endswith("/anthropic/v1"):
            if base_url.endswith("/anthropic"):
                base_url = f"{base_url}/v1"
            else:
                base_url = f"{base_url}/anthropic/v1"
    else:
        if not base_url.endswith("/v1"):
            base_url = f"{base_url}/v1"

    return base_url, is_anthropic_compatible


def auto_detect_provider() -> str | None:
    """
    Scan environment variables for configured provider credentials.

    Returns the provider name if *exactly one* provider has its key set,
    otherwise returns ``None``.

    Bedrock is treated specially – it doesn't require an API-key env var but
    does require ``AWS_ACCESS_KEY_ID`` (or an implicit IAM role).  We only
    count Bedrock as "configured" when ``AWS_ACCESS_KEY_ID`` is set, so that
    implicit IAM roles in production don't falsely trigger auto-detection.

    Azure requires either ``AZURE_BASE_URL`` or ``AZURE_RESOURCE_NAME`` in
    addition to ``AZURE_API_KEY`` to be considered fully configured.
    """
    configured: list[str] = []

    for name, config in PROVIDER_REGISTRY.items():
        if name in AWS_CREDENTIAL_PROVIDERS:
            # Bedrock: count if explicit AWS key is set
            if os.environ.get("AWS_ACCESS_KEY_ID"):
                configured.append(name)
            continue

        if name in KEYLESS_PROVIDERS:
            # Ollama / EdgeOne / SGLang: skip – no credential needed
            continue

        key_env = config.api_key_env
        if not key_env:
            continue

        if not os.environ.get(key_env):
            continue

        # Azure also needs a base URL or resource name
        if name == "azure":
            if not os.environ.get("AZURE_BASE_URL") and not os.environ.get(
                "AZURE_RESOURCE_NAME"
            ):
                continue

        configured.append(name)

    if len(configured) == 1:
        return configured[0]

    return None


def get_litellm_model_string(provider: str, model_id: str) -> str:
    """
    Convert a ``(provider, model_id)`` pair into the litellm model string
    that should be passed as the first argument to ``litellm.completion()``.

    litellm format reference:
    - OpenAI:       ``"openai/gpt-4o"``          (or bare ``"gpt-4o"``)
    - Anthropic:    ``"anthropic/claude-sonnet-4-5-20250929"``
    - Google:       ``"gemini/gemini-2.5-pro"``
    - Vertex AI:    ``"vertex_ai/gemini-2.5-pro"``
    - Bedrock:      ``"bedrock/anthropic.claude-sonnet-4-5-20250929-v1:0"``
    - Azure:        ``"azure/<deployment-name>"``
    - Ollama:       ``"ollama/llama3"``
    - OpenRouter:   ``"openrouter/anthropic/claude-sonnet-4-5"``
    - DeepSeek:     ``"deepseek/deepseek-chat"``
    - Others:       ``"openai/<model-id>"`` with custom ``base_url``
    """
    prefix = _LITELLM_PREFIX_MAP.get(provider)
    if prefix:
        return f"{prefix}/{model_id}"

    # OpenAI-compatible providers (SiliconFlow, SGLang, GLM, Qwen, Kimi,
    # MiniMax, Doubao, ModelScope, OpenRouter, Gateway, EdgeOne, Qiniu …)
    # litellm routes them via the openai prefix + a custom base_url.
    return f"openai/{model_id}"
