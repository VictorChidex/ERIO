"""Crawl one board: fetch, record the run, store raw postings (spec section 5).

A failed fetch only ever touches ``crawl_runs`` and the board's failure
counter; it never changes a posting or a job (status rule 2). Job status
changes from what successful fetches saw are applied by erio_ingest.status.
"""

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import CursorResult, Engine, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from erio_core.connectors import BoardFetch, Connector, Fetcher, FetchError, get_connector
from erio_core.db.models import CompanyBoard, CrawlRun, RawPosting
from erio_core.observability import log_context
from erio_core.schemas import RawPosting as RawPostingData
from erio_ingest.status import apply_successful_fetch
from erio_ingest.storage import STORE_WORKERS, RawStore

PAUSE_AFTER_FAILURES = 5
PAUSE_FOR = timedelta(hours=1)
RETRYABLE = {"timeout", "rate_limited"}

# Boards are crawled every 15 minutes; one with no new or changed posting
# for 7 days backs off to 60 minutes until it changes again (spec section 5).
FAST_CADENCE_MIN = 15
SLOW_CADENCE_MIN = 60
QUIET_AFTER = timedelta(days=7)

Clock = Callable[[], datetime]


log = logging.getLogger(__name__)


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
    reopened_postings: int = 0

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
        source_slug = board.source_slug

        # Record the attempt before fetching, so even a crash leaves a trace.
        run = CrawlRun(board_id=board_id, started_at=clock())
        session.add(run)
        session.commit()
        run_id = run.id

    with log_context(crawl_run_id=run_id, board_id=board_id, source=source_slug):
        result = _crawl(engine, board_id, run_id, connector, fetcher, store, clock)
        log.info(
            "crawl finished",
            extra={
                "outcome": result.outcome,
                "http_status": result.http_status,
                "postings_seen": result.postings_seen,
                "postings_new": result.new_postings,
                "postings_closed": result.closed_postings,
                "postings_reopened": result.reopened_postings,
            },
        )
        return result


def _crawl(
    engine: Engine,
    board_id: int,
    run_id: int,
    connector: Connector,
    fetcher: Fetcher,
    store: RawStore,
    clock: Clock,
) -> CrawlResult:
    with Session(engine) as session:
        board = session.get_one(CompanyBoard, board_id)
        board_token, etag, source_slug = board.board_token, board.etag, board.source_slug

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
    new = changed = reopened = 0
    # Payloads go to object storage before the transaction opens, so a slow or stalled
    # store never holds the row locks other writers queue behind. Keys include the
    # content hash, so storing one twice is harmless.
    keys = _store_changed_payloads(engine, source_slug, fetched, store)
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
                select(RawPosting.external_id, RawPosting.content_hash, RawPosting.closed_at).where(
                    RawPosting.source_slug == source_slug,
                    RawPosting.external_id.in_([p.external_id for p in fetched.postings]),
                )
            ).all()
            known = {external_id: content for external_id, content, _ in rows}
            closed = {external_id for external_id, _, closed_at in rows if closed_at}
            for posting in fetched.postings:
                previous = known.get(posting.external_id)
                if previous is None:
                    new += 1
                elif previous != posting.content_hash:
                    changed += 1
                reopened += posting.external_id in closed
                _upsert_posting(session, board_id, posting, keys.get(posting.external_id), now)
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
        run.postings_new = new
        run.postings_closed = changes.closed_postings
        run.postings_reopened = reopened

    return CrawlResult(
        run_id, "ok", fetched.http_status, seen, new, changed, changes.closed_postings, reopened
    )


def _store_changed_payloads(
    engine: Engine, source_slug: str, fetched: BoardFetch, store: RawStore
) -> dict[str, str]:
    """Store the payload of every posting that is new or has changed; keys by external id."""
    if fetched.unchanged or not fetched.postings:
        return {}
    with Session(engine) as session:
        known = dict(
            session.execute(
                select(RawPosting.external_id, RawPosting.content_hash).where(
                    RawPosting.source_slug == source_slug,
                    RawPosting.external_id.in_([p.external_id for p in fetched.postings]),
                )
            )
            .tuples()
            .all()
        )
    changed = [p for p in fetched.postings if known.get(p.external_id) != p.content_hash]
    with ThreadPoolExecutor(STORE_WORKERS) as pool:
        keys = list(pool.map(store.put_posting, changed))
    return {posting.external_id: key for posting, key in zip(changed, keys, strict=True)}


def _upsert_posting(
    session: Session,
    board_id: int,
    posting: RawPostingData,
    payload_key: str | None,
    now: datetime,
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
    if payload_key is not None:
        values["payload_s3_key"] = payload_key
        updates["payload_s3_key"] = payload_key
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
