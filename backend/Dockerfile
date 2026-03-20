# Multi-stage Dockerfile for Python FastAPI backend

# Stage 1: Build dependencies
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build deps for lxml, cairosvg, Pillow
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libxml2-dev \
    libxslt1-dev \
    libcairo2-dev \
    libffi-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Copy lockfile first (changes rarely) for layer caching, then project metadata
COPY requirements.lock ./
COPY pyproject.toml ./
RUN pip install --no-cache-dir --prefix=/install -r requirements.lock

# Stage 2: Production runtime
FROM python:3.12-slim AS runner

WORKDIR /app

# Install runtime libraries only (no compilers)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxml2 \
    libxslt1.1 \
    libcairo2 \
    libgdk-pixbuf2.0-0 \
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

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
