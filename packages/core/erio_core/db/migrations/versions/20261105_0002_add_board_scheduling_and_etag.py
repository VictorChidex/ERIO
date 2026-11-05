"""add board scheduling and etag

Revision ID: 0002
Revises: 0001
Create date: 2026-11-05 03:51:40.749329+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "company_boards",
        sa.Column(
            "next_crawl_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column("company_boards", sa.Column("etag", sa.String(length=200), nullable=True))
    op.create_index(
        op.f("ix_company_boards_next_crawl_at"), "company_boards", ["next_crawl_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_company_boards_next_crawl_at"), table_name="company_boards")
    op.drop_column("company_boards", "etag")
    op.drop_column("company_boards", "next_crawl_at")
