"""Board discovery: find the job boards of companies on the seed list.

For each company and source with no board yet, try the board tokens the
company's name and domain suggest ("Hugging Face", huggingface.co ->
huggingface, hugging-face). A token the source answers with a valid board
becomes a company board, crawled from then on. Every try is recorded, found
or not, and a pair is tried again only after ``RETRY_AFTER``, so each
nightly run moves on through the list.
"""

import re
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import Engine, and_, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from erio_core.connectors import CONNECTORS, Connector, Fetcher
from erio_core.db.models import BoardDiscovery, Company, CompanyBoard, Source

RETRY_AFTER = timedelta(days=30)
#: Company-and-source pairs tried per run, so one run stays well under an hour.
BATCH = 200
# Domain endings that say nothing about the company ("nubank.com.br" -> nubank).
DOMAIN_ENDINGS = re.compile(r"(\.(com|co|net|org|io|ai|app|club|so|in|mx|vn|ar))?\.[a-z]{2,}$")
LEGAL_WORDS = re.compile(r"\b(inc|ltd|llc|plc|gmbh|sa|group|technologies|holdings)\b")


def candidate_tokens(name: str, domain: str | None) -> list[str]:
    """Board tokens to try for a company, most likely first."""
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    words = re.findall(r"[a-z0-9]+", LEGAL_WORDS.sub(" ", folded))
    stem = DOMAIN_ENDINGS.sub("", (domain or "").lower())
    tokens = ["".join(words), "-".join(words), re.sub(r"[^a-z0-9-]", "", stem)]
    return [token for token in dict.fromkeys(tokens) if token]


@dataclass
class DiscoveryResult:
    tried: int = 0
    found: dict[str, list[str]] = field(default_factory=dict)  # source -> tokens


def due_pairs(session: Session, now: datetime, limit: int) -> list[tuple[Company, str]]:
    """Company and source pairs with no board, never tried or not tried lately."""
    live_sources = select(Source.slug).where(Source.status != "paused", Source.slug.in_(CONNECTORS))
    has_board = select(CompanyBoard.id).where(
        CompanyBoard.company_id == Company.id, CompanyBoard.source_slug == Source.slug
    )
    rows = session.execute(
        select(Company, Source.slug)
        .join(Source, Source.slug.in_(live_sources))
        .outerjoin(
            BoardDiscovery,
            and_(
                BoardDiscovery.company_id == Company.id, BoardDiscovery.source_slug == Source.slug
            ),
        )
        .where(~has_board.exists())
        .where(or_(BoardDiscovery.tried_at.is_(None), BoardDiscovery.tried_at < now - RETRY_AFTER))
        .order_by(BoardDiscovery.tried_at.asc().nulls_first(), Company.id, Source.slug)
        .limit(limit)
    ).tuples()
    return list(rows)


def discover_boards(
    engine: Engine,
    fetcher: Fetcher,
    now: Callable[[], datetime],
    connectors: Mapping[str, Connector] = CONNECTORS,
    limit: int = BATCH,
) -> DiscoveryResult:
    result = DiscoveryResult()
    with Session(engine) as session:
        pairs = [(company.id, company.name, company.domain, slug)
                 for company, slug in due_pairs(session, now(), limit)]  # fmt: skip
    for company_id, name, domain, slug in pairs:
        token = connectors[slug].discover(fetcher, candidate_tokens(name, domain), company=name)
        with Session(engine) as session, session.begin():
            tried = insert(BoardDiscovery).values(
                company_id=company_id, source_slug=slug, tried_at=now(), board_token=token
            )
            session.execute(
                tried.on_conflict_do_update(
                    index_elements=[BoardDiscovery.company_id, BoardDiscovery.source_slug],
                    set_={"tried_at": tried.excluded.tried_at, "board_token": token},
                )
            )
            if token:
                session.execute(
                    insert(CompanyBoard)
                    .values(company_id=company_id, source_slug=slug, board_token=token)
                    .on_conflict_do_nothing(index_elements=["source_slug", "board_token"])
                )
                result.found.setdefault(slug, []).append(token)
        result.tried += 1
    return result
