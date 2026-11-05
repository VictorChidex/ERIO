"""Tokens, tiers and rate limits on real Redis and Postgres."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from erio_api import access
from erio_api.deps import engine as engine_dependency
from erio_api.deps import search_alias as alias_dependency
from erio_api.main import app
from erio_api.tokens import main as tokens_cli
from erio_core.db.models import ApiToken
from erio_core.db.seed import sync_countries, sync_sources

LIMITS = {"internal": 50, "pro": 20, "free": 3, "anonymous": 2}


@pytest.fixture
def setup(
    migrated_engine: Engine, redis_url: str, search_alias: str, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Engine]:
    sync_countries(migrated_engine)
    sync_sources(migrated_engine)
    monkeypatch.setattr(access, "_is_internal", lambda address: address.startswith("172.18."))
    app.dependency_overrides.update(
        {
            engine_dependency: lambda: migrated_engine,
            alias_dependency: lambda: search_alias,
            access.redis_client: lambda: Redis.from_url(redis_url),
            access.limits: lambda: LIMITS,
        }
    )
    try:
        yield migrated_engine
    finally:
        app.dependency_overrides.clear()


def caller(address: str) -> TestClient:
    return TestClient(app, client=(address, 50000))


def make_token(engine: Engine, tier: str = "free") -> tuple[int, str]:
    token, digest = access.new_token()
    with Session(engine) as session, session.begin():
        row = ApiToken(owner_email="dev@example.com", token_hash=digest, tier=tier)
        session.add(row)
        session.flush()
        return row.id, token


def test_tokens_are_random_and_only_their_hash_is_stored(setup: Engine) -> None:
    token_id, token = make_token(setup)
    with Session(setup) as session:
        stored = session.get_one(ApiToken, token_id).token_hash
    assert token.startswith("erio_") and len(token) > 40
    assert stored == access.hash_token(token) and token not in stored
    assert access.new_token()[0] != access.new_token()[0]


def test_anonymous_callers_are_limited_per_address(setup: Engine) -> None:
    web = caller("203.0.113.7")
    first = web.get("/v1/stats")
    assert first.status_code == 200
    assert first.headers["X-RateLimit-Limit"] == "2"
    assert first.headers["X-RateLimit-Remaining"] == "1"
    assert int(first.headers["X-RateLimit-Reset"]) > 0
    assert web.get("/v1/stats").status_code == 200

    blocked = web.get("/v1/stats")
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"
    assert 1 <= int(blocked.headers["Retry-After"]) <= 61
    assert blocked.headers["X-RateLimit-Remaining"] == "0"

    # Another address has its own window.
    assert caller("203.0.113.8").get("/v1/stats").status_code == 200


def test_token_tiers_get_their_own_limits(setup: Engine) -> None:
    _, token = make_token(setup, "free")
    web = caller("203.0.113.9")
    headers = {"Authorization": f"Bearer {token}"}
    statuses = [web.get("/v1/stats", headers=headers).status_code for _ in range(4)]
    assert statuses == [200, 200, 200, 429]

    _, pro = make_token(setup, "pro")
    response = web.get("/v1/stats", headers={"Authorization": f"Bearer {pro}"})
    assert response.headers["X-RateLimit-Limit"] == "20"


def test_token_use_is_recorded(setup: Engine) -> None:
    token_id, token = make_token(setup)
    caller("203.0.113.10").get("/v1/stats", headers={"Authorization": f"Bearer {token}"})
    with Session(setup) as session:
        assert session.get_one(ApiToken, token_id).last_used_at is not None


@pytest.mark.parametrize(
    "header", ["Bearer erio_not-a-real-token", "Basic abc", "Bearer ", "erio_plain"]
)
def test_bad_tokens_are_refused(setup: Engine, header: str) -> None:
    response = caller("203.0.113.11").get("/v1/stats", headers={"Authorization": header})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


def test_revoked_tokens_are_refused(setup: Engine, capsys: pytest.CaptureFixture[str]) -> None:
    token_id, token = make_token(setup)
    with Session(setup) as session, session.begin():
        from datetime import UTC, datetime

        session.get_one(ApiToken, token_id).revoked_at = datetime.now(UTC)
    response = caller("203.0.113.12").get("/v1/stats", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_internal_network_needs_no_token(setup: Engine) -> None:
    response = caller("172.18.0.5").get("/v1/stats")
    assert response.status_code == 200
    assert response.headers["X-RateLimit-Limit"] == "50"


def test_health_and_docs_are_not_limited(setup: Engine) -> None:
    web = caller("203.0.113.13")
    for _ in range(5):
        assert web.get("/v1/health").status_code == 200
    assert web.get("/v1/openapi.json").status_code == 200


def test_admin_cli_creates_lists_and_revokes(
    setup: Engine, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("erio_api.tokens.get_settings", lambda: _settings_for(setup))
    assert tokens_cli(["create", "--email", "ops@example.com", "--tier", "pro"]) == 0
    token = capsys.readouterr().out.strip().splitlines()[-1]
    assert token.startswith("erio_")
    with Session(setup) as session:
        row = session.scalars(
            select(ApiToken).where(ApiToken.owner_email == "ops@example.com")
        ).one()
    assert row.token_hash == access.hash_token(token)

    assert tokens_cli(["list"]) == 0
    listing = capsys.readouterr().out
    assert "ops@example.com" in listing and token not in listing

    assert tokens_cli(["revoke", "--id", str(row.id)]) == 0
    response = caller("203.0.113.14").get("/v1/stats", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def _settings_for(engine: Engine) -> object:
    class _Settings:
        sqlalchemy_url = str(engine.url)  # test URLs carry no credential

    return _Settings()
