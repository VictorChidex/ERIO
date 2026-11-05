"""add job dedup fields

Revision ID: 0008
Revises: 0007
Create date: 2026-11-05 08:10:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("merged_into", sa.String(length=40), nullable=True))
    op.add_column("jobs", sa.Column("dedup_key", sa.CHAR(length=64), nullable=True))
    op.add_column("jobs", sa.Column("simhash", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        op.f("fk_jobs_merged_into_jobs"),
        "jobs",
        "jobs",
        ["merged_into"],
        ["canonical_id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("ix_jobs_merged_into"), "jobs", ["merged_into"], unique=False)
    op.create_index(
        op.f("ix_jobs_company_id_dedup_key"), "jobs", ["company_id", "dedup_key"], unique=False
    )
    op.add_column("job_sources", sa.Column("merged_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f("ix_job_sources_merged_at"), "job_sources", ["merged_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_job_sources_merged_at"), table_name="job_sources")
    op.drop_column("job_sources", "merged_at")
    op.drop_index(op.f("ix_jobs_company_id_dedup_key"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_merged_into"), table_name="jobs")
    op.drop_constraint(op.f("fk_jobs_merged_into_jobs"), "jobs", type_="foreignkey")
    op.drop_column("jobs", "simhash")
    op.drop_column("jobs", "dedup_key")
    op.drop_column("jobs", "merged_into")
