"""add normalizer state and fx rates

Revision ID: 0005
Revises: 0004
Create date: 2026-11-05 04:32:15.694555+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fx_rates",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("currency", sa.CHAR(length=3), nullable=False),
        sa.Column("usd_per_unit", sa.Double(), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.PrimaryKeyConstraint("day", "currency", name=op.f("pk_fx_rates")),
    )
    op.add_column("jobs", sa.Column("review_reason", sa.Text(), nullable=True))
    op.add_column("raw_postings", sa.Column("normalized_hash", sa.CHAR(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("raw_postings", "normalized_hash")
    op.drop_column("jobs", "review_reason")
    op.drop_table("fx_rates")
