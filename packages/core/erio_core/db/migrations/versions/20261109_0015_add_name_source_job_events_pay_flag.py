"""add company name_source, job_events and the unreliable pay flag

Revision ID: 0015
Revises: 0014
Create date: 2026-11-09 12:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "companies",
        sa.Column(
            "name_source",
            sa.Enum(
                "seed",
                "placeholder",
                "source",
                name="name_source",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="seed",
            nullable=False,
        ),
    )
    # Seed companies always carry a domain; board discovery creates its companies without one.
    op.execute("UPDATE companies SET name_source = 'placeholder' WHERE domain IS NULL")
    op.add_column(
        "jobs",
        sa.Column("salary_unreliable", sa.Boolean(), server_default="false", nullable=False),
    )
    op.create_table(
        "job_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.String(length=40), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "added",
                "changed",
                "closed",
                "reopened",
                "merged",
                name="job_event_kind",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "changes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.canonical_id"],
            name=op.f("fk_job_events_job_id_jobs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_events")),
    )
    op.create_index(op.f("ix_job_events_job_id_at"), "job_events", ["job_id", "at"], unique=False)
    op.create_index(op.f("ix_job_events_at"), "job_events", ["at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_job_events_at"), table_name="job_events")
    op.drop_index(op.f("ix_job_events_job_id_at"), table_name="job_events")
    op.drop_table("job_events")
    op.drop_column("jobs", "salary_unreliable")
    op.drop_column("companies", "name_source")
