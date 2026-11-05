from pathlib import Path

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from erio_core.db.models import Company, CompanyBoard, Job, RawPosting
from erio_core.search.index import client
from erio_ingest.demo import load
from erio_ingest.storage import MemoryRawStore

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"


def test_loads_the_recorded_jobs_end_to_end(migrated_engine: Engine, search_alias: str) -> None:
    counts = load(migrated_engine, FIXTURES, MemoryRawStore(), client(), search_alias)

    assert counts == {"postings": 7, "jobs": 7, "indexed": 7}
    with Session(migrated_engine) as session:
        countries = set(session.scalars(select(Job.country_code)))
    assert {"GB", "NG"} <= countries
    assert client().count(index=search_alias)["count"] == 7


def test_refuses_to_mix_with_real_crawls(migrated_engine: Engine, search_alias: str) -> None:
    load(migrated_engine, FIXTURES, MemoryRawStore(), client(), search_alias)
    with Session(migrated_engine) as session, session.begin():
        company = session.scalars(select(Company)).first()
        assert company is not None
        board = CompanyBoard(company_id=company.id, source_slug="greenhouse", board_token="stripe")
        session.add(board)
        session.flush()
        session.add(
            RawPosting(
                source_slug="greenhouse",
                board_id=board.id,
                external_id="real-1",
                content_hash="0" * 64,
                first_seen_at=func.now(),
                last_seen_at=func.now(),
            )
        )
    with pytest.raises(SystemExit, match="refusing"):
        load(migrated_engine, FIXTURES, MemoryRawStore(), client(), search_alias)
