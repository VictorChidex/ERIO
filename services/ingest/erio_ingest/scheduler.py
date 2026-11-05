"""Queue every board whose next crawl is due (run every minute by Celery beat).

A board is due when ``next_crawl_at`` has passed, it is not paused, its
source is not paused, and a connector exists for its source. Queuing moves
``next_crawl_at`` forward by the board's cadence in the same transaction,
with rows locked SKIP LOCKED, so two schedulers never queue a board twice.
"""

from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import Engine, or_, select
from sqlalchemy.orm import Session

from erio_core.connectors import CONNECTORS
from erio_core.db.models import CompanyBoard, Source

Enqueue = Callable[[int], None]

MAX_PER_TICK = 500


def schedule_due_boards(engine: Engine, enqueue: Enqueue, now: datetime) -> list[int]:
    with Session(engine) as session, session.begin():
        boards = session.scalars(
            select(CompanyBoard)
            .join(Source, Source.slug == CompanyBoard.source_slug)
            .where(
                CompanyBoard.next_crawl_at <= now,
                or_(CompanyBoard.paused_until.is_(None), CompanyBoard.paused_until <= now),
                Source.status != "paused",
                CompanyBoard.source_slug.in_(list(CONNECTORS)),
            )
            .order_by(CompanyBoard.next_crawl_at)
            .limit(MAX_PER_TICK)
            .with_for_update(of=CompanyBoard, skip_locked=True)
        ).all()
        for board in boards:
            board.next_crawl_at = now + timedelta(minutes=board.cadence_min)
        queued = [board.id for board in boards]

    # Queue only after the commit, so a worker never sees the old next_crawl_at.
    for board_id in queued:
        enqueue(board_id)
    return queued
