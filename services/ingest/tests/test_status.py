"""Failure-simulation suite for the status rules (spec section 5, step 5).

Every scenario drives the real pipeline on a real Postgres with a scripted
source, then checks job statuses. The core promise: no failed fetch ever
closes a job.
"""

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from erio_core.connectors import FetchResponse
from erio_core.connectors.greenhouse import GreenhouseConnector
from erio_core.db.models import Company, CompanyBoard, Job, JobSource, RawPosting
from erio_core.db.seed import sync_sources
from erio_ingest.pipeline import crawl_board
from erio_ingest.status import mark_unverified
from erio_ingest.storage import MemoryRawStore

FIXTURE = Path(__file__).resolve().parents[3] / "fixtures" / "greenhouse" / "truelayer.json"
T0 = datetime(2026, 11, 5, 9, 0, tzinfo=UTC)

Response = Callable[[], FetchResponse]


def board_json(drop: int | None = None) -> bytes:
    data = json.loads(FIXTURE.read_bytes())
    if drop is not None:
        del data["jobs"][drop]
        data["meta"]["total"] = len(data["jobs"])
    return json.dumps(data).encode()


def ok(drop: int | None = None, etag: str | None = None) -> Response:
    headers = {"ETag": etag} if etag else {}
    return lambda: FetchResponse(200, board_json(drop), headers)


def status(code: int, body: bytes = b"") -> Response:
    return lambda: FetchResponse(code, body)


def timeout() -> FetchResponse:
    raise httpx.ReadTimeout("read timed out")


class Board:
    """A scripted Greenhouse board crawled every 15 minutes."""

    def __init__(self, engine: Engine):
        self.engine = engine
        self.now = T0
        self.store = MemoryRawStore()
        self.response: Response = ok()
        sync_sources(engine)
        with Session(engine) as session, session.begin():
            company = Company(name="TrueLayer", domain="truelayer.com")
            session.add(company)
            session.flush()
            board = CompanyBoard(company_id=company.id, source_slug="greenhouse", board_token="tl")
            session.add(board)
            session.flush()
            self.board_id = board.id
            self.company_id = company.id

    def get(self, url: str, etag: str | None = None) -> FetchResponse:
        assert url == GreenhouseConnector().board_url("tl")
        return self.response()

    def crawl(self, response: Response | None = None, minutes: int = 15) -> str:
        if response is not None:
            self.response = response
        result = crawl_board(self.engine, self.board_id, self, self.store, lambda: self.now)
        self.now += timedelta(minutes=minutes)
        return result.outcome

    def link_jobs(self) -> None:
        """One canonical job per posting (the normalizer does this from step 6)."""
        with Session(self.engine) as session, session.begin():
            for posting in session.scalars(select(RawPosting)):
                job = Job(
                    canonical_id=f"job_{posting.external_id}",
                    title="Job",
                    company_id=self.company_id,
                    remote_status="onsite",
                    apply_url="https://example.com",
                    last_verified_at=posting.last_seen_at,
                )
                session.add(job)
                session.flush()
                session.add(JobSource(job_id=job.canonical_id, raw_posting_id=posting.id))

    def jobs(self) -> dict[str, tuple[str, datetime | None]]:
        with Session(self.engine) as session:
            return {j.canonical_id: (j.status, j.closed_at) for j in session.scalars(select(Job))}

    def statuses(self) -> list[str]:
        return sorted(status for status, _ in self.jobs().values())

    def expire_unverified(self) -> int:
        with Session(self.engine) as session, session.begin():
            return mark_unverified(session, self.now)


@pytest.fixture
def board(migrated_engine: Engine) -> Board:
    b = Board(migrated_engine)
    b.crawl()
    b.link_jobs()
    b.crawl()
    return b


def removed_job_id() -> str:
    return f"job_{json.loads(FIXTURE.read_bytes())['jobs'][0]['id']}"


