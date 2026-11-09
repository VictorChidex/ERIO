"""Which company a job gets on multi-employer boards, and the history each job keeps.

Real Postgres, scripted boards: a WP Job Manager site (a multi-employer board) and a
Greenhouse board (a single-employer one) go through the real crawl and normalizer.
"""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, func, select, update
from sqlalchemy.orm import Session

from erio_core.connectors import FetchResponse, get_connector
from erio_core.db.models import Company, CompanyBoard, Job, JobEvent, JobSource, RawPosting
from erio_core.db.seed import sync_countries, sync_sources
from erio_ingest.dedup import dedup_all
from erio_ingest.employers import clean_company_name, company_key, resolve_company
from erio_ingest.normalizer import normalize_pending
from erio_ingest.pipeline import crawl_board
from erio_ingest.status import apply_successful_fetch
from erio_ingest.storage import MemoryRawStore

T0 = datetime(2026, 11, 5, 9, 0, tzinfo=UTC)
GREENHOUSE = Path(__file__).resolve().parents[3] / "fixtures" / "greenhouse" / "moniepoint.json"


def wp_job(
    number: int, company: str | None, title: str = "Head Coach", place: str = "London, UK"
) -> dict[str, Any]:
    return {
        "id": number,
        "link": f"https://sportyjob.example/job/{number}/",
        "date_gmt": "2026-11-01T08:00:00",
        "title": {"rendered": title},
        "content": {"rendered": f"<p>Lead our training groups and plan the season {number}.</p>"},
        "meta": {"_company_name": company, "_job_location": place},
    }


class Site:
    """A WP Job Manager site that answers with whatever list it is given."""

    def __init__(self, jobs: list[dict[str, Any]]):
        self.jobs = jobs

    def get(self, url: str, etag: str | None = None) -> FetchResponse:
        return FetchResponse(200, json.dumps(self.jobs).encode())


@pytest.fixture
def engine(migrated_engine: Engine) -> Engine:
    sync_countries(migrated_engine)
    sync_sources(migrated_engine)
    return migrated_engine


def add_board(
    engine: Engine, source: str, token: str, name: str, name_source: str = "placeholder"
) -> int:
    with Session(engine) as session, session.begin():
        company = Company(name=name, name_source=name_source)
        session.add(company)
        session.flush()
        board = CompanyBoard(company_id=company.id, source_slug=source, board_token=token)
        session.add(board)
        session.flush()
        return board.id


def companies(engine: Engine) -> dict[str, Company]:
    with Session(engine) as session:
        return {c.slug: c for c in session.scalars(select(Company))}


def job_companies(engine: Engine) -> dict[str, str]:
    """Each job's title and external id mapped to its company's slug."""
    with Session(engine) as session:
        rows = session.execute(
            select(RawPosting.external_id, Company.slug)
            .join(JobSource, JobSource.raw_posting_id == RawPosting.id)
            .join(Job, Job.canonical_id == JobSource.job_id)
            .join(Company, Company.id == Job.company_id)
        )
        return {external_id: slug for external_id, slug in rows}


def test_the_connectors_of_job_boards_are_marked_multi_employer() -> None:
    assert get_connector("wp_job_manager").multi_employer
    assert get_connector("smartjobboard").multi_employer
    assert get_connector("nodex").multi_employer
    assert not get_connector("greenhouse").multi_employer
    assert not get_connector("paradox").multi_employer


@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("Acme", "acme"),
        ("ACME Ltd.", "acme"),
        ("Acme, Inc", "acme"),
        ("Acme Pvt. Ltd.", "acme"),
        ("Acme GmbH & Co. KG", "acme"),
        ("Café Müller S.A.", "cafe-muller"),
        ("Acme Sports Limited", "acme-sports"),
        ("Limited", "limited"),
        ("Co Ltd", "co"),
        ("Hugging Face, Inc.", "hugging-face"),
    ],
)
def test_spellings_of_one_company_share_a_key(name: str, key: str) -> None:
    assert company_key(name) == key


@pytest.mark.parametrize("name", [None, "", "  ", "Confidential", "N/A", "---", "Anonymous"])
def test_a_hidden_employer_names_no_company(name: str | None) -> None:
    assert clean_company_name(name) is None


