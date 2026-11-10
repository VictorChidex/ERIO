"""The anonymous workspace: saved roles, application tracking and saved searches.

There is no account. A workspace is a row holding only the SHA-256 of a random 256-bit token
that lives in its owner's browser. Nothing here names a person: no email, no address, no
device. Every child table cascades from ``workspaces``, so deleting the workspace deletes
everything. CVs are never stored.
"""

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from erio_core.db.models import Base, created_at, text_enum

APPLICATION_STAGES = ("saved", "applied", "interviewing", "offer", "rejected", "withdrawn")
EVENT_KINDS = ("created", "stage", "note", "reminder", "job_closed", "job_reopened", "job_changed")

# Per-workspace caps and size limits (the API enforces them; the schema cannot).
MAX_APPLICATIONS = 1000
MAX_SAVED = 500  # entries still at the "saved" stage
MAX_SEARCHES = 20
MAX_NOTE_BYTES = 64 * 1024
MAX_NOTES_TOTAL_BYTES = 4 * 1024 * 1024
MAX_EVENTS_PER_APPLICATION = 200
MAX_MATCHES_PER_SEARCH = 100
RETENTION_DAYS = 365


class Workspace(Base):
    """One anonymous workspace, found only by the hash of its owner's token."""

    __tablename__ = "workspaces"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    token_hash: Mapped[str] = mapped_column(CHAR(64), unique=True)
    created_at: Mapped[datetime] = created_at()
    # Refreshed at most hourly by use; a workspace unused for a year is deleted.
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class Application(Base):
    """A saved role and, as the person moves it along, an application.

    ``job_id`` links to an ERIO job when there is one (no foreign key: the job may close,
    merge or leave the index, and the saved copy of its title and place keeps working).
    """

    __tablename__ = "workspace_applications"
    __table_args__ = (UniqueConstraint("workspace_id", "job_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[str | None] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(300))
    company: Mapped[str] = mapped_column(String(200))
    location: Mapped[str | None] = mapped_column(String(300))
    url: Mapped[str | None] = mapped_column(Text)
    stage: Mapped[str] = mapped_column(
        text_enum("application_stage", APPLICATION_STAGES), server_default="saved"
    )
    notes: Mapped[str] = mapped_column(Text, server_default="")
    applied_on: Mapped[date | None] = mapped_column(Date)
    follow_up_on: Mapped[date | None] = mapped_column(Date)
    stage_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # What the person last saw of the job, to show what changed since (status, title,
    # place, salary, apply link); cleared by acknowledging the change.
    seen_status: Mapped[str | None] = mapped_column(String(16))
    seen_digest: Mapped[str | None] = mapped_column(CHAR(16))


class ApplicationEvent(Base):
    """One line in an application's timeline."""

    __tablename__ = "application_events"
    __table_args__ = (Index(None, "application_id", "at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("workspace_applications.id", ondelete="CASCADE")
    )
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    kind: Mapped[str] = mapped_column(text_enum("application_event_kind", EVENT_KINDS))
    stage: Mapped[str | None] = mapped_column(String(16))
    text: Mapped[str | None] = mapped_column(String(2000))


class SavedSearch(Base):
    """A saved search: a new-match counter, a public Atom feed and an optional webhook."""

    __tablename__ = "saved_searches"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # Anyone holding this random string can read the feed (public job data only); it is not
    # a login and grants nothing else.
    feed_token: Mapped[str] = mapped_column(String(48), unique=True)
    webhook_url: Mapped[str | None] = mapped_column(Text)
    webhook_failures: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    webhook_disabled: Mapped[bool] = mapped_column(Boolean, server_default="false")
    created_at: Mapped[datetime] = created_at()
    # Jobs indexed after this moment have not been checked against the search yet.
    last_evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # Matches found after this moment count as "new since you last looked".
    last_viewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SavedSearchMatch(Base):
    """A job a saved search found (the latest ones only), with the facts a feed shows."""

    __tablename__ = "saved_search_matches"
    __table_args__ = (
        UniqueConstraint("search_id", "job_id"),
        Index(None, "search_id", "matched_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    search_id: Mapped[int] = mapped_column(ForeignKey("saved_searches.id", ondelete="CASCADE"))
    job_id: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(300))
    company: Mapped[str] = mapped_column(String(200))
    location: Mapped[str | None] = mapped_column(String(300))
    apply_url: Mapped[str] = mapped_column(Text)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    matched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Null until the search's webhook, if it has one, has been told about this match.
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
