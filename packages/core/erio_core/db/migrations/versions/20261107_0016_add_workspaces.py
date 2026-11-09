"""add anonymous workspaces: applications, timelines, saved searches

Revision ID: 0016
Revises: 0013
Create date: 2026-11-07 09:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
# The lead re-chains this to follow 0015 (this branch started from 0013).
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _now() -> sa.TextClause:
    return sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("token_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.Column(
            "last_used_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspaces")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_workspaces_token_hash")),
    )
    op.create_index(
        op.f("ix_workspaces_last_used_at"), "workspaces", ["last_used_at"], unique=False
    )
    op.create_table(
        "workspace_applications",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("job_id", sa.String(length=40), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("company", sa.String(length=200), nullable=False),
        sa.Column("location", sa.String(length=300), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column(
            "stage",
            sa.Enum(
                "saved",
                "applied",
                "interviewing",
                "offer",
                "rejected",
                "withdrawn",
                name="application_stage",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="saved",
            nullable=False,
        ),
        sa.Column("notes", sa.Text(), server_default="", nullable=False),
        sa.Column("applied_on", sa.Date(), nullable=True),
        sa.Column("follow_up_on", sa.Date(), nullable=True),
        sa.Column(
            "stage_changed_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.Column("seen_status", sa.String(length=16), nullable=True),
        sa.Column("seen_digest", sa.CHAR(length=16), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_workspace_applications_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspace_applications")),
        sa.UniqueConstraint(
            "workspace_id", "job_id", name=op.f("uq_workspace_applications_workspace_id_job_id")
        ),
    )
    op.create_index(
        op.f("ix_workspace_applications_workspace_id"),
        "workspace_applications",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "application_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("application_id", sa.BigInteger(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "created",
                "stage",
                "note",
                "reminder",
                "job_closed",
                "job_reopened",
                "job_changed",
                name="application_event_kind",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("stage", sa.String(length=16), nullable=True),
        sa.Column("text", sa.String(length=2000), nullable=True),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["workspace_applications.id"],
            name=op.f("fk_application_events_application_id_workspace_applications"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_application_events")),
    )
    op.create_index(
        op.f("ix_application_events_application_id_at"),
        "application_events",
        ["application_id", "at"],
        unique=False,
    )
    op.create_table(
        "saved_searches",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("feed_token", sa.String(length=48), nullable=False),
        sa.Column("webhook_url", sa.Text(), nullable=True),
        sa.Column("webhook_failures", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("webhook_disabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.Column(
            "last_evaluated_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False
        ),
        sa.Column(
            "last_viewed_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_saved_searches_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_saved_searches")),
        sa.UniqueConstraint("feed_token", name=op.f("uq_saved_searches_feed_token")),
    )
    op.create_index(
        op.f("ix_saved_searches_workspace_id"), "saved_searches", ["workspace_id"], unique=False
    )
    op.create_table(
        "saved_search_matches",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("search_id", sa.BigInteger(), nullable=False),
        sa.Column("job_id", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("company", sa.String(length=200), nullable=False),
        sa.Column("location", sa.String(length=300), nullable=True),
        sa.Column("apply_url", sa.Text(), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("matched_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["search_id"],
            ["saved_searches.id"],
            name=op.f("fk_saved_search_matches_search_id_saved_searches"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_saved_search_matches")),
        sa.UniqueConstraint(
            "search_id", "job_id", name=op.f("uq_saved_search_matches_search_id_job_id")
        ),
    )
    op.create_index(
        op.f("ix_saved_search_matches_search_id_matched_at"),
        "saved_search_matches",
        ["search_id", "matched_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_saved_search_matches_search_id_matched_at"), table_name="saved_search_matches"
    )
    op.drop_table("saved_search_matches")
    op.drop_index(op.f("ix_saved_searches_workspace_id"), table_name="saved_searches")
    op.drop_table("saved_searches")
    op.drop_index(op.f("ix_application_events_application_id_at"), table_name="application_events")
    op.drop_table("application_events")
    op.drop_index(
        op.f("ix_workspace_applications_workspace_id"), table_name="workspace_applications"
    )
    op.drop_table("workspace_applications")
    op.drop_index(op.f("ix_workspaces_last_used_at"), table_name="workspaces")
    op.drop_table("workspaces")