def test_each_job_takes_the_company_its_posting_names(engine: Engine) -> None:
    board_id = add_board(engine, "wp_job_manager", "https://sportyjob.example", "SportyJob")
    site = Site(
        [
            wp_job(1, "Acme Ltd."),
            wp_job(2, "ACME, Inc", title="Fitness Instructor"),
            wp_job(3, "Beta Sports GmbH", title="Physio"),
            wp_job(4, None, title="Referee"),
            wp_job(5, "Confidential", title="Analyst"),
        ]
    )
    store = MemoryRawStore()
    crawl_board(engine, board_id, site, store, lambda: T0)

    result = normalize_pending(engine, store, lambda: T0)

    assert (result.jobs, result.failed) == (5, [])
    assert job_companies(engine) == {
        "1": "acme",
        "2": "acme",
        "3": "beta-sports",
        "4": "sportyjob",  # no name: the board's company
        "5": "sportyjob",  # a hidden name is no name
    }
    found = companies(engine)
    assert found["acme"].name == "Acme Ltd."  # the first spelling seen
    assert found["acme"].name_source == "source"
    assert found["sportyjob"].name_source == "placeholder"  # still the board's own


def test_a_seed_company_is_reused_and_keeps_its_name(engine: Engine) -> None:
    with Session(engine) as session, session.begin():
        session.add(Company(name="Acme", domain="acme.example"))
    board_id = add_board(engine, "wp_job_manager", "https://sportyjob.example", "SportyJob")
    store = MemoryRawStore()
    crawl_board(engine, board_id, Site([wp_job(1, "ACME LIMITED")]), store, lambda: T0)

    normalize_pending(engine, store, lambda: T0)

    found = companies(engine)
    assert sorted(found) == ["acme", "sportyjob"]  # no second Acme
    assert (found["acme"].name, found["acme"].name_source) == ("Acme", "seed")
    assert job_companies(engine) == {"1": "acme"}


def test_a_placeholder_company_found_by_a_board_takes_the_posted_name(engine: Engine) -> None:
    with Session(engine) as session, session.begin():
        session.add(Company(name="Acme", name_source="placeholder"))  # made from a board token
    board_id = add_board(engine, "wp_job_manager", "https://sportyjob.example", "SportyJob")
    store = MemoryRawStore()
    crawl_board(engine, board_id, Site([wp_job(1, "Acme Corporation")]), store, lambda: T0)

    normalize_pending(engine, store, lambda: T0)

    acme = companies(engine)["acme"]
    assert (acme.name, acme.name_source) == ("Acme Corporation", "source")


def test_new_companies_met_by_many_workers_at_once_are_created_once(engine: Engine) -> None:
    def meet(n: int) -> int | None:
        with Session(engine) as session, session.begin():
            return resolve_company(session, ["Zeta Ltd", "ZETA", "Zeta, Inc."][n % 3])

    with ThreadPoolExecutor(8) as pool:
        ids = list(pool.map(meet, range(24)))

    assert len(set(ids)) == 1
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Company)) == 1


def test_a_duplicate_across_two_boards_merges_once_both_name_the_company(
    engine: Engine,
) -> None:
    """Before, each board's jobs lived under the board's company and were never compared."""
    first = add_board(engine, "wp_job_manager", "https://sportyjob.example", "SportyJob")
    second = add_board(engine, "wp_job_manager", "https://othersport.example", "OtherSport")
    store = MemoryRawStore()
    job = wp_job(1, "Acme Ltd.")
    twin = wp_job(2, "ACME Inc")
    twin["content"] = job["content"]  # the same ad, posted on both boards
    crawl_board(engine, first, Site([job]), store, lambda: T0)
    crawl_board(engine, second, Site([twin]), store, lambda: T0)

    result = normalize_pending(engine, store, lambda: T0)
    dedup_all(engine, lambda: T0)

    assert result.failed == []
    with Session(engine) as session:
        live = session.scalars(select(Job).where(Job.merged_into.is_(None))).all()
        assert len(live) == 1
        events = session.scalars(
            select(JobEvent.kind).where(JobEvent.job_id == live[0].canonical_id)
        )
        assert sorted(events) == ["added", "merged"]


class GreenhouseBoard:
    """The recorded Moniepoint board; ``shift`` moves every job id, for a second board."""

    def __init__(self, shift: int = 0):
        self.shift = shift

    def get(self, url: str, etag: str | None = None) -> FetchResponse:
        data = json.loads(GREENHOUSE.read_bytes())
        for job in data["jobs"]:
            job["id"] += self.shift
        return FetchResponse(200, json.dumps(data).encode())


