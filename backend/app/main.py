"""
FastAPI application factory.

Creates and configures the FastAPI app including:
- CORS middleware
- Global exception handler
- Lifespan context manager (startup logging)
- Router registration under /api prefix
- /health endpoint
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.middleware.error_handler import unhandled_exception_handler

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Log key configuration on startup; clean up on shutdown."""
    settings = get_settings()
    logger.info("=== next-ai-draw-io Python backend starting ===")
    logger.info("  AI_PROVIDER          : %s", settings.AI_PROVIDER)
    logger.info("  AI_MODEL             : %s", settings.AI_MODEL)
    logger.info("  MAX_OUTPUT_TOKENS    : %d", settings.MAX_OUTPUT_TOKENS)
    logger.info("  MAX_TOOL_STEPS       : %d", settings.MAX_TOOL_STEPS)
    logger.info("  ENABLE_VLM_VALIDATION: %s", settings.ENABLE_VLM_VALIDATION)
    logger.info("  QUOTA_ENABLED        : %s", settings.quota_enabled)
    logger.info("  LANGFUSE_ENABLED     : %s", settings.langfuse_enabled)
    logger.info("  ALLOW_PRIVATE_URLS   : %s", settings.ALLOW_PRIVATE_URLS)
    logger.info("  ALLOWED_ORIGINS      : %s", settings.ALLOWED_ORIGINS)
    logger.info("================================================")
    yield
    logger.info("=== next-ai-draw-io Python backend shutting down ===")


def create_app() -> FastAPI:
    """Construct and return a fully configured FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="next-ai-draw-io API",
        description="Python backend for AI-powered draw.io diagram generation",
        version="0.1.0",
        lifespan=lifespan,
        # Disable default exception handlers so ours take precedence
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # ------------------------------------------------------------------
    # CORS
    # ------------------------------------------------------------------
    origins = settings.allowed_origins_list
    allow_all = origins == ["*"]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins if not allow_all else ["*"],
        allow_credentials=not allow_all,  # credentials not supported with wildcard
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-Id"],
    )

    # ------------------------------------------------------------------
    # Exception handlers
    # ------------------------------------------------------------------
    app.add_exception_handler(Exception, unhandled_exception_handler)  # type: ignore[arg-type]

    # ------------------------------------------------------------------
    # Routers  (imported lazily to avoid circular imports at module level)
    # ------------------------------------------------------------------
    from app.routes import all_routers  # noqa: PLC0415

    for _router in all_routers:
        app.include_router(_router, prefix="/api")

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------
    @app.get("/health", tags=["health"], summary="Service liveness probe")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


# Module-level app instance used by uvicorn / gunicorn
app = create_app()
