"""Crawl one board: fetch, record the run, store raw postings (spec section 5).

A failed fetch only ever touches ``crawl_runs`` and the board's failure
counter; it never changes a posting or a job (status rule 2). Job status
changes from what successful fetches saw are applied by erio_ingest.status.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import CursorResult, Engine, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from erio_core.connectors import BoardFetch, Fetcher, FetchError, get_connector
from erio_core.db.models import CompanyBoard, CrawlRun, RawPosting
from erio_core.schemas import RawPosting as RawPostingData
from erio_ingest.status import apply_successful_fetch
from erio_ingest.storage import RawStore

PAUSE_AFTER_FAILURES = 5
PAUSE_FOR = timedelta(hours=1)
RETRYABLE = {"timeout", "rate_limited"}

# Boards are crawled every 15 minutes; one with no new or changed posting
# for 7 days backs off to 60 minutes until it changes again (spec section 5).
FAST_CADENCE_MIN = 15
SLOW_CADENCE_MIN = 60
QUIET_AFTER = timedelta(days=7)

Clock = Callable[[], datetime]


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class CrawlResult:
    run_id: int
    outcome: str
    http_status: int | None
    postings_seen: int
    new_postings: int = 0
    changed_postings: int = 0
    closed_postings: int = 0

    @property
    def retryable(self) -> bool:
        server_error = self.http_status is not None and self.http_status >= 500
        return self.outcome in RETRYABLE or (self.outcome == "http_error" and server_error)


def crawl_board(
    engine: Engine,
    board_id: int,
    fetcher: Fetcher,
    store: RawStore,
    clock: Clock = utcnow,
) -> CrawlResult:
    with Session(engine) as session:
        board = session.get_one(CompanyBoard, board_id)
        connector = get_connector(board.source_slug)
        source_slug, board_token, etag = board.source_slug, board.board_token, board.etag

        # Record the attempt before fetching, so even a crash leaves a trace.
        run = CrawlRun(board_id=board_id, started_at=clock())
        session.add(run)
        session.commit()
        run_id = run.id

    try:
        fetched = connector.list_postings(fetcher, board_token, etag=etag)
    except FetchError as error:
        return _record_failure(
            engine, board_id, run_id, error.outcome, error.http_status, str(error), clock
        )
    except httpx.TimeoutException as error:
        return _record_failure(engine, board_id, run_id, "timeout", None, repr(error), clock)
    except httpx.HTTPError as error:
        return _record_failure(engine, board_id, run_id, "http_error", None, repr(error), clock)

    return _record_success(engine, board_id, run_id, source_slug, fetched, store, clock)


def _record_failure(
    engine: Engine,
    board_id: int,
    run_id: int,
    outcome: str,
    http_status: int | None,
    message: str,
    clock: Clock,
) -> CrawlResult:
    now = clock()
    with Session(engine) as session, session.begin():
        board = session.get_one(CompanyBoard, board_id, with_for_update=True)
        board.consecutive_failures += 1
        if board.consecutive_failures >= PAUSE_AFTER_FAILURES:
            board.paused_until = now + PAUSE_FOR
        run = session.get_one(CrawlRun, run_id)
        run.finished_at = now
        run.outcome = outcome
        run.http_status = http_status
        run.error = message[:2000]
    return CrawlResult(run_id, outcome, http_status, postings_seen=0)


def _record_success(
    engine: Engine,
    board_id: int,
    run_id: int,
    source_slug: str,
    fetched: BoardFetch,
    store: RawStore,
    clock: Clock,
) -> CrawlResult:
    now = clock()
    new = changed = 0
    with Session(engine) as session, session.begin():
        if fetched.unchanged:
            # 304: everything listed last time is still listed.
            touched: CursorResult[Any] = session.execute(  # type: ignore[assignment]
                update(RawPosting)
                .where(
                    RawPosting.board_id == board_id,
                    RawPosting.missing_since.is_(None),
                    RawPosting.closed_at.is_(None),
                )
                .values(last_seen_at=now)
            )
            seen = touched.rowcount
        else:
            rows = session.execute(
                select(RawPosting.external_id, RawPosting.content_hash).where(
                    RawPosting.source_slug == source_slug,
                    RawPosting.external_id.in_([p.external_id for p in fetched.postings]),
                )
            )
            known = {external_id: content for external_id, content in rows}
            for posting in fetched.postings:
                previous = known.get(posting.external_id)
                if previous is None:
                    new += 1
                elif previous != posting.content_hash:
                    changed += 1
                _upsert_posting(
                    session,
                    board_id,
                    posting,
                    store,
                    now,
                    store_payload=previous != posting.content_hash,
                )
            seen = len(fetched.postings)

        listed = None if fetched.unchanged else {p.external_id for p in fetched.postings}
        changes = apply_successful_fetch(session, board_id, listed, now, fetched.complete)

        board = session.get_one(CompanyBoard, board_id, with_for_update=True)
        board.last_ok_at = now
        board.consecutive_failures = 0
        board.paused_until = None
        if fetched.etag:
            board.etag = fetched.etag
        _adapt_cadence(board, changed_now=new + changed > 0, now=now)

        run = session.get_one(CrawlRun, run_id)
        run.finished_at = now
        run.outcome = "ok"
        run.http_status = fetched.http_status
        run.postings_seen = seen

    return CrawlResult(
        run_id, "ok", fetched.http_status, seen, new, changed, changes.closed_postings
    )


def _upsert_posting(
    session: Session,
    board_id: int,
    posting: RawPostingData,
    store: RawStore,
    now: datetime,
    store_payload: bool,
) -> None:
    values = {
        "source_slug": posting.source_slug,
        "board_id": board_id,
        "external_id": posting.external_id,
        "content_hash": posting.content_hash,
        "first_seen_at": now,
        "last_seen_at": now,
    }
    # Seen again: a posting that was missing or closed is reopened (rule 5).
    updates = {
        "board_id": board_id,
        "content_hash": posting.content_hash,
        "last_seen_at": now,
        "missing_since": None,
        "closed_at": None,
    }
    if store_payload:
        key = store.put_posting(posting)
        values["payload_s3_key"] = key
        updates["payload_s3_key"] = key
    statement = insert(RawPosting).values(values)
    session.execute(
        statement.on_conflict_do_update(
            index_elements=[RawPosting.source_slug, RawPosting.external_id], set_=updates
        )
    )


def _adapt_cadence(board: CompanyBoard, changed_now: bool, now: datetime) -> None:
    if changed_now or board.last_change_at is None:
        board.last_change_at = now
        board.cadence_min = FAST_CADENCE_MIN
    elif now - board.last_change_at >= QUIET_AFTER:
        board.cadence_min = SLOW_CADENCE_MIN
