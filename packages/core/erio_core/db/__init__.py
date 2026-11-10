"""Postgres schema (spec section 4) and database helpers."""

# Registers the workspace tables on the shared metadata (Alembic and the tests need them).
from erio_core.db import workspace_models  # noqa: F401
