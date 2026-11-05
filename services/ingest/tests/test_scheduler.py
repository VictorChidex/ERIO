from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from erio_core.db.models import CompanyBoard, Source
from erio_core.db.seed import sync_boards, sync_sources
from erio_ingest.scheduler import schedule_due_boards

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


@pytest.fixture
def boards(migrated_engine: Engine) -> list[int]:
    sync_sources(migrated_engine)
    sync_boards(migrated_engine)
    with Session(migrated_engine) as session, session.begin():
        session.execute(update(CompanyBoard).values(next_crawl_at=NOW - timedelta(minutes=1)))
        return list(session.scalars(select(CompanyBoard.id).order_by(CompanyBoard.id)))


def run(engine: Engine, now: datetime = NOW) -> list[int]:
    queued: list[int] = []
    schedule_due_boards(engine, queued.append, now)
    return queued


def test_queues_every_due_board_once(migrated_engine: Engine, boards: list[int]) -> None:
    assert sorted(run(migrated_engine)) == boards
    # Queuing moved each board's next crawl forward, so nothing is due now.
    assert run(migrated_engine) == []


def test_next_crawl_follows_the_board_cadence(migrated_engine: Engine, boards: list[int]) -> None:
    with Session(migrated_engine) as session, session.begin():
        session.get_one(CompanyBoard, boards[0]).cadence_min = 60
    run(migrated_engine)

    assert sorted(run(migrated_engine, NOW + timedelta(minutes=15))) == boards[1:]
    assert sorted(run(migrated_engine, NOW + timedelta(minutes=60))) == boards


def test_skips_paused_boards_until_their_pause_ends(
    migrated_engine: Engine, boards: list[int]
) -> None:
    with Session(migrated_engine) as session, session.begin():
        session.get_one(CompanyBoard, boards[0]).paused_until = NOW + timedelta(minutes=30)

    assert boards[0] not in run(migrated_engine)
    assert boards[0] in run(migrated_engine, NOW + timedelta(minutes=31))


def test_skips_paused_sources(migrated_engine: Engine, boards: list[int]) -> None:
    with Session(migrated_engine) as session, session.begin():
        session.execute(update(Source).values(status="paused"))
    assert run(migrated_engine) == []


def test_seeded_boards_span_several_regions(migrated_engine: Engine, boards: list[int]) -> None:
    assert len(boards) == 30
    with Session(migrated_engine) as session:
        tokens = set(session.scalars(select(CompanyBoard.board_token)))
    assert {"moniepoint", "jumia", "gympass", "xendit", "tamara", "monzo"} <= tokens
