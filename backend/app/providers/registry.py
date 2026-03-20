"""
Registry of all 23 supported AI providers.

Each entry maps a short provider name to a :class:`~app.providers.base.ProviderConfig`
describing its environment variables, default URL, and capability flags.
"""

from __future__ import annotations

from app.providers.base import ProviderConfig

# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

PROVIDER_REGISTRY: dict[str, ProviderConfig] = {
    # ------------------------------------------------------------------
    # 1. OpenAI
    # ------------------------------------------------------------------
    "openai": ProviderConfig(
        name="openai",
        label="OpenAI",
        default_base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
        base_url_env="OPENAI_BASE_URL",
        supports_vision=True,
        supports_caching=False,
        single_system_message=False,
    ),
    # ------------------------------------------------------------------
    # 2. Anthropic
    # ------------------------------------------------------------------
    "anthropic": ProviderConfig(
        name="anthropic",
        label="Anthropic",
        default_base_url="https://api.anthropic.com/v1",
        api_key_env="ANTHROPIC_API_KEY",
        base_url_env="ANTHROPIC_BASE_URL",
        supports_vision=True,
        supports_caching=True,
        single_system_message=False,
    ),
    # ------------------------------------------------------------------
    # 3. Google Generative AI (Gemini)
    # ------------------------------------------------------------------
    "google": ProviderConfig(
        name="google",
        label="Google",
        default_base_url="https://generativelanguage.googleapis.com/v1beta",
        api_key_env="GOOGLE_GENERATIVE_AI_API_KEY",
        base_url_env="GOOGLE_BASE_URL",
        supports_vision=True,
        supports_caching=False,
        single_system_message=False,
    ),
    # ------------------------------------------------------------------
    # 4. Google Vertex AI (Express Mode)
    # ------------------------------------------------------------------
    "vertexai": ProviderConfig(
        name="vertexai",
        label="Google Vertex AI",
        default_base_url=None,
        api_key_env="GOOGLE_VERTEX_API_KEY",
        base_url_env="GOOGLE_VERTEX_BASE_URL",
        supports_vision=True,
        supports_caching=False,
        single_system_message=False,
    ),
    # ------------------------------------------------------------------
    # 5. Azure OpenAI
    # ------------------------------------------------------------------
    "azure": ProviderConfig(
        name="azure",
        label="Azure OpenAI",
        # Default URL is constructed from AZURE_RESOURCE_NAME at runtime if
        # AZURE_BASE_URL is not set.
        default_base_url="https://your-resource.openai.azure.com/openai",
        api_key_env="AZURE_API_KEY",
        base_url_env="AZURE_BASE_URL",
        supports_vision=True,
        supports_caching=False,
        single_system_message=False,
    ),
    # ------------------------------------------------------------------
    # 6. Amazon Bedrock
    #    Uses AWS credentials – no single API-key env var.
    # ------------------------------------------------------------------
    "bedrock": ProviderConfig(
        name="bedrock",
        label="Amazon Bedrock",
        default_base_url=None,
        api_key_env=None,  # Uses AWS_ACCESS_KEY_ID / IAM role
        base_url_env=None,
        supports_vision=True,
        supports_caching=True,  # Supported for Claude models on Bedrock
        single_system_message=False,
    ),
    # ------------------------------------------------------------------
    # 7. Ollama (local)
    # ------------------------------------------------------------------
    "ollama": ProviderConfig(
        name="ollama",
        label="Ollama",
        default_base_url="http://localhost:11434",
        api_key_env="OLLAMA_API_KEY",  # optional – Ollama doesn't require a key
        base_url_env="OLLAMA_BASE_URL",
        supports_vision=False,  # depends on specific model; conservative default
        supports_caching=False,
        single_system_message=False,
    ),
    # ------------------------------------------------------------------
    # 8. OpenRouter
    # ------------------------------------------------------------------
    "openrouter": ProviderConfig(
        name="openrouter",
        label="OpenRouter",
        default_base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
        base_url_env="OPENROUTER_BASE_URL",
        supports_vision=True,
        supports_caching=False,
        single_system_message=False,
    ),
    # ------------------------------------------------------------------
    # 9. DeepSeek
    # ------------------------------------------------------------------
    "deepseek": ProviderConfig(
        name="deepseek",
        label="DeepSeek",
        default_base_url="https://api.deepseek.com/v1",
        api_key_env="DEEPSEEK_API_KEY",
        base_url_env="DEEPSEEK_BASE_URL",
        supports_vision=False,  # text-only by default; VL variants override
        supports_caching=False,
        single_system_message=False,
    ),
    # ------------------------------------------------------------------
    # 10. SiliconFlow
    # ------------------------------------------------------------------
    "siliconflow": ProviderConfig(
        name="siliconflow",
        label="SiliconFlow",
        default_base_url="https://api.siliconflow.cn/v1",
        api_key_env="SILICONFLOW_API_KEY",
        base_url_env="SILICONFLOW_BASE_URL",
        supports_vision=True,
        supports_caching=False,
        single_system_message=False,
    ),
    # ------------------------------------------------------------------
    # 11. SGLang (self-hosted, OpenAI-compatible)
    # ------------------------------------------------------------------
    "sglang": ProviderConfig(
        name="sglang",
        label="SGLang",
        default_base_url="http://127.0.0.1:8000/v1",
        api_key_env="SGLANG_API_KEY",
        base_url_env="SGLANG_BASE_URL",
        supports_vision=True,
        supports_caching=False,
        single_system_message=False,
    ),
    # ------------------------------------------------------------------
    # 12. AI Gateway (Vercel AI Gateway)
    # ------------------------------------------------------------------
    "gateway": ProviderConfig(
        name="gateway",
        label="AI Gateway",
        default_base_url="https://ai-gateway.vercel.sh/v1/ai",
        api_key_env="AI_GATEWAY_API_KEY",
        base_url_env="AI_GATEWAY_BASE_URL",
        supports_vision=True,
        supports_caching=False,
        single_system_message=False,
    ),
    # ------------------------------------------------------------------
    # 13. EdgeOne Pages Edge AI
    # ------------------------------------------------------------------
    "edgeone": ProviderConfig(
        name="edgeone",
        label="EdgeOne Pages",
        default_base_url=None,  # Relative /api/edgeai path
        api_key_env="EDGEONE_API_KEY",
        base_url_env="EDGEONE_BASE_URL",
        supports_vision=False,
        supports_caching=False,
        single_system_message=False,
    ),
    # ------------------------------------------------------------------
    # 14. Doubao (ByteDance Volcengine Ark)
    # ------------------------------------------------------------------
    "doubao": ProviderConfig(
        name="doubao",
        label="Doubao (ByteDance)",
        default_base_url="https://ark.cn-beijing.volces.com/api/v3",
        api_key_env="DOUBAO_API_KEY",
        base_url_env="DOUBAO_BASE_URL",
        supports_vision=True,
        supports_caching=False,
        single_system_message=False,
    ),
    # ------------------------------------------------------------------
    # 15. ModelScope (Alibaba)
    # ------------------------------------------------------------------
    "modelscope": ProviderConfig(
        name="modelscope",
        label="ModelScope",
        default_base_url="https://api-inference.modelscope.cn/v1",
        api_key_env="MODELSCOPE_API_KEY",
        base_url_env="MODELSCOPE_BASE_URL",
        supports_vision=True,
        supports_caching=False,
        single_system_message=False,
    ),
    # ------------------------------------------------------------------
    # 16. GLM / Zhipu AI
    # ------------------------------------------------------------------
    "glm": ProviderConfig(
        name="glm",
        label="GLM (Zhipu)",
        default_base_url="https://open.bigmodel.cn/api/paas/v4",
        api_key_env="GLM_API_KEY",
        base_url_env="GLM_BASE_URL",
        supports_vision=True,
        supports_caching=False,
        single_system_message=True,
    ),
    # ------------------------------------------------------------------
    # 17. Qwen (Alibaba DashScope)
    # ------------------------------------------------------------------
    "qwen": ProviderConfig(
        name="qwen",
        label="Qwen (Alibaba)",
        default_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key_env="QWEN_API_KEY",
        base_url_env="QWEN_BASE_URL",
        supports_vision=False,  # text-only; VL variants override
        supports_caching=False,
        single_system_message=True,
    ),
    # ------------------------------------------------------------------
    # 18. Kimi (Moonshot AI)
    # ------------------------------------------------------------------
    "kimi": ProviderConfig(
        name="kimi",
        label="Kimi (Moonshot)",
        default_base_url="https://api.moonshot.cn/v1",
        api_key_env="KIMI_API_KEY",
        base_url_env="KIMI_BASE_URL",
        supports_vision=False,  # K2 text-only; vision variants override
        supports_caching=False,
        single_system_message=True,
    ),
    # ------------------------------------------------------------------
    # 19. MiniMax
    # ------------------------------------------------------------------
    "minimax": ProviderConfig(
        name="minimax",
        label="MiniMax",
        default_base_url="https://api.minimaxi.com/anthropic",
        api_key_env="MINIMAX_API_KEY",
        base_url_env="MINIMAX_BASE_URL",
        supports_vision=True,
        supports_caching=False,
        single_system_message=True,
    ),
    # ------------------------------------------------------------------
    # 20. Qiniu
    # ------------------------------------------------------------------
    "qiniu": ProviderConfig(
        name="qiniu",
        label="Qiniu",
        default_base_url="https://api.qnaigc.com/v1",
        api_key_env="QINIU_API_KEY",
        base_url_env="QINIU_BASE_URL",
        supports_vision=False,
        supports_caching=False,
        single_system_message=True,
    ),
}

# ---------------------------------------------------------------------------
# Convenience sets / constants
# ---------------------------------------------------------------------------

# Providers that only accept a single system message at the start of a conversation
SINGLE_SYSTEM_PROVIDERS: set[str] = {
    "minimax",
    "glm",
    "qwen",
    "kimi",
    "qiniu",
}

# Providers that use AWS credential chain rather than an API key env var
AWS_CREDENTIAL_PROVIDERS: set[str] = {"bedrock"}

# Providers that need no credentials at all (local / auth-less deployments)
KEYLESS_PROVIDERS: set[str] = {"ollama", "edgeone", "sglang"}
