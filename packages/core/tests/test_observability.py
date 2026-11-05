"""JSON log lines with request and crawl context (spec section 10)."""

import json
import logging

import pytest

from erio_core.observability import JsonFormatter, bind, log_context, setup_tracing
from erio_core.settings import get_settings


def line(record: logging.LogRecord) -> dict[str, object]:
    data: dict[str, object] = json.loads(JsonFormatter("worker").format(record))
    return data


def record(message: str, **extra: object) -> logging.LogRecord:
    entry = logging.makeLogRecord({"name": "erio.test", "levelname": "INFO", "msg": message})
    entry.__dict__.update(extra)
    return entry


def test_one_json_object_per_line_with_context_and_extras() -> None:
    with log_context(crawl_run_id=42, source="lever"):
        got = line(record("crawl finished", outcome="ok", postings_seen=12))
    assert got["msg"] == "crawl finished" and got["level"] == "info"
    assert (got["service"], got["logger"]) == ("worker", "erio.test")
    assert (got["crawl_run_id"], got["source"]) == (42, "lever")
    assert (got["outcome"], got["postings_seen"]) == ("ok", 12)
    assert "trace_id" not in got
    # Context ends with its block.
    assert "crawl_run_id" not in line(record("after"))


def test_bind_lasts_for_the_rest_of_the_context() -> None:
    with log_context():
        bind(request_id="abc123")
        assert line(record("x"))["request_id"] == "abc123"


def test_exceptions_are_included() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        entry = record("failed")
        entry.exc_info = sys.exc_info()
    assert "ValueError: boom" in str(line(entry)["exc"])


def test_tracing_is_off_without_a_collector(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "otel_endpoint", None)
    assert setup_tracing("api") is False
