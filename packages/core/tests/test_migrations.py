"""Migration tests against a real Postgres (fixtures in conftest.py)."""

from datetime import UTC, datetime

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from erio_core.db.models import Base
from erio_core.testing import alembic_config

EXPECTED_TABLES = {
    "ai_cache",
    "ai_evals",
    "ai_calls",
    "api_tokens",
    "application_events",
    "board_discovery",
    "companies",
    "company_boards",
    "countries",
    "crawl_runs",
    "fx_rates",
    "job_events",
    "job_sources",
    "jobs",
    "raw_postings",
    "saved_search_matches",
    "saved_searches",
    "source_checks",
    "sources",
    "workspace_applications",
    "workspaces",
}


def _tables(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_upgrade_and_downgrade_run_cleanly(database_url: str) -> None:
    config = alembic_config(database_url)

    command.upgrade(config, "head")
    assert _tables(database_url) == EXPECTED_TABLES | {"alembic_version"}

    command.downgrade(config, "base")
    assert _tables(database_url) == {"alembic_version"}

    command.upgrade(config, "head")
    assert _tables(database_url) == EXPECTED_TABLES | {"alembic_version"}


def test_models_match_migrations(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        differences = compare_metadata(context, Base.metadata)

    assert differences == [], "models and migrations differ: add a migration"


def test_spec_indexes_exist(migrated_engine: Engine) -> None:
    inspector = inspect(migrated_engine)
    job_indexes = {tuple(ix["column_names"]) for ix in inspector.get_indexes("jobs")}
    posting_uniques = {
        tuple(uq["column_names"]) for uq in inspector.get_unique_constraints("raw_postings")
    }

    # Spec step 3: country_code, status, posted_at and (source_slug, external_id).
    assert ("country_code",) in job_indexes
    assert ("status", "posted_at") in job_indexes
    assert ("posted_at",) in job_indexes
    assert ("source_slug", "external_id") in posting_uniques


def test_check_constraints_reject_unknown_values(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        connection.execute(
            text("INSERT INTO companies (id, name, slug) VALUES (1, 'Acme', 'acme')")
        )
    with pytest.raises(IntegrityError), migrated_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO jobs (canonical_id, title, company_id, remote_status, "
                "status, apply_url, posted_at) VALUES ('j1', 'Engineer', 1, 'remote', "
                "'deleted', 'https://example.com', :now)"
            ),
            {"now": datetime.now(UTC)},
        )


def test_company_slugs_are_backfilled_unique_and_ascii(database_url: str) -> None:
    config = alembic_config(database_url)
    command.upgrade(config, "0013")
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO companies (id, name) VALUES "
                    "(1, 'Café Müller & Co.'), (2, 'Acme'), (3, 'ACME'), (4, '!!!')"
                )
            )
        command.upgrade(config, "0014")
        with engine.connect() as connection:
            slugs = dict(connection.execute(text("SELECT id, slug FROM companies")).tuples().all())
        assert slugs == {1: "cafe-muller-co", 2: "acme", 3: "acme-2", 4: "company"}

        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                text("INSERT INTO companies (id, name, slug) VALUES (5, 'Other', 'acme')")
            )

        command.downgrade(config, "0013")
        assert "slug" not in {c["name"] for c in inspect(engine).get_columns("companies")}
    finally:
        engine.dispose()
