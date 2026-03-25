"""
Application configuration via Pydantic Settings.

All previously hardcoded limits and toggles are surfaced as environment
variables so operators can tune behaviour without touching source code.
Every field maps 1-to-1 with the corresponding env var name (uppercase).
"""

from __future__ import annotations

import logging
from functools import cached_property, lru_cache
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """
    Central configuration for the Python backend.

    Environment variables are read at startup.  Use get_settings() to
    obtain the singleton (cached) instance throughout the application.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,  # env var names are uppercase
        extra="ignore",  # silently ignore unknown env vars
    )

    # ------------------------------------------------------------------
    # AI Provider
    # ------------------------------------------------------------------
    AI_PROVIDER: str = Field(
        default="bedrock",
        description="Which LLM provider to use (bedrock, openai, anthropic, google, etc.)",
    )
    AI_MODEL: str = Field(
        default="global.anthropic.claude-sonnet-4-5-20250929-v1:0",
        description="Model identifier for the chosen provider",
    )
    TEMPERATURE: Optional[float] = Field(
        default=None,
        description="Sampling temperature. Leave unset for reasoning models.",
    )

    # ------------------------------------------------------------------
    # File upload limits
    # ------------------------------------------------------------------
    MAX_FILE_SIZE_BYTES: int = Field(
        default=2 * 1024 * 1024,  # 2 MB
        description="Maximum size (bytes) of a single uploaded file",
    )
    MAX_FILES_PER_MESSAGE: int = Field(
        default=5,
        description="Maximum number of files allowed in a single message",
    )
    MAX_IMAGE_SIZE_BYTES: int = Field(
        default=2 * 1024 * 1024,  # 2 MB
        description="Maximum size (bytes) of a single uploaded image",
    )

    # ------------------------------------------------------------------
    # URL / content extraction
    # ------------------------------------------------------------------
    MAX_CONTENT_LENGTH: int = Field(
        default=150_000,
        description="Maximum character count for extracted URL/PDF content",
    )
    EXTRACT_TIMEOUT_SECONDS: float = Field(
        default=15.0,
        description="HTTP timeout (seconds) when fetching external URLs",
    )

    # ------------------------------------------------------------------
    # LLM generation
    # ------------------------------------------------------------------
    MAX_OUTPUT_TOKENS: int = Field(
        default=16_384,
        description="Maximum tokens the LLM may generate per response",
    )
    MAX_TOOL_STEPS: int = Field(
        default=8,
        description="Maximum number of tool-call / agentic steps per request",
    )
    ENABLE_HISTORY_XML_REPLACE: bool = Field(
        default=False,
        description="Replace historical tool-call XML with placeholders to save tokens",
    )

    # ------------------------------------------------------------------
    # VLM validation
    # ------------------------------------------------------------------
    VALIDATION_MODEL: Optional[str] = Field(
        default=None,
        description="Model ID to use for VLM diagram validation (falls back to AI_MODEL if unset)",
    )
    ENABLE_VLM_VALIDATION: bool = Field(
        default=True,
        description="Enable Vision-Language Model post-generation diagram validation",
    )
    VALIDATION_TIMEOUT_SECONDS: float = Field(
        default=10.0,
        description="Timeout (seconds) for the validation VLM call",
    )
    VALIDATION_MAX_OUTPUT_TOKENS: int = Field(
        default=1024,
        description="Maximum tokens the validation model may generate",
    )
    MAX_VALIDATION_RETRIES: int = Field(
        default=3,
        description="How many times to retry a failed validation before giving up",
    )

    # ------------------------------------------------------------------
    # Authentication / access control
    # ------------------------------------------------------------------
    ACCESS_CODE_LIST: Optional[str] = Field(
        default=None,
        description="Comma-separated list of valid access codes (disabled when unset)",
    )

    @cached_property
    def access_codes(self) -> list[str]:
        """Return the parsed, stripped list of valid access codes (cached)."""
        if not self.ACCESS_CODE_LIST:
            return []
        return [c.strip() for c in self.ACCESS_CODE_LIST.split(",") if c.strip()]

    # ------------------------------------------------------------------
    # Quota / DynamoDB
    # ------------------------------------------------------------------
    DYNAMODB_QUOTA_TABLE: Optional[str] = Field(
        default=None,
        description="DynamoDB table name for quota tracking (quota disabled when unset)",
    )
    DYNAMODB_REGION: str = Field(
        default="ap-northeast-1",
        description="AWS region for the DynamoDB quota table",
    )
    QUOTA_TIMEZONE: str = Field(
        default="UTC",
        description="Timezone used when resetting daily quota counters",
    )
    DAILY_REQUEST_LIMIT: int = Field(
        default=10,
        description="Maximum requests per user per day (0 = unlimited)",
    )
    DAILY_TOKEN_LIMIT: int = Field(
        default=200_000,
        description="Maximum tokens consumed per user per day (0 = unlimited)",
    )
    TPM_LIMIT: int = Field(
        default=20_000,
        description="Tokens-per-minute rate limit per user (0 = unlimited)",
    )

    @property
    def quota_enabled(self) -> bool:
        """Return True only when a DynamoDB table is configured."""
        return bool(self.DYNAMODB_QUOTA_TABLE)

    # ------------------------------------------------------------------
    # Observability / Langfuse
    # ------------------------------------------------------------------
    LANGFUSE_PUBLIC_KEY: Optional[str] = Field(
        default=None,
        description="Langfuse public key (telemetry disabled when unset)",
    )
    LANGFUSE_SECRET_KEY: Optional[str] = Field(
        default=None,
        description="Langfuse secret key",
    )
    LANGFUSE_BASEURL: Optional[str] = Field(
        default=None,
        description="Langfuse ingestion endpoint (e.g. https://cloud.langfuse.com)",
    )

    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.LANGFUSE_PUBLIC_KEY and self.LANGFUSE_SECRET_KEY)

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------
    DIAGRAM_EXPORT_TIMEOUT_SECONDS: float = Field(
        default=10.0,
        description="Timeout (seconds) for diagram export operations (PPTX, PNG, etc.)",
    )
    PNG_CAPTURE_DELAY_MS: int = Field(
        default=100,
        description="Milliseconds to wait after draw.io renders before capturing PNG",
    )

    # ------------------------------------------------------------------
    # OpenAI
    # ------------------------------------------------------------------
    OPENAI_API_KEY: Optional[str] = Field(default=None)
    OPENAI_BASE_URL: Optional[str] = Field(
        default=None,
        description="Custom OpenAI-compatible endpoint",
    )
    OPENAI_ORGANIZATION: Optional[str] = Field(default=None)
    OPENAI_PROJECT: Optional[str] = Field(default=None)
    OPENAI_REASONING_EFFORT: Optional[str] = Field(
        default=None,
        description="Reasoning effort for o1/o3 models (minimal/low/medium/high)",
    )
    OPENAI_REASONING_SUMMARY: Optional[str] = Field(
        default=None,
        description="Reasoning summary verbosity (none/brief/detailed)",
    )

    # ------------------------------------------------------------------
    # Anthropic
    # ------------------------------------------------------------------
    ANTHROPIC_API_KEY: Optional[str] = Field(default=None)
    ANTHROPIC_BASE_URL: Optional[str] = Field(default=None)
    ANTHROPIC_THINKING_TYPE: Optional[str] = Field(
        default=None,
        description="Extended thinking mode ('enabled')",
    )
    ANTHROPIC_THINKING_BUDGET_TOKENS: Optional[int] = Field(
        default=None,
        description="Token budget for Anthropic extended thinking",
    )

    # ------------------------------------------------------------------
    # Google Generative AI
    # ------------------------------------------------------------------
    GOOGLE_GENERATIVE_AI_API_KEY: Optional[str] = Field(default=None)
    GOOGLE_BASE_URL: Optional[str] = Field(default=None)
    GOOGLE_CANDIDATE_COUNT: Optional[int] = Field(default=None)
    GOOGLE_TOP_K: Optional[int] = Field(default=None)
    GOOGLE_TOP_P: Optional[float] = Field(default=None)
    GOOGLE_THINKING_BUDGET: Optional[int] = Field(
        default=None,
        description="Gemini 2.5 thinking budget (tokens)",
    )
    GOOGLE_THINKING_LEVEL: Optional[str] = Field(
        default=None,
        description="Gemini 3 thinking level (low/high)",
    )

    # ------------------------------------------------------------------
    # Google Vertex AI
    # ------------------------------------------------------------------
    GOOGLE_VERTEX_API_KEY: Optional[str] = Field(
        default=None,
        description="Vertex AI Express Mode API key",
    )
    GOOGLE_VERTEX_BASE_URL: Optional[str] = Field(default=None)
    GOOGLE_VERTEX_THINKING_BUDGET: Optional[int] = Field(default=None)
    GOOGLE_VERTEX_THINKING_LEVEL: Optional[str] = Field(default=None)

    # ------------------------------------------------------------------
    # AWS / Bedrock
    # ------------------------------------------------------------------
    AWS_ACCESS_KEY_ID: Optional[str] = Field(default=None)
    AWS_SECRET_ACCESS_KEY: Optional[str] = Field(default=None)
    AWS_REGION: str = Field(
        default="us-east-1",
        description="Default AWS region for Bedrock calls",
    )
    BEDROCK_REASONING_BUDGET_TOKENS: Optional[int] = Field(
        default=None,
        description="Claude reasoning budget on Bedrock (1024-64000)",
    )
    BEDROCK_REASONING_EFFORT: Optional[str] = Field(
        default=None,
        description="Nova reasoning effort (low/medium/high)",
    )

    # ------------------------------------------------------------------
    # Azure OpenAI
    # ------------------------------------------------------------------
    AZURE_RESOURCE_NAME: Optional[str] = Field(default=None)
    AZURE_API_KEY: Optional[str] = Field(default=None)
    AZURE_BASE_URL: Optional[str] = Field(default=None)
    AZURE_REASONING_EFFORT: Optional[str] = Field(default=None)
    AZURE_REASONING_SUMMARY: Optional[str] = Field(default=None)

    # ------------------------------------------------------------------
    # Ollama
    # ------------------------------------------------------------------
    OLLAMA_BASE_URL: Optional[str] = Field(default=None)
    OLLAMA_API_KEY: Optional[str] = Field(default=None)
    OLLAMA_ENABLE_THINKING: bool = Field(default=False)

    # ------------------------------------------------------------------
    # OpenRouter
    # ------------------------------------------------------------------
    OPENROUTER_API_KEY: Optional[str] = Field(default=None)
    OPENROUTER_BASE_URL: Optional[str] = Field(default=None)

    # ------------------------------------------------------------------
    # DeepSeek
    # ------------------------------------------------------------------
    DEEPSEEK_API_KEY: Optional[str] = Field(default=None)
    DEEPSEEK_BASE_URL: Optional[str] = Field(default=None)

    # ------------------------------------------------------------------
    # SiliconFlow
    # ------------------------------------------------------------------
    SILICONFLOW_API_KEY: Optional[str] = Field(default=None)
    SILICONFLOW_BASE_URL: Optional[str] = Field(default=None)

    # ------------------------------------------------------------------
    # SGLang
    # ------------------------------------------------------------------
    SGLANG_API_KEY: Optional[str] = Field(default=None)
    SGLANG_BASE_URL: Optional[str] = Field(default=None)

    # ------------------------------------------------------------------
    # ModelScope
    # ------------------------------------------------------------------
    MODELSCOPE_API_KEY: Optional[str] = Field(default=None)
    MODELSCOPE_BASE_URL: Optional[str] = Field(default=None)

    # ------------------------------------------------------------------
    # ByteDance Doubao
    # ------------------------------------------------------------------
    DOUBAO_API_KEY: Optional[str] = Field(default=None)
    DOUBAO_BASE_URL: Optional[str] = Field(default=None)

    # ------------------------------------------------------------------
    # Vercel AI Gateway
    # ------------------------------------------------------------------
    AI_GATEWAY_API_KEY: Optional[str] = Field(default=None)
    AI_GATEWAY_BASE_URL: Optional[str] = Field(default=None)

    # ------------------------------------------------------------------
    # MiniMax
    # ------------------------------------------------------------------
    MINIMAX_API_KEY: Optional[str] = Field(default=None)
    MINIMAX_BASE_URL: Optional[str] = Field(default=None)

    # ------------------------------------------------------------------
    # GLM (Zhipu AI)
    # ------------------------------------------------------------------
    GLM_API_KEY: Optional[str] = Field(default=None)
    GLM_BASE_URL: Optional[str] = Field(default=None)

    # ------------------------------------------------------------------
    # Qwen (Alibaba)
    # ------------------------------------------------------------------
    QWEN_API_KEY: Optional[str] = Field(default=None)
    QWEN_BASE_URL: Optional[str] = Field(default=None)

    # ------------------------------------------------------------------
    # Kimi (Moonshot)
    # ------------------------------------------------------------------
    KIMI_API_KEY: Optional[str] = Field(default=None)
    KIMI_BASE_URL: Optional[str] = Field(default=None)

    # ------------------------------------------------------------------
    # Qiniu
    # ------------------------------------------------------------------
    QINIU_API_KEY: Optional[str] = Field(default=None)
    QINIU_BASE_URL: Optional[str] = Field(default=None)

    # ------------------------------------------------------------------
    # Security
    # ------------------------------------------------------------------
    ALLOW_PRIVATE_URLS: bool = Field(
        default=False,
        description=(
            "Allow requests to private/internal URLs. "
            "Default False (secure) — set True only for reverse-proxy setups "
            "where the backend needs to reach internal services."
        ),
    )

    # ------------------------------------------------------------------
    # Server / CORS
    # ------------------------------------------------------------------
    ALLOWED_ORIGINS: str = Field(
        default="*",
        description="Comma-separated list of allowed CORS origins, or '*' for all",
    )

    @property
    def allowed_origins_list(self) -> list[str]:
        """Return parsed list of allowed origins."""
        if self.ALLOWED_ORIGINS.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]

    AI_MODELS_CONFIG_PATH: Optional[str] = Field(
        default=None,
        description="Path to the JSON file containing server-provided model definitions",
    )

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------
    @field_validator("TEMPERATURE", mode="before")
    @classmethod
    def _validate_temperature(cls, v: object) -> Optional[float]:
        if v is None or v == "":
            return None
        val = float(v)  # type: ignore[arg-type]
        if not (0.0 <= val <= 2.0):
            raise ValueError("TEMPERATURE must be between 0.0 and 2.0")
        return val

    @field_validator("MAX_FILE_SIZE_BYTES", "MAX_IMAGE_SIZE_BYTES", mode="before")
    @classmethod
    def _positive_int(cls, v: object) -> int:
        val = int(v)  # type: ignore[arg-type]
        if val <= 0:
            raise ValueError("Value must be a positive integer")
        return val


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the application-wide Settings singleton (cached after first call)."""
    settings = Settings()
    logger.info(
        "Settings loaded: provider=%s model=%s quota_enabled=%s langfuse_enabled=%s",
        settings.AI_PROVIDER,
        settings.AI_MODEL,
        settings.quota_enabled,
        settings.langfuse_enabled,
    )
    return settings
