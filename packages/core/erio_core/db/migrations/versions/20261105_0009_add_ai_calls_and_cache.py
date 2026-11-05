"""add ai calls and cache

Revision ID: 0009
Revises: 0008
Create date: 2026-11-05 14:11:25.789717+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_cache",
        sa.Column("key", sa.CHAR(length=64), nullable=False),
        sa.Column("task", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=80), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_ai_cache")),
    )
    op.create_table(
        "ai_calls",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("task", sa.String(length=40), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=80), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Double(), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_calls")),
    )
    op.create_index(op.f("ix_ai_calls_task_at"), "ai_calls", ["task", "at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_ai_calls_task_at"), table_name="ai_calls")
    op.drop_table("ai_calls")
    op.drop_table("ai_cache")
