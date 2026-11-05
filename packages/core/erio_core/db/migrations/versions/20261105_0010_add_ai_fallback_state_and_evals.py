"""add ai fallback state and evals

Revision ID: 0010
Revises: 0009
Create date: 2026-11-05 14:22:10.730098+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_evals",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("task", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=80), nullable=False),
        sa.Column("rows", sa.Integer(), nullable=False),
        sa.Column("answered", sa.Integer(), nullable=False),
        sa.Column("accuracy", sa.Double(), nullable=False),
        sa.Column("cost_usd", sa.Double(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_evals")),
    )
    op.create_index(op.f("ix_ai_evals_task_at"), "ai_evals", ["task", "at"], unique=False)
    op.add_column("jobs", sa.Column("ai_checked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "jobs",
        sa.Column("ai_filled", sa.ARRAY(sa.String(length=16)), server_default="{}", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("jobs", "ai_filled")
    op.drop_column("jobs", "ai_checked_at")
    op.drop_index(op.f("ix_ai_evals_task_at"), table_name="ai_evals")
    op.drop_table("ai_evals")