def test_a_placeholder_name_is_replaced_but_a_seed_name_never(engine: Engine) -> None:
    placeholder = add_board(engine, "greenhouse", "moniepoint", "Moniepoint board", "placeholder")
    seed = add_board(engine, "greenhouse", "moniepoint-two", "Our Moniepoint", "seed")
    store = MemoryRawStore()
    crawl_board(engine, placeholder, GreenhouseBoard(), store, lambda: T0)
    crawl_board(engine, seed, GreenhouseBoard(shift=1_000_000), store, lambda: T0)

    normalize_pending(engine, store, lambda: T0, limit=1000)

    with Session(engine) as session:
        rows = session.execute(
            select(CompanyBoard.board_token, Company.name, Company.name_source).join(
                Company, Company.id == CompanyBoard.company_id
            )
        ).all()
    assert sorted(rows) == [
        ("moniepoint", "Moniepoint", "source"),
        ("moniepoint-two", "Our Moniepoint", "seed"),
    ]


def events(engine: Engine, kind: str | None = None) -> list[JobEvent]:
    with Session(engine) as session:
        query = select(JobEvent).order_by(JobEvent.id)
        if kind:
            query = query.where(JobEvent.kind == kind)
        return list(session.scalars(query))


def test_a_new_job_is_added_and_an_unchanged_reread_writes_nothing(engine: Engine) -> None:
    board_id = add_board(engine, "wp_job_manager", "https://sportyjob.example", "SportyJob")
    store = MemoryRawStore()
    crawl_board(engine, board_id, Site([wp_job(1, "Acme")]), store, lambda: T0)
    normalize_pending(engine, store, lambda: T0)

    assert [(e.kind, e.changes) for e in events(engine)] == [("added", {})]

    # Read the same posting again, as a rules change or a backfill does.
    with Session(engine) as session, session.begin():
        session.execute(update(RawPosting).values(normalized_hash=None))
    later = T0 + timedelta(hours=1)
    assert normalize_pending(engine, store, lambda: later).jobs == 1

    assert [e.kind for e in events(engine)] == ["added"]


def test_a_changed_posting_records_each_field_that_moved(engine: Engine) -> None:
    board_id = add_board(engine, "wp_job_manager", "https://sportyjob.example", "SportyJob")
    store = MemoryRawStore()
    crawl_board(engine, board_id, Site([wp_job(1, "Acme")]), store, lambda: T0)
    normalize_pending(engine, store, lambda: T0)

    later = T0 + timedelta(hours=1)
    changed = wp_job(1, "Acme", title="Senior Coach", place="Paris, France")
    crawl_board(engine, board_id, Site([changed]), store, lambda: later)
    normalize_pending(engine, store, lambda: later)

    [added, change] = events(engine)
    assert (added.kind, added.at) == ("added", T0)
    assert (change.kind, change.at) == ("changed", later)
    assert change.changes["title"] == ["Head Coach", "Senior Coach"]
    assert change.changes["location_text"] == ["London, UK", "Paris, France"]
    assert change.changes["country_code"] == ["GB", "FR"]
    # A description-only edit moves no tracked field, so it records nothing.
    edited = wp_job(1, "Acme", title="Senior Coach", place="Paris, France")
    edited["content"] = {"rendered": "<p>A different text altogether.</p>"}
    crawl_board(engine, board_id, Site([edited]), store, lambda: later + timedelta(hours=1))
    normalize_pending(engine, store, lambda: later + timedelta(hours=1))
    assert len(events(engine)) == 2


def test_closing_and_reopening_are_recorded_once_each(engine: Engine) -> None:
    board_id = add_board(engine, "wp_job_manager", "https://sportyjob.example", "SportyJob")
    store = MemoryRawStore()
    now = T0
    crawl_board(engine, board_id, Site([wp_job(1, "Acme")]), store, lambda: now)
    normalize_pending(engine, store, lambda: now)

    for minutes in (15, 60, 75):  # missing twice, 30+ minutes apart: closed
        now = T0 + timedelta(minutes=minutes)
        clock = lambda at=now: at  # noqa: E731 (bound now, not the loop variable)
        crawl_board(engine, board_id, Site([]), store, clock)
        normalize_pending(engine, store, clock)
    assert [e.kind for e in events(engine)] == ["added", "closed"]

    now = T0 + timedelta(minutes=90)
    crawl_board(engine, board_id, Site([wp_job(1, "Acme")]), store, lambda: now)
    normalize_pending(engine, store, lambda: now)
    assert [e.kind for e in events(engine)] == ["added", "closed", "reopened"]

    with Session(engine) as session, session.begin():  # a fetch that changes nothing
        apply_successful_fetch(session, board_id, ["1"], now + timedelta(minutes=15))
    assert len(events(engine)) == 3
