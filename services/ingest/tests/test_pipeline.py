"""Crawl pipeline tests on a real Postgres with recorded Greenhouse responses."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

from erio_core.connectors import FetchResponse
from erio_core.connectors.greenhouse import GreenhouseConnector
from erio_core.db.models import Company, CompanyBoard, CrawlRun, RawPosting
from erio_core.db.seed import sync_sources
from erio_core.schemas import RawPosting as RawPostingData
from erio_ingest.pipeline import PAUSE_AFTER_FAILURES, crawl_board
from erio_ingest.storage import MemoryRawStore

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "greenhouse"
URL = GreenhouseConnector().board_url("truelayer")
T0 = datetime(2026, 11, 5, 9, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now

    def advance(self, minutes: int = 15) -> None:
        self.now += timedelta(minutes=minutes)


class Source:
    """A fake Greenhouse that serves whatever the test sets."""

    def __init__(self, status: int = 200, body: bytes = b"", etag: str | None = None):
        self.status, self.body, self.etag = status, body, etag
        self.calls = 0

    def get(self, url: str, etag: str | None = None) -> FetchResponse:
        assert url == URL
        self.calls += 1
        if self.etag and etag == self.etag:
            return FetchResponse(304, b"")
        headers = {"ETag": self.etag} if self.etag else {}
        return FetchResponse(self.status, self.body, headers)


@pytest.fixture
def board_id(migrated_engine: Engine) -> int:
    sync_sources(migrated_engine)
    with Session(migrated_engine) as session, session.begin():
        company = Company(name="TrueLayer", domain="truelayer.com")
        session.add(company)
        session.flush()
        board = CompanyBoard(
            company_id=company.id, source_slug="greenhouse", board_token="truelayer"
        )
        session.add(board)
        session.flush()
        return board.id


def truelayer() -> bytes:
    return (FIXTURES / "truelayer.json").read_bytes()


def postings(engine: Engine) -> list[RawPosting]:
    with Session(engine) as session:
        return list(session.scalars(select(RawPosting).order_by(RawPosting.external_id)))


def board(engine: Engine, board_id: int) -> CompanyBoard:
    with Session(engine) as session:
        return session.get_one(CompanyBoard, board_id)


def test_successful_crawl_records_run_postings_and_payloads(
    migrated_engine: Engine, board_id: int
) -> None:
    store, clock = MemoryRawStore(), Clock()

    result = crawl_board(migrated_engine, board_id, Source(200, truelayer()), store, clock)

    assert (result.outcome, result.http_status, result.postings_seen, result.new_postings) == (
        "ok", 200, 3, 3,
    )  # fmt: skip
    with Session(migrated_engine) as session:
        run = session.get_one(CrawlRun, result.run_id)
    assert (run.outcome, run.postings_seen, run.started_at, run.finished_at) == ("ok", 3, T0, T0)

    rows = postings(migrated_engine)
    assert len(rows) == 3
    assert all(r.first_seen_at == r.last_seen_at == T0 for r in rows)
    assert all(r.payload_s3_key in store.objects for r in rows)
    assert board(migrated_engine, board_id).last_ok_at == T0


def test_unchanged_postings_are_not_stored_again(migrated_engine: Engine, board_id: int) -> None:
    store, clock, source = MemoryRawStore(), Clock(), Source(200, truelayer())
    crawl_board(migrated_engine, board_id, source, store, clock)
    clock.advance()

    result = crawl_board(migrated_engine, board_id, source, store, clock)

    assert (result.new_postings, result.changed_postings) == (0, 0)
    assert len(store.objects) == 3
    rows = postings(migrated_engine)
    assert all(r.first_seen_at == T0 and r.last_seen_at == clock.now for r in rows)


def test_changed_posting_gets_a_new_payload(migrated_engine: Engine, board_id: int) -> None:
    store, clock = MemoryRawStore(), Clock()
    crawl_board(migrated_engine, board_id, Source(200, truelayer()), store, clock)

    data = json.loads(truelayer())
    data["jobs"][0]["title"] = "Senior Customer Success Manager - iGaming"
    clock.advance()
    result = crawl_board(
        migrated_engine, board_id, Source(200, json.dumps(data).encode()), store, clock
    )

    assert result.changed_postings == 1
    assert len(store.objects) == 4


@pytest.mark.parametrize(
    ("status", "body", "outcome"),
    [(500, b"oops", "http_error"), (429, b"", "rate_limited"), (200, b"<html/>", "parse_error")],
)
def test_failed_fetch_changes_no_posting(
    migrated_engine: Engine, board_id: int, status: int, body: bytes, outcome: str
) -> None:
    store, clock = MemoryRawStore(), Clock()
    crawl_board(migrated_engine, board_id, Source(200, truelayer()), store, clock)
    before = [(r.external_id, r.last_seen_at, r.content_hash) for r in postings(migrated_engine)]
    clock.advance()

    result = crawl_board(migrated_engine, board_id, Source(status, body), store, clock)

    assert result.outcome == outcome
    after = [(r.external_id, r.last_seen_at, r.content_hash) for r in postings(migrated_engine)]
    assert after == before
    current = board(migrated_engine, board_id)
    assert current.consecutive_failures == 1
    assert current.last_ok_at == T0


def test_board_pauses_after_repeated_failures(migrated_engine: Engine, board_id: int) -> None:
    store, clock = MemoryRawStore(), Clock()
    for _ in range(PAUSE_AFTER_FAILURES):
        crawl_board(migrated_engine, board_id, Source(500, b""), store, clock)
        clock.advance()

    paused = board(migrated_engine, board_id)
    assert paused.consecutive_failures == PAUSE_AFTER_FAILURES
    assert paused.paused_until is not None and paused.paused_until > clock.now

    crawl_board(migrated_engine, board_id, Source(200, truelayer()), store, clock)
    recovered = board(migrated_engine, board_id)
    assert (recovered.consecutive_failures, recovered.paused_until) == (0, None)


def test_not_modified_board_counts_as_seen(migrated_engine: Engine, board_id: int) -> None:
    store, clock, source = MemoryRawStore(), Clock(), Source(200, truelayer(), etag='W/"v1"')
    crawl_board(migrated_engine, board_id, source, store, clock)
    assert board(migrated_engine, board_id).etag == 'W/"v1"'
    clock.advance()

    result = crawl_board(migrated_engine, board_id, source, store, clock)

    assert (result.outcome, result.http_status, result.postings_seen) == ("ok", 304, 3)
    assert all(r.last_seen_at == clock.now for r in postings(migrated_engine))


def test_every_attempt_is_a_crawl_run(migrated_engine: Engine, board_id: int) -> None:
    store, clock = MemoryRawStore(), Clock()
    crawl_board(migrated_engine, board_id, Source(200, truelayer()), store, clock)
    crawl_board(migrated_engine, board_id, Source(500, b""), store, clock)

    with Session(migrated_engine) as session:
        outcomes = session.scalars(select(CrawlRun.outcome).order_by(CrawlRun.id)).all()
        assert session.scalar(select(func.count()).select_from(CrawlRun)) == 2
    assert outcomes == ["ok", "http_error"]


@pytest.mark.parametrize(
    ("outcome", "status", "retryable"),
    [("timeout", None, True), ("rate_limited", 429, True), ("http_error", 503, True),
     ("http_error", 404, False), ("parse_error", 200, False)],
)  # fmt: skip
def test_which_failures_are_retried(outcome: str, status: int | None, retryable: bool) -> None:
    from erio_ingest.pipeline import CrawlResult

    assert CrawlResult(1, outcome, status, 0).retryable is retryable


def test_quiet_boards_slow_down_and_speed_up_on_change(
    migrated_engine: Engine, board_id: int
) -> None:
    store, clock, source = MemoryRawStore(), Clock(), Source(200, truelayer())
    crawl_board(migrated_engine, board_id, source, store, clock)
    assert board(migrated_engine, board_id).cadence_min == 15

    clock.advance(minutes=7 * 24 * 60)
    crawl_board(migrated_engine, board_id, source, store, clock)
    assert board(migrated_engine, board_id).cadence_min == 60

    data = json.loads(truelayer())
    data["jobs"][0]["title"] = "Changed title"
    clock.advance()
    crawl_board(migrated_engine, board_id, Source(200, json.dumps(data).encode()), store, clock)
    assert board(migrated_engine, board_id).cadence_min == 15


def test_payloads_are_stored_before_the_transaction_that_records_them(
    migrated_engine: Engine, board_id: int
) -> None:
    class Probe(MemoryRawStore):
        """Tries to lock the board and its postings while a payload is being stored."""

        def put_posting(self, posting: RawPostingData) -> str:
            with migrated_engine.connect() as connection:  # fails at once if a lock is held
                connection.execute(text("select id from company_boards for update nowait")).all()
                connection.execute(text("select id from raw_postings for update nowait")).all()
            return super().put_posting(posting)

    result = crawl_board(migrated_engine, board_id, Source(200, truelayer()), Probe(), Clock())

    assert (result.outcome, result.new_postings) == ("ok", 3)
    assert all(p.payload_s3_key for p in postings(migrated_engine))
