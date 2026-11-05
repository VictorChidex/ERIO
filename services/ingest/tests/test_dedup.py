"""Dedup on Postgres: a job posted on Greenhouse and Ashby becomes one job."""

import html
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, func, select, update
from sqlalchemy.orm import Session

from erio_core.connectors import FetchResponse
from erio_core.db.models import Company, CompanyBoard, Job, JobSource, RawPosting
from erio_core.db.seed import sync_countries, sync_sources
from erio_core.search.index import searchable
from erio_ingest import normalizer
from erio_ingest.dedup import DedupResult, dedup_all, recent_merges
from erio_ingest.normalizer import normalize_pending
from erio_ingest.pipeline import crawl_board
from erio_ingest.storage import MemoryRawStore

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "greenhouse"
T0 = datetime(2026, 11, 5, 9, 0, tzinfo=UTC)
LONDON_JOB = "4936062101"


class Board:
    def __init__(self, body: bytes):
        self.body = body

    def get(self, url: str, etag: str | None = None) -> FetchResponse:
        return FetchResponse(200, self.body)


def greenhouse() -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / "moniepoint.json").read_bytes())
    return data


def ashby(published_at: str) -> bytes:
    """Moniepoint's London analytics job as Ashby lists it: no city, a place in the title."""
    source = next(j for j in greenhouse()["jobs"] if str(j["id"]) == LONDON_JOB)
    job = {
        "id": "7d1f0c52-35a8-4a8e-9a43-2f1d0f0f6a11",
        "title": "Analytics Manager - London",
        "department": "Data",
        "location": "United Kingdom",
        "secondaryLocations": [],
        "publishedAt": published_at,
        "isListed": True,
        "workplaceType": "OnSite",
        "address": {"postalAddress": {"addressCountry": "United Kingdom"}},
        "jobUrl": "https://jobs.ashbyhq.com/moniepoint/7d1f0c52-35a8-4a8e-9a43-2f1d0f0f6a11",
        "descriptionHtml": html.unescape(source["content"]),
    }
    return json.dumps({"apiVersion": "1", "jobs": [job]}).encode()


@pytest.fixture
def boards(migrated_engine: Engine) -> tuple[Engine, int, int]:
    sync_countries(migrated_engine)
    sync_sources(migrated_engine)
    with Session(migrated_engine) as session, session.begin():
        company = Company(name="Moniepoint", domain="moniepoint.com")
        session.add(company)
        session.flush()
        boards = [
            CompanyBoard(company_id=company.id, source_slug=slug, board_token="moniepoint")
            for slug in ("greenhouse", "ashby")
        ]
        session.add_all(boards)
        session.flush()
        return migrated_engine, boards[0].id, boards[1].id


def crawl(boards: tuple[Engine, int, int], published_at: str) -> MemoryRawStore:
    engine, greenhouse_id, ashby_id = boards
    store = MemoryRawStore()
    body = json.dumps(greenhouse()).encode()
    crawl_board(engine, greenhouse_id, Board(body), store, lambda: T0)
    crawl_board(engine, ashby_id, Board(ashby(published_at)), store, lambda: T0)
    return store


def links(engine: Engine) -> dict[str, list[tuple[str, bool, str | None]]]:
    with Session(engine) as session:
        rows = session.execute(
            select(JobSource.job_id, RawPosting.source_slug, JobSource.is_primary)
            .add_columns(JobSource.dedup_method)
            .join(RawPosting, RawPosting.id == JobSource.raw_posting_id)
            .order_by(RawPosting.source_slug)
        )
        found: dict[str, list[tuple[str, bool, str | None]]] = {}
        for job_id, source, primary, method in rows:
            found.setdefault(job_id, []).append((source, primary, method))
        return found


def live(engine: Engine) -> dict[str, Job]:
    with Session(engine) as session:
        return {
            job.canonical_id: job
            for job in session.scalars(select(Job).where(Job.merged_into.is_(None)))
        }


