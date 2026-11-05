"""Pipeline metrics read from Postgres and Redis (spec section 10)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from erio_core.db.models import (
    Company,
    CompanyBoard,
    CrawlRun,
    Job,
    JobSource,
    RawPosting,
    SourceCheck,
)  # fmt: skip
from erio_core.db.seed import sync_countries, sync_sources
from erio_ingest.metrics import PipelineCollector

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


class FakeRedis:
    def get(self, key: str) -> bytes:
        return (NOW - timedelta(seconds=40)).isoformat().encode()

    def llen(self, key: str) -> int:
        return 12


def samples(engine: Engine) -> dict[tuple[str, tuple[str, ...]], float]:
    collector = PipelineCollector(engine, FakeRedis(), lambda: NOW)  # type: ignore[arg-type]
    return {
        (s.name, tuple(s.labels.values())): s.value
        for family in collector.collect()
        for s in family.samples
    }


def test_source_index_queue_and_freshness_metrics(migrated_engine: Engine) -> None:
    sync_countries(migrated_engine)
    sync_sources(migrated_engine)
    with Session(migrated_engine) as session, session.begin():
        company = Company(name="Kavak", domain="kavak.com")
        session.add(company)
        session.flush()
        board = CompanyBoard(
            company_id=company.id, source_slug="lever", board_token="kavak",
            last_ok_at=NOW - timedelta(minutes=10),
        )  # fmt: skip
        session.add(board)
        session.flush()
        for minutes, outcome, seconds in [
            (5, "ok", 2),
            (20, "ok", 4),
            (35, "timeout", 20),
            (90, "ok", 1),
        ]:
            started = NOW - timedelta(minutes=minutes)
            session.add(
                CrawlRun(
                    board_id=board.id, started_at=started,
                    finished_at=started + timedelta(seconds=seconds), outcome=outcome,
                    postings_seen=10 if outcome == "ok" else None, postings_new=1,
                    postings_closed=2, postings_reopened=0,
                )
            )  # fmt: skip
        session.add(SourceCheck(source_slug="lever", checked_at=NOW, ok=False))
        posting = RawPosting(
            source_slug="lever", board_id=board.id, external_id="1", content_hash="0" * 64,
            first_seen_at=NOW - timedelta(minutes=8), last_seen_at=NOW,
        )  # fmt: skip
        session.add(posting)
        session.add(
            Job(
                canonical_id="j_1", title="Engineer", company_id=company.id,
                remote_status="onsite", apply_url="https://x.test", status="open",
                searchable_at=NOW - timedelta(minutes=2), freshness_seconds=360,
            )
        )  # fmt: skip
        session.flush()
        session.add(JobSource(job_id="j_1", raw_posting_id=posting.id, is_primary=True))

    got = samples(migrated_engine)

    # The run 90 minutes ago is outside the one-hour window.
    assert got[("erio_source_fetches", ("lever", "ok"))] == 2
    assert got[("erio_source_fetches", ("lever", "timeout"))] == 1
    assert got[("erio_source_fetch_success_ratio", ("lever",))] == 2 / 3
    assert got[("erio_source_fetch_seconds", ("lever", "0.5"))] == 4
    assert got[("erio_source_postings", ("lever", "seen"))] == 20
    assert got[("erio_source_postings", ("lever", "closed"))] == 6
    assert got[("erio_source_seconds_since_success", ("lever",))] == 600
    assert got[("erio_source_smoke_ok", ("lever",))] == 0
    assert got[("erio_index_lag_seconds", ())] == 40
    assert got[("erio_queue_backlog", ("crawl",))] == 12
    assert got[("erio_jobs", ("open",))] == 1
    assert got[("erio_freshness_seconds", ("0.5",))] == 360
    # A source with no runs still reports its postings (as zero), not a ratio.
    assert got[("erio_source_postings", ("greenhouse", "seen"))] == 0
    assert ("erio_source_fetch_success_ratio", ("greenhouse",)) not in got
