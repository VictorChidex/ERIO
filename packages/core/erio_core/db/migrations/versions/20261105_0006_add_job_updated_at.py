"""add job updated_at

Revision ID: 0006
Revises: 0005
Create date: 2026-11-05 04:47:40.296075+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(op.f("ix_jobs_updated_at"), "jobs", ["updated_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_jobs_updated_at"), table_name="jobs")
    op.drop_column("jobs", "updated_at")
