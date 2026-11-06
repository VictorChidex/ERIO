"""Nightly live smoke test: one real board per source, end to end.

Fetches a board each source is known to serve, through the same polite
fetcher the crawler uses, and parses every posting. A source passes when
the board answers and at least one posting parses. Each result is stored in
``source_checks``; a failure is also logged at ERROR with ``source smoke
test failed``, the line production alerting watches.
"""

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from erio_core.connectors import CONNECTORS, Connector, Fetcher, FetchError
from erio_core.data import example_boards
from erio_core.db.models import CompanyBoard, Source, SourceCheck

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Check:
    source: str
    board_token: str | None
    ok: bool
    postings: int | None
    error: str | None


def canary_board(session: Session, source: str) -> str | None:
    """The board on ``source`` that last fetched cleanly; any board if none has;
    and, for a platform with no registered board yet, its first known example board
    (platforms.json), so every connector is tested live every night."""
    registered = session.scalar(
        select(CompanyBoard.board_token)
        .where(CompanyBoard.source_slug == source)
        .order_by(CompanyBoard.last_ok_at.desc().nulls_last(), CompanyBoard.id)
        .limit(1)
    )
    return registered or next(iter(example_boards().get(source, [])), None)


def check_source(connector: Connector, fetcher: Fetcher, token: str | None) -> Check:
    if token is None:
        return Check(connector.slug, None, False, None, "no board to test")
    try:
        postings = connector.list_postings(fetcher, token).postings
        for raw in postings:
            connector.parse(raw)
    except FetchError as error:
        return Check(connector.slug, token, False, None, f"{error.outcome}: {error}")
    except Exception as error:
        return Check(connector.slug, token, False, None, f"parse failed: {error!r}"[:500])
    if not postings:
        return Check(connector.slug, token, False, 0, "board listed no postings")
    return Check(connector.slug, token, True, len(postings), None)


def smoke_test_sources(
    engine: Engine,
    fetcher: Fetcher,
    now: Callable[[], datetime],
    connectors: Mapping[str, Connector] = CONNECTORS,
) -> list[Check]:
    with Session(engine) as session:
        sources = session.scalars(
            select(Source.slug).where(Source.status != "paused").order_by(Source.slug)
        ).all()
        tokens = {slug: canary_board(session, slug) for slug in sources if slug in connectors}
    checks = [check_source(connectors[slug], fetcher, token) for slug, token in tokens.items()]
    with Session(engine) as session, session.begin():
        for check in checks:
            session.add(
                SourceCheck(
                    source_slug=check.source,
                    board_token=check.board_token,
                    checked_at=now(),
                    ok=check.ok,
                    postings=check.postings,
                    error=check.error,
                )
            )
            if not check.ok:
                log.error(
                    "source smoke test failed: source=%s board=%s error=%s",
                    check.source, check.board_token, check.error,
                )  # fmt: skip
    return checks