def test_cross_posted_job_becomes_one_job_listing_both_sources(
    boards: tuple[Engine, int, int],
) -> None:
    engine = boards[0]
    store = crawl(boards, "2026-08-01T10:00:00.000+00:00")

    result = normalize_pending(engine, store, lambda: T0)

    assert (result.jobs, result.merged, result.failed) == (5, 1, [])
    jobs = live(engine)
    assert len(jobs) == 4
    [(survivor_id, sources)] = [(k, v) for k, v in links(engine).items() if len(v) == 2]
    # Greenhouse published first, so its posting is primary.
    assert sources == [("ashby", False, "simhash"), ("greenhouse", True, None)]
    survivor = jobs[survivor_id]
    assert (survivor.title, survivor.city, survivor.dedup_method) == (
        "Analytics Manager", "London", "simhash",
    )  # fmt: skip
    assert survivor.status == "open"
    with Session(engine) as session:
        merged = session.scalars(select(Job).where(Job.merged_into.is_not(None))).one()
        merged_at = session.scalar(
            select(JobSource.merged_at).where(JobSource.dedup_method.is_not(None))
        )
    assert merged.merged_into == survivor_id
    assert merged_at == T0
    [record] = recent_merges(engine)
    assert (record.job_id, record.method, record.source) == (survivor_id, "simhash", "ashby")
    # The merged job leaves search; the survivor stays.
    assert not searchable({"status": merged.status, "merged_into": merged.merged_into})
    assert searchable({"status": survivor.status, "merged_into": None})


def test_earliest_posting_wins(boards: tuple[Engine, int, int]) -> None:
    engine = boards[0]
    store = crawl(boards, "2026-07-01T10:00:00.000+00:00")

    normalize_pending(engine, store, lambda: T0)

    [sources] = [v for v in links(engine).values() if len(v) == 2]
    assert sources == [("ashby", True, None), ("greenhouse", False, "simhash")]


def test_similar_jobs_in_other_places_stay_apart(boards: tuple[Engine, int, int]) -> None:
    engine = boards[0]
    store = crawl(boards, "2026-08-01T10:00:00.000+00:00")
    normalize_pending(engine, store, lambda: T0)

    titles = sorted((job.title, job.country_code) for job in live(engine).values())
    # Same text, but Poland is not London, and Anambra is not Bauchi.
    assert titles == [
        ("Analytics Manager", "GB"),
        ("Analytics Manager", "PL"),
        ("Business Relationship Manager (Anambra)", "NG"),
        ("Business Relationship Manager (Bauchi)", "NG"),
    ]


def test_merge_survives_a_recrawl(boards: tuple[Engine, int, int]) -> None:
    engine, _, ashby_id = boards
    store = crawl(boards, "2026-08-01T10:00:00.000+00:00")
    normalize_pending(engine, store, lambda: T0)

    later = T0 + timedelta(minutes=15)
    changed = json.loads(ashby("2026-08-01T10:00:00.000+00:00"))
    changed["jobs"][0]["title"] = "Analytics Manager (London)"
    crawl_board(engine, ashby_id, Board(json.dumps(changed).encode()), store, lambda: later)
    result = normalize_pending(engine, store, lambda: later)

    assert (result.jobs, result.merged) == (1, 0)
    assert len(live(engine)) == 4
    assert sorted(len(v) for v in links(engine).values()) == [1, 1, 1, 2]


def test_full_pass_merges_jobs_built_before_dedup(
    boards: tuple[Engine, int, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = boards[0]
    store = crawl(boards, "2026-08-01T10:00:00.000+00:00")
    monkeypatch.setattr(normalizer, "dedup_jobs", lambda *args: DedupResult())
    normalize_pending(engine, store, lambda: T0)
    with Session(engine) as session, session.begin():
        session.execute(update(Job).values(dedup_key=None, simhash=None, updated_at=T0))
    assert len(live(engine)) == 5

    later = T0 + timedelta(minutes=5)
    result = dedup_all(engine, lambda: later)

    assert (result.fingerprinted, result.checked, len(result.merges)) == (5, 5, 1)
    assert len(live(engine)) == 4
    # Only the merged pair changed for the search index; fingerprints alone do not count.
    with Session(engine) as session:
        changed = session.scalar(select(func.count()).where(Job.updated_at == later))
    assert changed == 2
    assert len(dedup_all(engine, lambda: T0).merges) == 0
