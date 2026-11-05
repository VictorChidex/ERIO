"""Migration tests against a real Postgres.

Each test gets a fresh, empty database on the server named by
ERIO_TEST_DATABASE_URL (default: the local compose Postgres) and drops it
afterwards. Without a reachable server the tests skip, unless
ERIO_REQUIRE_DB_TESTS is set (as in CI), where they fail instead.
"""

import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from erio_core.db.models import Base
from erio_core.settings import Settings

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"

EXPECTED_TABLES = {
    "api_tokens",
    "companies",
    "company_boards",
    "countries",
    "crawl_runs",
    "job_sources",
    "jobs",
    "raw_postings",
    "sources",
}


def _server_url() -> str:
    return os.environ.get("ERIO_TEST_DATABASE_URL", Settings().database_url)


@pytest.fixture
def database_url() -> Iterator[str]:
    server = _server_url()
    try:
        admin = psycopg.connect(server, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as error:
        if os.environ.get("ERIO_REQUIRE_DB_TESTS"):
            raise
        pytest.skip(f"no Postgres for migration tests: {error}")

    name = f"erio_test_{uuid.uuid4().hex[:12]}"
    with admin:
        admin.execute(f'CREATE DATABASE "{name}"')
        try:
            base, _, _ = server.rpartition("/")
            yield f"{base}/{name}".replace("postgresql://", "postgresql+psycopg://", 1)
        finally:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def _alembic(url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.attributes["sqlalchemy_url"] = url
    config.attributes["configure_logger"] = False
    return config


def _tables(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_upgrade_and_downgrade_run_cleanly(database_url: str) -> None:
    config = _alembic(database_url)

    command.upgrade(config, "head")
    assert _tables(database_url) == EXPECTED_TABLES | {"alembic_version"}

    command.downgrade(config, "base")
    assert _tables(database_url) == {"alembic_version"}

    command.upgrade(config, "head")
    assert _tables(database_url) == EXPECTED_TABLES | {"alembic_version"}


def test_models_match_migrations(database_url: str) -> None:
    command.upgrade(_alembic(database_url), "head")

    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(connection, opts={"compare_type": True})
            differences = compare_metadata(context, Base.metadata)
    finally:
        engine.dispose()

    assert differences == [], "models and migrations differ: add a migration"


def test_spec_indexes_exist(database_url: str) -> None:
    command.upgrade(_alembic(database_url), "head")

    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        job_indexes = {tuple(ix["column_names"]) for ix in inspector.get_indexes("jobs")}
        posting_uniques = {
            tuple(uq["column_names"]) for uq in inspector.get_unique_constraints("raw_postings")
        }
    finally:
        engine.dispose()

    # Spec step 3: country_code, status, posted_at and (source_slug, external_id).
    assert ("country_code",) in job_indexes
    assert ("status", "posted_at") in job_indexes
    assert ("posted_at",) in job_indexes
    assert ("source_slug", "external_id") in posting_uniques


def test_check_constraints_reject_unknown_values(database_url: str) -> None:
    command.upgrade(_alembic(database_url), "head")

    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO companies (id, name) VALUES (1, 'Acme')"))
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO jobs (canonical_id, title, company_id, remote_status, "
                    "status, apply_url, posted_at) VALUES ('j1', 'Engineer', 1, 'remote', "
                    "'deleted', 'https://example.com', :now)"
                ),
                {"now": datetime.now(UTC)},
            )
    finally:
        engine.dispose()
