"""Shared fixtures for tests that need a real Postgres.

Each test gets a fresh, empty database on the server named by
ERIO_TEST_DATABASE_URL (default: the local compose Postgres) and drops it
afterwards. Without a reachable server these tests skip, unless
ERIO_REQUIRE_DB_TESTS is set (as in CI), where they fail instead.
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