FAILURES: list[tuple[str, Response]] = [
    ("server error", status(500, b"oops")),
    ("bad gateway", status(502)),
    ("rate limited", status(429)),
    ("forbidden", status(403)),
    ("empty body", status(200)),
    ("html page", status(200, b"<html>maintenance</html>")),
    ("malformed json", status(200, b'{"jobs": [')),
    ("jobs not a list", status(200, b'{"jobs": {}}')),
    ("empty list without total", status(200, b'{"jobs": []}')),
    ("timeout", timeout),
]


@pytest.mark.parametrize(("name", "failure"), FAILURES, ids=[n for n, _ in FAILURES])
def test_no_failed_fetch_ever_closes_a_job(board: Board, name: str, failure: Response) -> None:
    for _ in range(8):  # two hours of failures, every 15 minutes
        assert board.crawl(failure) != "ok"

    assert board.statuses() == ["open", "open", "open"]
    with Session(board.engine) as session:
        assert session.scalars(select(RawPosting.missing_since)).all() == [None, None, None]


def test_mixed_failures_between_successes_close_nothing(board: Board) -> None:
    for _, failure in FAILURES:
        board.crawl(failure)
        board.crawl(ok())
    assert board.statuses() == ["open", "open", "open"]


def test_removed_posting_closes_within_45_minutes(board: Board) -> None:
    removed_at = board.now - timedelta(minutes=5)  # disappears between two crawls
    board.crawl(ok(drop=0))  # first miss
    assert board.jobs()[removed_job_id()][0] == "open"
    board.crawl()  # 15 minutes later: too soon to close
    assert board.jobs()[removed_job_id()][0] == "open"
    board.crawl()  # 30 minutes after the first miss: closed

    job_status, closed_at = board.jobs()[removed_job_id()]
    assert job_status == "closed"
    assert closed_at is not None and closed_at - removed_at <= timedelta(minutes=45)
    assert board.statuses() == ["closed", "open", "open"]


def test_failures_between_misses_do_not_count_as_misses(board: Board) -> None:
    board.crawl(ok(drop=0))  # first miss
    for _ in range(4):
        board.crawl(status(500))  # an hour of failures
    assert board.jobs()[removed_job_id()][0] == "open"
    board.crawl(ok(drop=0))  # the second successful fetch confirms it
    assert board.jobs()[removed_job_id()][0] == "closed"


def test_a_posting_that_comes_back_is_reopened(board: Board) -> None:
    board.crawl(ok(drop=0))
    board.crawl(minutes=30)
    board.crawl()
    assert board.jobs()[removed_job_id()][0] == "closed"

    board.crawl(ok())

    assert board.jobs()[removed_job_id()] == ("open", None)


def test_not_modified_counts_as_a_successful_fetch(board: Board) -> None:
    board.crawl(ok(drop=0, etag='W/"v2"'), minutes=30)  # first miss; ETag stored
    board.crawl(status(304))  # 30 minutes later the board is unchanged: still missing
    assert board.jobs()[removed_job_id()][0] == "closed"
    assert board.statuses() == ["closed", "open", "open"]


def test_a_304_without_our_etag_is_a_failure(board: Board) -> None:
    board.crawl(ok(drop=0), minutes=30)  # first miss; the board sent no ETag
    assert board.crawl(status(304)) == "http_error"
    assert board.jobs()[removed_job_id()][0] == "open"


def test_a_board_that_says_it_is_empty_closes_its_jobs(board: Board) -> None:
    empty = status(200, b'{"jobs": [], "meta": {"total": 0}}')
    board.crawl(empty, minutes=30)
    board.crawl(empty)
    assert board.statuses() == ["closed", "closed", "closed"]


def test_failing_board_keeps_jobs_open_then_unknown_after_72_hours(board: Board) -> None:
    for _ in range(8):  # 500s for two hours
        board.crawl(status(500))
    assert board.expire_unverified() == 0
    assert board.statuses() == ["open", "open", "open"]

    board.now += timedelta(hours=72)
    assert board.expire_unverified() == 3
    assert board.statuses() == ["unknown", "unknown", "unknown"]

    board.crawl(ok())  # the board recovers
    assert board.statuses() == ["open", "open", "open"]
