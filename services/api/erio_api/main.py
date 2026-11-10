"""FastAPI application. Run locally with ``uvicorn erio_api.main:app``."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from opensearchpy.exceptions import OpenSearchException

from erio_api import errors, telemetry
from erio_api.health import Check, default_checks, run_checks
from erio_api.routes import changes, insights, jobs, live, meta
from erio_core import __version__
from erio_core.observability import configure_logging
from erio_core.search.index import client, ensure_alias
from erio_core.settings import get_settings

configure_logging("api")
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # A fresh stack has no jobs index until the indexer's first run; create an
    # empty one so searches answer with no results instead of an error.
    try:
        ensure_alias(client(), get_settings().search_alias)
    except OpenSearchException:
        log.warning("search index not reachable at startup; the indexer will create it")
    yield


app = FastAPI(
    lifespan=lifespan,
    title="ERIO API",
    version=__version__,
    description="Real-time job index: every job from applicant tracking systems, in every country.",
    openapi_url="/v1/openapi.json",
    docs_url="/v1/docs",
)
# Telemetry first: middleware added later wraps it, so the request ID exists by then.
telemetry.install(app)
errors.install(app)
app.include_router(changes.router)
app.include_router(insights.router)
app.include_router(jobs.router)
app.include_router(live.router)
app.include_router(meta.router)


def get_checks() -> dict[str, Check]:
    return default_checks(get_settings())


@app.get("/v1/health", tags=["health"])
async def health() -> dict[str, str]:
    """Liveness: the process is up and serving requests."""
    return {"status": "ok", "version": __version__}


@app.get("/v1/health/ready", tags=["health"])
async def ready(checks: Annotated[dict[str, Check], Depends(get_checks)]) -> JSONResponse:
    """Readiness: every dependency the API needs is reachable."""
    results = await run_checks(checks)
    healthy = all(results.values())
    body: dict[str, Any] = {"status": "ok" if healthy else "unavailable", "checks": results}
    return JSONResponse(body, status_code=200 if healthy else 503)
