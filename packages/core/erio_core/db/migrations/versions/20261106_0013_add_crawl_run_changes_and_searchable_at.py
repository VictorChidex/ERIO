"""add crawl run changes and job searchable_at

Revision ID: 0013
Revises: 0012
Create date: 2026-11-05 16:59:32.362871+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("crawl_runs", sa.Column("postings_new", sa.Integer(), nullable=True))
    op.add_column("crawl_runs", sa.Column("postings_closed", sa.Integer(), nullable=True))
    op.add_column("crawl_runs", sa.Column("postings_reopened", sa.Integer(), nullable=True))
    op.add_column("jobs", sa.Column("searchable_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("freshness_seconds", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_jobs_searchable_at"), "jobs", ["searchable_at"], unique=False)
    # Jobs that already exist were made searchable before anyone measured it:
    # stamp them so the indexer leaves them be, with no freshness to report.
    op.execute("update jobs set searchable_at = now()")


def downgrade() -> None:
    op.drop_index(op.f("ix_jobs_searchable_at"), table_name="jobs")
    op.drop_column("jobs", "freshness_seconds")
    op.drop_column("jobs", "searchable_at")
    op.drop_column("crawl_runs", "postings_reopened")
    op.drop_column("crawl_runs", "postings_closed")
    op.drop_column("crawl_runs", "postings_new")
