# syntax=docker/dockerfile:1.7
# Multi-stage build for the FastAPI service image.
# Phase 1: minimal — no torch/transformers; Phase 2 adds encoder deps.

# ----- Builder stage -----
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

# Install uv
RUN pip install --no-cache-dir uv==0.11.14

WORKDIR /build

# Cache layer: copy lockfile first
COPY pyproject.toml uv.lock README.md ./
COPY app ./app

RUN uv sync --frozen --no-dev

# ----- Runtime stage -----
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# Runtime OS deps for Phase 1 (PDF + image processing)
RUN apt-get update && apt-get install -y --no-install-recommends \
      libjpeg62-turbo \
      libpng16-16 \
      libxml2 \
      libxslt1.1 \
      curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user
RUN useradd --system --create-home --shell /bin/false cti

WORKDIR /app
COPY --from=builder --chown=cti:cti /build/.venv ./.venv
COPY --chown=cti:cti app ./app
COPY --chown=cti:cti pyproject.toml README.md ./

USER cti

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
