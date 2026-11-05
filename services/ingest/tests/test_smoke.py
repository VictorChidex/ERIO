import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from erio_core.connectors import CONNECTORS, FetchResponse
from erio_core.db.models import SourceCheck
from erio_core.db.seed import sync_boards, sync_sources
from erio_ingest.report import coverage
from erio_ingest.smoke import smoke_test_sources

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"
NOW = datetime(2026, 11, 5, 3, 0, tzinfo=UTC)
# One seeded board per live source, answered from a recorded fixture.
RECORDED = {
    "greenhouse": ("stripe", "greenhouse/truelayer"),
    "lever": ("kavak", "lever/kavak"),
    "ashby": ("andela", "ashby/andela"),
    "recruitee": ("channable", "recruitee/channable"),
    "workable": ("huggingface", "workable/huggingface"),
}


class Recorded:
    def __init__(self, broken: str | None = None):
        self.responses = {
            CONNECTORS[source].board_url(token): FetchResponse(
                200,
                b"<html>down</html>"
                if source == broken
                else (FIXTURES / f"{path}.json").read_bytes(),
            )
            for source, (token, path) in RECORDED.items()
        }

    def get(self, url: str, etag: str | None = None) -> FetchResponse:
        return self.responses.get(url, FetchResponse(404, b"{}"))


@pytest.fixture
def seeded(migrated_engine: Engine) -> Engine:
    sync_sources(migrated_engine)
    sync_boards(migrated_engine)
    return migrated_engine


def test_checks_every_live_source_and_records_it(seeded: Engine) -> None:
    checks = smoke_test_sources(seeded, Recorded(), lambda: NOW)

    assert {c.source: c.ok for c in checks} == dict.fromkeys(RECORDED, True)
    assert all(c.postings for c in checks)
    with Session(seeded) as session:
        rows = session.scalars(select(SourceCheck)).all()
    assert {(row.source_slug, row.ok) for row in rows} == {(s, True) for s in RECORDED}


def test_a_broken_source_fails_alone_and_raises_an_alert(
    seeded: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR):
        checks = smoke_test_sources(seeded, Recorded(broken="ashby"), lambda: NOW)

    failed = [c for c in checks if not c.ok]
    assert [c.source for c in failed] == ["ashby"]
    assert (failed[0].error or "").startswith("parse_error")
    assert "source smoke test failed: source=ashby" in caplog.text
    report = {line.source: line.smoke_ok for line in coverage(seeded, NOW).sources}
    assert report["ashby"] is False
    assert report["lever"] is True
    assert report["smartrecruiters"] is None  # paused: not tested
