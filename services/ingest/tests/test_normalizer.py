"""Normalizer tests: real recorded postings, crawled and normalized on Postgres."""

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, func, select, text, update
from sqlalchemy.orm import Session

from erio_core.connectors import FetchResponse
from erio_core.db.models import Company, CompanyBoard, FxRate, Job, JobSource, RawPosting
from erio_core.db.seed import sync_countries, sync_sources
from erio_ingest.normalizer import latest_rates, normalize_pending
from erio_ingest.pipeline import crawl_board
from erio_ingest.storage import MemoryRawStore

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "greenhouse"
T0 = datetime(2026, 11, 5, 9, 0, tzinfo=UTC)


class Board:
    def __init__(self, body: bytes):
        self.body = body

    def get(self, url: str, etag: str | None = None) -> FetchResponse:
        return FetchResponse(200, self.body)


@pytest.fixture
def setup(migrated_engine: Engine) -> tuple[Engine, MemoryRawStore, int]:
    sync_countries(migrated_engine)
    sync_sources(migrated_engine)
    with Session(migrated_engine) as session, session.begin():
        company = Company(name="Moniepoint", domain="moniepoint.com")
        session.add(company)
        session.flush()
        board = CompanyBoard(
            company_id=company.id, source_slug="greenhouse", board_token="moniepoint"
        )
        session.add(board)
        session.add_all(
            [
                FxRate(day=date(2026, 11, 4), currency="GBP", usd_per_unit=1.30, source="ecb"),
                FxRate(day=date(2026, 11, 3), currency="GBP", usd_per_unit=1.20, source="ecb"),
                FxRate(
                    day=date(2026, 11, 4), currency="NGN", usd_per_unit=0.0007, source="fallback"
                ),
            ]
        )
        session.flush()
        board_id = board.id
    store = MemoryRawStore()
    crawl_board(migrated_engine, board_id, Board(fixture()), store, lambda: T0)
    return migrated_engine, store, board_id


def fixture() -> bytes:
    return (FIXTURES / "moniepoint.json").read_bytes()


def jobs(engine: Engine) -> dict[str, Job]:
    with Session(engine) as session:
        return {j.location_text or "": j for j in session.scalars(select(Job))}


def test_latest_rate_per_currency(setup: tuple[Engine, MemoryRawStore, int]) -> None:
    engine, _, _ = setup
    with Session(engine) as session:
        assert latest_rates(session) == {"GBP": 1.30, "NGN": 0.0007}


def test_every_posting_becomes_a_linked_job(setup: tuple[Engine, MemoryRawStore, int]) -> None:
    engine, store, _ = setup

    result = normalize_pending(engine, store, lambda: T0)

    assert (result.jobs, result.failed) == (4, [])
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Job)) == 4
        assert session.scalar(select(func.count()).select_from(JobSource)) == 4
        assert (
            session.scalars(select(RawPosting.normalized_hash)).all()
            == session.scalars(select(RawPosting.content_hash)).all()
        )

    found = jobs(engine)
    remote = found["Remote, Nigeria"]
    assert (remote.remote_status, remote.remote_scope, remote.eligible_country_codes) == (
        "remote", "country", ["NG"],
    )  # fmt: skip
    assert found["Bauchi, Nigeria"].country_code == "NG"
    assert found["London, United Kingdom"].country_code == "GB"
    assert found["Remote, Poland"].eligible_country_codes == ["PL"]
    assert {j.status for j in found.values()} == {"open"}
    assert all(j.last_verified_at == T0 and j.company_id for j in found.values())


def test_nothing_left_to_do_on_a_second_run(setup: tuple[Engine, MemoryRawStore, int]) -> None:
    engine, store, _ = setup
    normalize_pending(engine, store, lambda: T0)
    assert normalize_pending(engine, store, lambda: T0).jobs == 0


def test_changed_posting_is_normalized_again(setup: tuple[Engine, MemoryRawStore, int]) -> None:
    engine, store, board_id = setup
    normalize_pending(engine, store, lambda: T0)

    data = json.loads(fixture())
    data["jobs"][0]["title"] = "URGENT: Senior Business Relationship Manager (Anambra)"
    later = T0 + timedelta(minutes=15)
    crawl_board(engine, board_id, Board(json.dumps(data).encode()), store, lambda: later)

    assert normalize_pending(engine, store, lambda: later).jobs == 1
    titles = {j.title for j in jobs(engine).values()}
    assert "Senior Business Relationship Manager (Anambra)" in titles


def test_unresolvable_location_goes_to_review(setup: tuple[Engine, MemoryRawStore, int]) -> None:
    engine, store, board_id = setup
    data = json.loads(fixture())
    data["jobs"] = data["jobs"][:1]
    data["jobs"][0]["location"]["name"] = "N/A"
    data["jobs"][0]["offices"] = []
    data["meta"]["total"] = 1
    with Session(engine) as session, session.begin():
        session.execute(update(RawPosting).values(normalized_hash=RawPosting.content_hash))
    crawl_board(engine, board_id, Board(json.dumps(data).encode()), store, lambda: T0)

    result = normalize_pending(engine, store, lambda: T0)

    assert (result.jobs, result.needs_review) == (1, 1)
    flagged = jobs(engine)["N/A"]
    assert flagged.review_reason and flagged.country_code is None


def test_one_bad_posting_does_not_stop_the_batch(setup: tuple[Engine, MemoryRawStore, int]) -> None:
    engine, store, _ = setup
    with Session(engine) as session, session.begin():
        first = session.scalars(select(RawPosting).order_by(RawPosting.id)).first()
        assert first is not None
        first.payload_s3_key = "postings/missing.json.gz"

    result = normalize_pending(engine, store, lambda: T0)

    assert result.jobs == 3
    assert len(result.failed) == 1 and "missing" in result.failed[0]
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Job)) == 3


def test_salary_is_converted_to_usd(setup: tuple[Engine, MemoryRawStore, int]) -> None:
    engine, store, board_id = setup
    data = json.loads(fixture())
    data["jobs"] = data["jobs"][:1]
    data["jobs"][0]["content"] = "&lt;p&gt;Salary: ₦3.5M–₦5M/mo&lt;/p&gt;"
    data["meta"]["total"] = 1
    crawl_board(engine, board_id, Board(json.dumps(data).encode()), store, lambda: T0)
    normalize_pending(engine, store, lambda: T0)

    with Session(engine) as session:
        job = session.scalars(select(Job).where(Job.salary_currency == "NGN")).one()
    assert (job.salary_min, job.salary_max, job.salary_period) == (3_500_000, 5_000_000, "month")
    assert job.salary_usd_annual_min == 29_400


def test_payloads_are_read_with_no_row_locks_held(
    setup: tuple[Engine, MemoryRawStore, int],
) -> None:
    engine, store, _ = setup

    class Probe(MemoryRawStore):
        """Tries to lock every raw posting while the normalizer is reading from storage."""

        def get_posting(self, key: str) -> dict[str, Any]:
            with engine.connect() as connection:  # fails at once if a row lock is held
                connection.execute(text("select id from raw_postings for update nowait")).all()
            return super().get_posting(key)

    probe = Probe()
    probe.objects = store.objects

    result = normalize_pending(engine, probe, lambda: T0)

    assert (result.jobs, result.failed) == (4, [])
