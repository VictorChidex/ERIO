from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from erio_api.health import Check
from erio_api.main import app, get_checks


def _fixed(value: bool) -> Check:
    async def check() -> bool:
        return value

    return check


@pytest.fixture
def client() -> Iterator[TestClient]:
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_liveness(client: TestClient) -> None:
    response = client.get("/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ready_when_all_dependencies_answer(client: TestClient) -> None:
    app.dependency_overrides[get_checks] = lambda: {"postgres": _fixed(True), "redis": _fixed(True)}
    response = client.get("/v1/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"postgres": True, "redis": True}}


def test_not_ready_when_any_dependency_fails(client: TestClient) -> None:
    app.dependency_overrides[get_checks] = lambda: {
        "postgres": _fixed(True),
        "redis": _fixed(False),
    }
    response = client.get("/v1/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["redis"] is False


def test_openapi_is_published_under_v1(client: TestClient) -> None:
    response = client.get("/v1/openapi.json")
    assert response.status_code == 200
    assert response.json()["openapi"].startswith("3.1")
