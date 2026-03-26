# Multi-stage Dockerfile for Python FastAPI backend

# Stage 1: Build dependencies
FROM python:3.12-slim AS builder

WORKDIR /app

# Only gcc needed for a few sdist packages (feedfinder2, jieba3k, etc.)
# No g++/dev headers needed — lxml/pillow/tiktoken/etc. all have pre-built wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.lock ./
COPY pyproject.toml ./

# Skip resvg (requires full Rust toolchain + libc-dev to build from source).
# Also skip drawio2pptx from the lock file since it depends on resvg.
# Re-install drawio2pptx with --no-deps so it won't pull resvg.
# The app has a fallback PPTX export path if drawio2pptx's resvg features are missing.
RUN grep -v -E 'resvg|drawio2pptx' requirements.lock > requirements-filtered.lock \
    && pip install --no-cache-dir --prefix=/install -r requirements-filtered.lock \
    && pip install --no-cache-dir --prefix=/install --no-deps drawio2pptx==0.0.7

# Stage 2: Production runtime
FROM python:3.12-slim AS runner

WORKDIR /app

# Runtime shared libraries for cairocffi/cairosvg (loaded via ctypes/cffi at runtime)
# Note: libxml2/libxslt not needed — lxml manylinux wheel bundles them statically
RUN apt-get update && apt-get install -y --no-install-recommends \
    libcairo2 \
    libgdk-pixbuf-2.0-0 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    shared-mime-info \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd --system --gid 1001 appuser \
    && useradd --system --uid 1001 --gid appuser appuser

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY --chown=appuser:appuser app/ ./app/
COPY --chown=appuser:appuser pyproject.toml ./

# Copy shape library docs if they exist (from the main repo, mounted at build time)
# These are needed by the get_shape_library tool
COPY --chown=appuser:appuser docs/shape-libraries/ ./docs/shape-libraries/

USER appuser

EXPOSE 8000

ENV PORT=8000
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--timeout-keep-alive", "600"]
