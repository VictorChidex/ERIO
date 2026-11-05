# One image for every Python service (API, worker, MCP). Compose picks the command.
# Holds code and dependencies only; configuration arrives as ERIO_* addresses
# at runtime and no credential is ever baked in (decision D-08).

FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.9.17 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies first, so code changes do not reinstall them.
COPY pyproject.toml uv.lock .python-version ./
COPY packages/core/pyproject.toml packages/core/
COPY services/api/pyproject.toml services/api/
COPY services/ingest/pyproject.toml services/ingest/
COPY services/mcp/pyproject.toml services/mcp/
# The uv cache lives in a build cache mount, never in the image.
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-workspace

COPY packages/core packages/core
COPY services/api services/api
COPY services/ingest services/ingest
COPY services/mcp services/mcp
# Labeled sets for the nightly AI evaluation (erio_ingest.ai_eval).
COPY fixtures/labeled fixtures/labeled
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-editable

RUN useradd --create-home --uid 10001 erio
USER erio

EXPOSE 8000
# The API: WEB_CONCURRENCY worker processes (default 1). With several, metrics
# are shared through PROMETHEUS_MULTIPROC_DIR, emptied at each start.
ENV PROMETHEUS_MULTIPROC_DIR=/tmp/erio-metrics
CMD ["sh", "-c", "rm -rf \"$PROMETHEUS_MULTIPROC_DIR\" && mkdir -p \"$PROMETHEUS_MULTIPROC_DIR\" && exec uvicorn erio_api.main:app --host 0.0.0.0 --port 8000"]
