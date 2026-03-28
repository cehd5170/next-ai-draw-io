"""
POST /validate-model — test AI provider credentials.

Accepts a provider configuration, makes a minimal lightweight completion
("Say 'OK'", max 20 tokens) to verify that the credentials are valid, and
returns ``{valid, responseTime}`` or ``{valid: false, error}``.

Security
--------
- SSRF protection is applied to any ``baseUrl`` supplied by the caller.
- AWS credentials never leave the server; only standard key/secret patterns
  are accepted.
"""

from __future__ import annotations

import logging
import time

import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from openai import AsyncOpenAI

from app.config import Settings
from app.dependencies import get_settings
from app.models.validate_model import ValidateModelRequest, ValidateModelResponse
from app.services.ssrf_protection import is_private_url

router = APIRouter()
logger = logging.getLogger(__name__)

# Providers that do not require a traditional API key
_KEYLESS_PROVIDERS = {"ollama", "edgeone", "sglang", "bedrock"}

# Providers that require AWS credentials rather than an API key
_AWS_PROVIDERS = {"bedrock"}

# Providers that require Vertex AI credentials
_VERTEX_PROVIDERS = {"vertexai"}

# Providers we validate through the official OpenAI SDK path.
_OPENAI_SDK_PROVIDERS = {"openai", "openrouter"}


