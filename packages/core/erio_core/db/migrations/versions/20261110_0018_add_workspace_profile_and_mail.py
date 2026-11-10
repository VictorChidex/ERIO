"""workspace profile (skills read from a CV, look and layout) and confirmed alert email

Revision ID: 0018
Revises: 0017
Create date: 2026-11-10 12:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _now() -> sa.TextClause:
    return sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "workspace_profiles",
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("skills", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("titles", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("countries", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("remote_only", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("min_score", sa.SmallInteger(), server_default="40", nullable=False),
        sa.Column("prefs", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_workspace_profiles_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("workspace_id", name=op.f("pk_workspace_profiles")),
    )
    op.create_table(
        "workspace_mail",
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column(
            "frequency",
            sa.Enum(
                "daily",
                "weekly",
                name="mail_frequency",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="daily",
            nullable=False,
        ),
        sa.Column("confirm_token_hash", sa.CHAR(length=64), nullable=True),
        sa.Column("confirm_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("manage_token", sa.String(length=48), nullable=False),
        sa.Column("paused", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_checked_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False
        ),
        sa.Column("sent_job_ids", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("bounces", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_workspace_mail_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("workspace_id", name=op.f("pk_workspace_mail")),
        sa.UniqueConstraint(
            "confirm_token_hash", name=op.f("uq_workspace_mail_confirm_token_hash")
        ),
        sa.UniqueConstraint("manage_token", name=op.f("uq_workspace_mail_manage_token")),
    )


def downgrade() -> None:
    op.drop_table("workspace_mail")
    op.drop_table("workspace_profiles")
