"""API request metrics and logs (spec section 10)."""

import logging

import pytest
from fastapi.testclient import TestClient

from erio_api import telemetry
from erio_api.main import app


def test_metrics_answer_only_internal_networks(monkeypatch: pytest.MonkeyPatch) -> None:
    api = TestClient(app)
    assert api.get("/metrics").status_code == 404

    monkeypatch.setattr(telemetry, "is_internal", lambda address: True)
    api.get("/v1/health")
    api.get("/v1/jobs/not%20an%20id")  # rejected before any database call
    body = api.get("/metrics").text
    assert 'erio_api_requests_total{method="GET",route="/v1/health",status="200"}' in body
    assert 'route="/v1/jobs/{canonical_id}"' in body
    assert "erio_api_request_seconds_bucket" in body


def test_each_request_logs_one_line_with_its_request_id(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="erio_api.requests")
    response = TestClient(app).get("/v1/openapi.json", headers={"X-Request-ID": "req-12345678"})

    [entry] = [r for r in caplog.records if r.name == "erio_api.requests"]
    assert response.headers["X-Request-ID"] == "req-12345678"
    assert (entry.route, entry.status, entry.method) == ("/v1/openapi.json", 200, "GET")  # type: ignore[attr-defined]
    assert entry.duration_ms >= 0  # type: ignore[attr-defined]
