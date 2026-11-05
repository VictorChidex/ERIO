"""add company country, board discovery and source checks

Revision ID: 0007
Revises: 0006
Create date: 2026-11-05 08:18:51.226581+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "source_checks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source_slug", sa.String(length=40), nullable=False),
        sa.Column("board_token", sa.String(length=200), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("postings", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["source_slug"], ["sources.slug"], name=op.f("fk_source_checks_source_slug_sources")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_checks")),
    )
    op.create_index(
        op.f("ix_source_checks_source_slug_checked_at"),
        "source_checks",
        ["source_slug", "checked_at"],
        unique=False,
    )
    op.create_table(
        "board_discovery",
        sa.Column("company_id", sa.BigInteger(), nullable=False),
        sa.Column("source_slug", sa.String(length=40), nullable=False),
        sa.Column("tried_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("board_token", sa.String(length=200), nullable=True),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_board_discovery_company_id_companies"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_slug"], ["sources.slug"], name=op.f("fk_board_discovery_source_slug_sources")
        ),
        sa.PrimaryKeyConstraint("company_id", "source_slug", name=op.f("pk_board_discovery")),
    )
    op.add_column("companies", sa.Column("country_code", sa.CHAR(length=2), nullable=True))
    op.create_foreign_key(
        op.f("fk_companies_country_code_countries"),
        "companies",
        "countries",
        ["country_code"],
        ["code"],
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_companies_country_code_countries"), "companies", type_="foreignkey")
    op.drop_column("companies", "country_code")
    op.drop_table("board_discovery")
    op.drop_index(op.f("ix_source_checks_source_slug_checked_at"), table_name="source_checks")
    op.drop_table("source_checks")
