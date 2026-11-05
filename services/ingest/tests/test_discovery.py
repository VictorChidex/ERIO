from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine, delete, func, insert, select, update
from sqlalchemy.orm import Session

from erio_core.connectors import CONNECTORS, FetchResponse
from erio_core.db.models import BoardDiscovery, Company, CompanyBoard, Source
from erio_core.db.seed import sync_sources
from erio_ingest.discovery import RETRY_AFTER, candidate_tokens, discover_boards

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"
NOW = datetime(2026, 11, 5, 3, 0, tzinfo=UTC)


class Boards:
    """Answers a few known boards from their fixtures; everything else is 404."""

    def __init__(self, known: dict[str, tuple[str, str]]):
        self.responses = {
            CONNECTORS[source].board_url(token): FetchResponse(
                200, (FIXTURES / source / f"{fixture}.json").read_bytes()
            )
            for token, (source, fixture) in known.items()
        }
        self.requested: list[str] = []

    def get(self, url: str, etag: str | None = None) -> FetchResponse:
        self.requested.append(url)
        return self.responses.get(url, FetchResponse(404, b"{}"))


@pytest.mark.parametrize(
    ("name", "domain", "tokens"),
    [
        ("Hugging Face", "huggingface.co", ["huggingface", "hugging-face"]),
        ("Nubank", "nubank.com.br", ["nubank"]),
        ("Konfío", "konfio.mx", ["konfio"]),
        ("LINE MAN Wongnai", "lmwn.com", ["linemanwongnai", "line-man-wongnai", "lmwn"]),
        ("Acme Technologies Ltd", None, ["acme"]),
        ("M-KOPA", "m-kopa.com", ["mkopa", "m-kopa"]),
    ],
)
def test_candidate_tokens(name: str, domain: str | None, tokens: list[str]) -> None:
    assert candidate_tokens(name, domain) == tokens


@pytest.fixture
def companies(migrated_engine: Engine) -> dict[str, int]:
    sync_sources(migrated_engine)
    rows = [("Hugging Face", "huggingface.co"), ("Kavak", "kavak.com"), ("Nowhere", None)]
    with Session(migrated_engine) as session, session.begin():
        return {
            name: session.scalars(
                insert(Company).values(name=name, domain=domain).returning(Company.id)
            ).one()
            for name, domain in rows
        }


def boards(engine: Engine) -> set[tuple[str, str]]:
    with Session(engine) as session:
        rows = session.execute(select(CompanyBoard.source_slug, CompanyBoard.board_token))
        return {(source, token) for source, token in rows}


def test_finds_boards_on_every_live_source(
    migrated_engine: Engine, companies: dict[str, int]
) -> None:
    fetcher = Boards({"huggingface": ("workable", "huggingface"), "kavak": ("lever", "kavak")})

    result = discover_boards(migrated_engine, fetcher, lambda: NOW)

    # 3 companies x 5 sources: SmartRecruiters is paused.
    assert result.tried == 15
    assert result.found == {"lever": ["kavak"], "workable": ["huggingface"]}
    assert boards(migrated_engine) == {("lever", "kavak"), ("workable", "huggingface")}
    assert not any("smartrecruiters" in url for url in fetcher.requested)
    with Session(migrated_engine) as session:
        assert session.scalar(select(func.count()).select_from(BoardDiscovery)) == 15


def test_does_not_probe_again_until_the_retry_period_ends(
    migrated_engine: Engine, companies: dict[str, int]
) -> None:
    fetcher = Boards({})
    discover_boards(migrated_engine, fetcher, lambda: NOW)
    asked = len(fetcher.requested)

    assert discover_boards(migrated_engine, fetcher, lambda: NOW + timedelta(days=1)).tried == 0
    later = NOW + RETRY_AFTER + timedelta(hours=1)
    assert discover_boards(migrated_engine, fetcher, lambda: later).tried == 15
    assert len(fetcher.requested) == 2 * asked


def test_skips_pairs_that_already_have_a_board(
    migrated_engine: Engine, companies: dict[str, int]
) -> None:
    with Session(migrated_engine) as session, session.begin():
        session.add(
            CompanyBoard(company_id=companies["Kavak"], source_slug="lever", board_token="kavak")
        )
    assert discover_boards(migrated_engine, Boards({}), lambda: NOW).tried == 14


def test_works_through_the_list_in_batches(
    migrated_engine: Engine, companies: dict[str, int]
) -> None:
    with Session(migrated_engine) as session, session.begin():
        session.execute(update(Source).where(Source.slug != "lever").values(status="paused"))
        session.execute(delete(Company).where(Company.name == "Nowhere"))

    first = discover_boards(migrated_engine, Boards({}), lambda: NOW, limit=1)
    second = discover_boards(migrated_engine, Boards({}), lambda: NOW, limit=5)

    assert (first.tried, second.tried) == (1, 1)
