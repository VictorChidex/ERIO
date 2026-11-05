"""Structured logs and traces for every ERIO service (spec section 10).

Logs are one JSON object per line on stdout, so any collector (CloudWatch,
Loki) can index them. Each line carries the service name and whatever
context is active: ``request_id`` in the API, ``crawl_run_id``, ``board_id``
and ``source`` in the crawler, plus the OpenTelemetry trace and span IDs.

Traces go to an OpenTelemetry collector over OTLP/HTTP when
``ERIO_OTEL_ENDPOINT`` is set (locally, the "obs" compose profile runs
Jaeger); otherwise tracing is off and costs nothing.
"""

import json
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from opentelemetry import trace

from erio_core.settings import get_settings

_context: ContextVar[dict[str, Any]] = ContextVar("erio_log_context", default={})  # noqa: B039

# Attributes every LogRecord has; anything else passed in ``extra`` is logged.
_STANDARD = set(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


@contextmanager
def log_context(**values: Any) -> Iterator[None]:
    """Add fields to every log line written inside this block."""
    token = _context.set(_context.get() | values)
    try:
        yield
    finally:
        _context.reset(token)


def bind(**values: Any) -> None:
    """Add fields for the rest of the current request or task."""
    _context.set(_context.get() | values)


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str):
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        line: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "service": self.service,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        line |= _context.get()
        line |= {k: v for k, v in vars(record).items() if k not in _STANDARD}
        span = trace.get_current_span().get_span_context()
        if span.is_valid:
            line["trace_id"] = format(span.trace_id, "032x")
            line["span_id"] = format(span.span_id, "016x")
        if record.exc_info:
            line["exc"] = self.formatException(record.exc_info)
        return json.dumps(line, default=str, ensure_ascii=False)


def configure_logging(service: str) -> None:
    """JSON lines on stdout for the whole process (``ERIO_LOG_FORMAT=text`` for humans)."""
    settings = get_settings()
    handler = logging.StreamHandler(sys.stdout)
    if settings.log_format == "json":
        handler.setFormatter(JsonFormatter(service))
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(settings.log_level.upper())
    # Uvicorn and Celery add their own handlers; send everything through ours.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "celery"):
        logging.getLogger(name).handlers[:] = []
        logging.getLogger(name).propagate = True
    # One line per HTTP call to OpenSearch or a job board is noise; traces have them.
    for name in ("opensearch", "httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


def setup_tracing(service: str) -> bool:
    """Send traces to the configured OTLP endpoint; returns False when tracing is off."""
    endpoint = get_settings().otel_endpoint
    if not endpoint:
        return False
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(resource=Resource.create({"service.name": f"erio-{service}"}))
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint.rstrip('/')}/v1/traces"))
    )
    trace.set_tracer_provider(provider)
    return True