@router.post("/validate-model", response_model=ValidateModelResponse)
async def validate_model(
    body: ValidateModelRequest,
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """
    Attempt a trivial LLM completion to validate provider credentials.

    Returns HTTP 200 in all cases so the client can always read the JSON
    response body, matching the TypeScript route's behaviour.
    """
    provider = (body.provider or "").strip().lower()
    model_id = (body.modelId or "").strip()

    # ------------------------------------------------------------------
    # Basic validation
    # ------------------------------------------------------------------
    if not provider or not model_id:
        return JSONResponse(
            content=ValidateModelResponse(
                valid=False, error="Provider and model ID are required"
            ).model_dump()
        )

    # ------------------------------------------------------------------
    # SSRF protection on custom base URL
    # ------------------------------------------------------------------
    if body.baseUrl and not settings.ALLOW_PRIVATE_URLS:
        if is_private_url(body.baseUrl):
            return JSONResponse(
                content=ValidateModelResponse(
                    valid=False, error="Invalid base URL"
                ).model_dump()
            )

    # ------------------------------------------------------------------
    # Provider-specific credential checks
    # ------------------------------------------------------------------
    if provider in _AWS_PROVIDERS:
        if not (body.awsAccessKeyId and body.awsSecretAccessKey and body.awsRegion):
            return JSONResponse(
                content=ValidateModelResponse(
                    valid=False,
                    error=(
                        "AWS credentials (Access Key ID, Secret Access Key, Region) "
                        "are required"
                    ),
                ).model_dump()
            )

    elif provider in _VERTEX_PROVIDERS:
        if not body.vertexApiKey:
            return JSONResponse(
                content=ValidateModelResponse(
                    valid=False,
                    error="Vertex AI API key is required for Express Mode",
                ).model_dump()
            )

    elif provider not in _KEYLESS_PROVIDERS and not body.apiKey:
        return JSONResponse(
            content=ValidateModelResponse(
                valid=False, error="API key is required"
            ).model_dump()
        )

    # ------------------------------------------------------------------
    # Attempt the lightweight completion via litellm
    # ------------------------------------------------------------------
    try:
        return await _test_completion(body, provider, model_id, settings)
    except Exception as exc:  # noqa: BLE001
        logger.error("[validate-model] Unexpected error: %s", exc, exc_info=True)
        return JSONResponse(
            content=ValidateModelResponse(
                valid=False, error="Validation failed due to an unexpected error"
            ).model_dump()
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _test_completion(
    body: ValidateModelRequest,
    provider: str,
    model_id: str,
    settings: Settings,
) -> JSONResponse:
    """Make a minimal completion and return a validated response."""
    start = time.monotonic()

    try:
        if provider in _OPENAI_SDK_PROVIDERS:
            client = AsyncOpenAI(
                **_build_openai_client_kwargs(body, provider, settings)
            )
            await client.chat.completions.create(
                **_build_openai_sdk_request(model_id)
            )
        else:
            try:
                import litellm  # type: ignore[import]
            except ImportError:
                return JSONResponse(
                    content=ValidateModelResponse(
                        valid=False,
                        error="litellm is not installed on the server",
                    ).model_dump()
                )

            await litellm.acompletion(  # type: ignore[attr-defined]
                messages=[{"role": "user", "content": "Say 'OK'"}],
                max_tokens=20,
                **_build_litellm_kwargs(body, provider, model_id, settings),
            )

        response_time_ms = int((time.monotonic() - start) * 1000)
        return JSONResponse(
            content=ValidateModelResponse(
                valid=True, responseTime=response_time_ms
            ).model_dump()
        )

    except Exception as exc:  # noqa: BLE001
        error_msg = _classify_error(exc)
        logger.info("[validate-model] Validation failed (%s): %s", provider, error_msg)
        return JSONResponse(
            content=ValidateModelResponse(valid=False, error=error_msg).model_dump()
        )


def _build_openai_client_kwargs(
    body: ValidateModelRequest,
    provider: str,
    settings: Settings,
) -> dict:
    """Assemble ``AsyncOpenAI(...)`` keyword arguments."""
    kwargs: dict = {}
    if body.apiKey:
        kwargs["api_key"] = body.apiKey

    resolved_base_url = _resolve_provider_base_url(body, provider, settings)
    if resolved_base_url:
        kwargs["base_url"] = resolved_base_url

    return kwargs


def _build_openai_sdk_request(model_id: str) -> dict:
    """Assemble ``client.chat.completions.create(...)`` keyword arguments."""
    request = {
        "model": model_id,
        "messages": [{"role": "user", "content": "Say 'OK'"}],
    }
    request.update(_openai_token_limit_kwargs(model_id, 20))
    return request


def _build_litellm_kwargs(
    body: ValidateModelRequest,
    provider: str,
    model_id: str,
    settings: Settings,
) -> dict:
    """Assemble the litellm.acompletion keyword arguments."""
    # Determine litellm model string
    from app.providers.helpers import get_litellm_model_string

    litellm_model = get_litellm_model_string(provider, model_id)

    kwargs: dict = {"model": litellm_model}

    if body.apiKey:
        kwargs["api_key"] = body.apiKey

    # AWS Bedrock
    if provider == "bedrock":
        kwargs["aws_access_key_id"] = body.awsAccessKeyId
        kwargs["aws_secret_access_key"] = body.awsSecretAccessKey
        kwargs["aws_region_name"] = body.awsRegion

    # Vertex AI
    elif provider == "vertexai" and body.vertexApiKey:
        kwargs["vertex_ai_api_key"] = body.vertexApiKey

    resolved_base_url = _resolve_provider_base_url(body, provider, settings)
    if resolved_base_url:
        kwargs["api_base"] = resolved_base_url

    return kwargs


def _resolve_provider_base_url(
    body: ValidateModelRequest,
    provider: str,
    settings: Settings,
) -> str | None:
    """Resolve the effective provider base URL for validate-model requests."""
    if body.baseUrl:
        # EdgeOne sends a relative /api/edgeai URL from the browser. The Python
        # backend cannot resolve that server-side, so only absolute URLs apply here.
        if body.baseUrl.startswith("http"):
            return body.baseUrl
        return None

    default_urls: dict[str, str] = {
        "siliconflow": "https://api.siliconflow.cn/v1",
        "sglang": "http://127.0.0.1:8000/v1",
        "doubao": "https://ark.cn-beijing.volces.com/api/v3",
        "modelscope": "https://api-inference.modelscope.cn/v1",
        "glm": "https://open.bigmodel.cn/api/paas/v4",
        "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "kimi": "https://api.moonshot.cn/v1",
        "qiniu": "https://api.qnaigc.com/v1",
        "minimax": "https://api.minimaxi.com/anthropic/v1",
        "openrouter": "https://openrouter.ai/api/v1",
        "ollama": settings.OLLAMA_BASE_URL or "http://localhost:11434",
        "gateway": settings.AI_GATEWAY_BASE_URL or "https://ai-gateway.vercel.sh/v1/ai",
    }
    return default_urls.get(provider)


def _openai_token_limit_kwargs(model_id: str, limit: int) -> dict[str, int]:
    """Use the correct OpenAI Chat Completions token-limit parameter per model."""
    lower = (model_id or "").lower()
    if any(token in lower for token in ("gpt-5", "o1", "o3", "o4")):
        return {"max_completion_tokens": limit}
    return {"max_tokens": limit}


def _classify_error(exc: Exception) -> str:
    """Map common exception messages to short, user-friendly descriptions."""
    msg = str(exc)
    lower = msg.lower()

    if "401" in msg or "unauthorized" in lower or "invalid api key" in lower:
        return "Invalid API key"
    if "404" in msg or "not found" in lower or "no such model" in lower:
        return "Model not found"
    if "429" in msg or "rate limit" in lower:
        return "Rate limited — try again later"
    if "econnrefused" in lower or "connection refused" in lower:
        return "Cannot connect to server"
    if "timeout" in lower or "timed out" in lower:
        return "Request timed out"
    if "ssl" in lower or "certificate" in lower:
        return "SSL/TLS error — check base URL"

    # Truncate to 120 chars to avoid leaking credentials in the response
    return msg[:120] if msg else "Validation failed"
