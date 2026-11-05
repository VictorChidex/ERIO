"""Load a small, known set of jobs from recorded fixtures, with no network.

Runs the real pipeline (crawl, normalize, index) on fixtures/greenhouse/*.json
so CI and fresh local stacks have predictable jobs to test against:

    docker compose run --rm -v "$PWD/fixtures:/app/fixtures:ro" worker \
        python -m erio_ingest.demo /app/fixtures

It refuses to run when the database already holds postings from real
crawls: recorded postings share IDs with live ones and would mark them
missing.
"""

import sys
from datetime import UTC, datetime
from pathlib import Path

from opensearchpy import OpenSearch
from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.orm import Session

from erio_core.connectors import FetchResponse
from erio_core.db.models import Company, CompanyBoard, RawPosting
from erio_core.db.seed import sync_countries, sync_sources
from erio_core.normalize.fx import parse_ecb, parse_fallback
from erio_core.search.index import client
from erio_core.settings import get_settings
from erio_ingest.fx import store_rates
from erio_ingest.indexer import sync_changed
from erio_ingest.normalizer import normalize_pending
from erio_ingest.pipeline import crawl_board
from erio_ingest.storage import RawStore, S3RawStore

DEMO_PREFIX = "demo-"
COMPANIES = {
    "truelayer": ("TrueLayer", "truelayer.com"),
    "moniepoint": ("Moniepoint", "moniepoint.com"),
}


class FixtureFetcher:
    def __init__(self, body: bytes):
        self.body = body

    def get(self, url: str, etag: str | None = None) -> FetchResponse:
        return FetchResponse(200, self.body)


def _check_empty(engine: Engine) -> None:
    with Session(engine) as session:
        real = session.scalar(
            select(func.count())
            .select_from(RawPosting)
            .join(CompanyBoard, CompanyBoard.id == RawPosting.board_id)
            .where(CompanyBoard.board_token.not_like(f"{DEMO_PREFIX}%"))
        )
    if real:
        raise SystemExit(f"refusing to load demo data: {real} postings from real crawls exist")


def load(
    engine: Engine, fixtures: Path, store: RawStore, search: OpenSearch, alias: str
) -> dict[str, int]:
    _check_empty(engine)
    sync_countries(engine)
    sync_sources(engine)
    ecb_day, ecb = parse_ecb((fixtures / "fx" / "ecb-daily.xml").read_bytes())
    store_rates(engine, ecb_day, ecb, "ecb")
    fallback_day, fallback = parse_fallback((fixtures / "fx" / "er-api-usd.json").read_bytes())
    store_rates(
        engine,
        fallback_day,
        {c: r for c, r in fallback.items() if c not in ecb},
        "exchangerate-api",
    )

    crawled = 0
    for name, (company_name, domain) in COMPANIES.items():
        with Session(engine) as session, session.begin():
            company = session.scalar(select(Company).where(Company.domain == domain))
            if company is None:
                company = Company(name=company_name, domain=domain)
                session.add(company)
                session.flush()
            token = f"{DEMO_PREFIX}{name}"
            board = session.scalar(select(CompanyBoard).where(CompanyBoard.board_token == token))
            if board is None:
                board = CompanyBoard(
                    company_id=company.id, source_slug="greenhouse", board_token=token
                )
                session.add(board)
                session.flush()
            board_id = board.id
        body = (fixtures / "greenhouse" / f"{name}.json").read_bytes()
        result = crawl_board(engine, board_id, FixtureFetcher(body), store)
        crawled += result.postings_seen

    normalized = normalize_pending(engine, store, lambda: datetime.now(UTC)).jobs
    indexed = sync_changed(engine, search, alias, None).indexed
    return {"postings": crawled, "jobs": normalized, "indexed": indexed}


def main() -> None:
    fixtures = Path(sys.argv[1] if len(sys.argv) > 1 else "fixtures")
    engine = create_engine(get_settings().sqlalchemy_url)
    try:
        settings = get_settings()
        counts = load(engine, fixtures, S3RawStore(settings), client(), settings.search_alias)
    finally:
        engine.dispose()
    postings, jobs, indexed = counts["postings"], counts["jobs"], counts["indexed"]
    print(f"demo data: {postings} postings, {jobs} jobs, {indexed} indexed")


if __name__ == "__main__":
    main()
