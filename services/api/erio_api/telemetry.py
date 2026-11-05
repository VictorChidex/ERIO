"""Request logs, Prometheus metrics and traces for the API (spec section 10).

Every request writes one JSON log line (method, route, status, time,
request_id) and updates two metrics, labeled by route template so
``/v1/jobs/{canonical_id}`` stays one series. ``/metrics`` answers only
internal networks (D-15), where Prometheus scrapes it; everyone else gets
a 404. Traces are added when an OpenTelemetry collector is configured.
"""

import logging
import os
import time
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
    multiprocess,
)

from erio_api.access import is_internal
from erio_core.observability import bind, setup_tracing

log = logging.getLogger("erio_api.requests")

REQUESTS = Counter("erio_api_requests_total", "API requests", ["method", "route", "status"])
LATENCY = Histogram(
    "erio_api_request_seconds",
    "Time to answer an API request",
    ["route"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.2, 0.3, 0.5, 1.0, 2.5, 5.0),
)
QUIET = ("/v1/health", "/metrics")


def _registry() -> CollectorRegistry:
    """With several worker processes (PROMETHEUS_MULTIPROC_DIR set), add up
    every process's samples; otherwise this process's own."""
    if not os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        return REGISTRY
    registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(registry)  # type: ignore[no-untyped-call]
    return registry


def install(app: FastAPI) -> None:
    """Add before the request-ID middleware, so this one runs inside it."""

    @app.middleware("http")
    async def observe(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        started = time.perf_counter()
        bind(request_id=getattr(request.state, "request_id", None))
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            # API routes give their template; the few plain routes (OpenAPI,
            # docs) have fixed paths. Unknown paths share one label, so
            # random URLs cannot create unlimited series.
            template = getattr(request.scope.get("route"), "path", None)
            route = template or (request.url.path if status != 404 else "unmatched")
            elapsed = time.perf_counter() - started
            REQUESTS.labels(request.method, route, str(status)).inc()
            LATENCY.labels(route).observe(elapsed)
            level = logging.DEBUG if request.url.path.startswith(QUIET) else logging.INFO
            log.log(
                level,
                "request",
                extra={
                    "method": request.method,
                    "route": route,
                    "status": status,
                    "duration_ms": round(elapsed * 1000, 1),
                },
            )

    @app.get("/metrics", include_in_schema=False)
    async def metrics(request: Request) -> Response:
        if not is_internal(request.client.host if request.client else ""):
            return Response(status_code=404)
        return Response(generate_latest(_registry()), media_type=CONTENT_TYPE_LATEST)

    if setup_tracing("api"):
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        FastAPIInstrumentor.instrument_app(app, excluded_urls="v1/health,metrics")
        SQLAlchemyInstrumentor().instrument()
        HTTPXClientInstrumentor().instrument()
