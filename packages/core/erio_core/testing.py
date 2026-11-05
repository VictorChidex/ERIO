"""Pytest fixtures for tests that need a real Postgres or Redis.

Loaded for every test suite by the repo's root conftest.py. Each database
test gets a fresh, empty database on the server named by
ERIO_TEST_DATABASE_URL (default: the local compose Postgres) and drops it
afterwards; Redis tests use ERIO_TEST_REDIS_URL. Without a reachable server
these tests skip, unless ERIO_REQUIRE_DB_TESTS is set (as in CI), where
they fail instead.
"""

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine

from erio_core.settings import Settings

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


def alembic_config(url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.attributes["sqlalchemy_url"] = url
    config.attributes["configure_logger"] = False
    return config


@pytest.fixture
def database_url() -> Iterator[str]:
    """SQLAlchemy URL of a fresh, empty database."""
    server = os.environ.get("ERIO_TEST_DATABASE_URL", Settings().database_url)
    try:
        admin = psycopg.connect(server, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as error:
        if os.environ.get("ERIO_REQUIRE_DB_TESTS"):
            raise
        pytest.skip(f"no Postgres for database tests: {error}")

    name = f"erio_test_{uuid.uuid4().hex[:12]}"
    with admin:
        admin.execute(f'CREATE DATABASE "{name}"')
        try:
            base, _, _ = server.rpartition("/")
            yield f"{base}/{name}".replace("postgresql://", "postgresql+psycopg://", 1)
        finally:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture
def migrated_engine(database_url: str) -> Iterator[Engine]:
    """Engine on a fresh database with every migration applied."""
    command.upgrade(alembic_config(database_url), "head")
    engine = create_engine(database_url)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def redis_url() -> Iterator[str]:
    """URL of a Redis database, flushed before and after the test."""
    import redis

    url = os.environ.get("ERIO_TEST_REDIS_URL", "redis://127.0.0.1:6379/15")
    client = redis.Redis.from_url(url, socket_connect_timeout=3)
    try:
        client.ping()
    except redis.RedisError as error:
        if os.environ.get("ERIO_REQUIRE_DB_TESTS"):
            raise
        pytest.skip(f"no Redis for tests: {error}")
    client.flushdb()
    try:
        yield url
    finally:
        client.flushdb()
        client.close()


@pytest.fixture
def search_alias() -> Iterator[str]:
    """A unique index alias on the OpenSearch named by ERIO_TEST_OPENSEARCH_URL;
    every index behind it is deleted afterwards."""
    from opensearchpy import OpenSearch
    from opensearchpy.exceptions import ConnectionError as SearchConnectionError

    url = os.environ.get("ERIO_TEST_OPENSEARCH_URL", Settings().opensearch_url)
    search = OpenSearch(hosts=[url], timeout=10)
    try:
        search.info()
    except SearchConnectionError as error:
        if os.environ.get("ERIO_REQUIRE_DB_TESTS"):
            raise
        pytest.skip(f"no OpenSearch for tests: {error}")
    alias = f"test_jobs_{uuid.uuid4().hex[:10]}"
    try:
        yield alias
    finally:
        search.indices.delete(index=f"{alias}*", ignore_unavailable=True)
        search.close()
