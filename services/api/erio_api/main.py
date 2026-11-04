"""FastAPI application. Run locally with ``uvicorn erio_api.main:app``."""

from typing import Annotated, Any

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse

from erio_api.health import Check, default_checks, run_checks
from erio_core import __version__
from erio_core.settings import get_settings

app = FastAPI(
    title="ERIO API",
    version=__version__,
    openapi_url="/v1/openapi.json",
    docs_url="/v1/docs",
)


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
