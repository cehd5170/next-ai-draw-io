"""
Base dataclasses for the AI provider factory.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ProviderConfig:
    """Static metadata describing a provider's capabilities and environment variables."""

    name: str
    """Internal provider identifier (e.g. 'openai', 'anthropic')."""

    label: str
    """Human-readable display name (e.g. 'OpenAI', 'Anthropic')."""

    default_base_url: str | None
    """Official/default base URL for this provider, or None if not applicable."""

    api_key_env: str | None
    """Name of the environment variable that holds the API key, or None if no key needed."""

    base_url_env: str | None
    """Name of the environment variable that overrides the base URL, or None."""

    supports_vision: bool
    """Whether the provider's models generally support image/vision input."""

    supports_caching: bool
    """Whether the provider supports prompt caching (e.g. Anthropic, Bedrock/Claude)."""

    single_system_message: bool = False
    """
    Some providers (MiniMax, GLM, Qwen, Kimi, Qiniu) only accept a single
    system message at the top of the conversation.  When True, callers should
    merge / deduplicate system messages before sending.
    """


@dataclass
class ModelConfig:
    """
    Resolved configuration used to make an LLM call via litellm.

    The *model_id* field contains the fully-qualified litellm model string,
    e.g. ``"openai/gpt-4o"``, ``"bedrock/anthropic.claude-sonnet-4-5-20250929-v1:0"``.
    """

    provider: str
    """Normalised provider name (matches PROVIDER_REGISTRY keys)."""

    model_id: str
    """litellm-format model string, e.g. 'openai/gpt-4o' or 'gemini/gemini-2.5-pro'."""

    api_key: str | None
    """Resolved API key to pass to litellm, or None when auth is implicit (IAM, etc.)."""

    base_url: str | None
    """Resolved base URL override, or None to use the litellm / provider default."""

    extra_params: dict = field(default_factory=dict)
    """
    Provider-specific litellm call parameters, e.g.:
    - reasoning_effort / reasoning_summary  (OpenAI o-series)
    - thinking  (Anthropic extended thinking)
    - thinking_config  (Google Gemini 2.5)
    - reasoning_config  (Bedrock)
    - think  (Ollama)
    """
