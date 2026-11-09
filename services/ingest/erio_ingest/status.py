"""Failure-aware status rules (spec section 5).

1. A fetch counts as successful only with HTTP 200 and a payload that parses
   (or 304 to our ETag). Only successful fetches reach this module.
2. Failed fetches never change any status: the pipeline records them and
   stops before calling anything here.
3. A posting missing from 2 consecutive successful fetches, at least 30
   minutes apart, is closed. A job closes when all its postings are closed.
4. A job not verified by any successful fetch for 72 hours becomes
   ``unknown`` (``mark_unverified``, run periodically).
5. A posting that reappears is reopened, and its job with it, keeping the
   same ``canonical_id``.

A job that closes or reopens gets a history event (``erio_ingest.history``).
"""

from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from erio_core.db.models import Job, JobSource, RawPosting
from erio_ingest.history import record_event

CLOSE_AFTER_MISSING = timedelta(minutes=30)
UNVERIFIED_AFTER = timedelta(hours=72)


@dataclass
class StatusChanges:
    first_misses: int = 0
    closed_postings: int = 0
    jobs_updated: int = 0


def apply_successful_fetch(
    session: Session,
    board_id: int,
    listed: Collection[str] | None,
    now: datetime,
    complete: bool = True,
) -> StatusChanges:
    """Apply rules 3 and 5 after a successful fetch of one board.

    ``listed`` holds the external IDs the board listed; ``None`` means the
    source answered 304, so it lists exactly what it listed last time. An
    incomplete fetch (``complete`` False: the connector stopped at a cap)
    closes nothing: postings it did not list are unknown, not missing.
    Postings it lists were already marked seen (and reopened) by the upsert.
    """
    changes = StatusChanges()
    open_postings = session.scalars(
        select(RawPosting).where(RawPosting.board_id == board_id, RawPosting.closed_at.is_(None))
    )
    for posting in open_postings:
        still_listed = (
            posting.missing_since is None if listed is None else posting.external_id in listed
        )
        if still_listed or not complete:
            continue
        if posting.missing_since is None:
            posting.missing_since = now
            changes.first_misses += 1
        elif now - posting.missing_since >= CLOSE_AFTER_MISSING:
            posting.closed_at = now
            changes.closed_postings += 1

    session.flush()
    job_ids = session.scalars(
        select(JobSource.job_id)
        .join(RawPosting, RawPosting.id == JobSource.raw_posting_id)
        .where(RawPosting.board_id == board_id)
        .distinct()
    ).all()
    changes.jobs_updated = refresh_jobs(session, job_ids, now)
    return changes


def refresh_jobs(session: Session, job_ids: Collection[str], now: datetime) -> int:
    """Derive each job's status from the postings it was built from."""
    for job_id in job_ids:
        job = session.get_one(Job, job_id)
        was_closed = job.status == "closed"
        postings = session.scalars(
            select(RawPosting)
            .join(JobSource, JobSource.raw_posting_id == RawPosting.id)
            .where(JobSource.job_id == job_id)
        ).all()
        still_open = [p for p in postings if p.closed_at is None]
        if still_open:
            job.closed_at = None
            listed = [p.last_seen_at for p in still_open if p.missing_since is None]
            if listed:
                job.last_verified_at = max(listed)
            verified = (
                job.last_verified_at is not None and now - job.last_verified_at < UNVERIFIED_AFTER
            )
            job.status = "open" if verified else "unknown"
        elif postings:
            job.status = "closed"
            job.closed_at = max(p.closed_at for p in postings if p.closed_at is not None)
        if job.status == "closed" and not was_closed:
            record_event(session, job_id, "closed", now)
        elif was_closed and job.status != "closed":
            record_event(session, job_id, "reopened", now)
    return len(job_ids)


def mark_unverified(session: Session, now: datetime) -> int:
    """Rule 4: open jobs no successful fetch has verified for 72 hours."""
    cutoff = now - UNVERIFIED_AFTER
    result = session.execute(
        update(Job)
        .where(
            Job.status == "open",
            or_(
                Job.last_verified_at < cutoff,
                Job.last_verified_at.is_(None) & (Job.indexed_at < cutoff),
            ),
        )
        .values(status="unknown")
    )
    return int(getattr(result, "rowcount", 0) or 0)
