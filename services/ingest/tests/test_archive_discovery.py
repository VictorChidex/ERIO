"""Board discovery from the Internet Archive's CDX index, with the archive and the boards faked."""

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from erio_core.connectors import CONNECTORS, FetchResponse
from erio_core.db.models import Company, CompanyBoard, Source
from erio_core.db.seed import sync_sources
from erio_ingest.archive_discovery import (
    PATTERNS,
    MemoryState,
    cdx_url,
    discover_from_archive,
    parse_cdx,
    path_pattern,
    pretty,
    subdomain_pattern,
    tokens_in,
)

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "greenhouse"
NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
GREENHOUSE = path_pattern("boards.greenhouse.io", "greenhouse")
RECRUITEE = subdomain_pattern("recruitee.com", "recruitee")


def cdx(*urls: str, resume: str | None = None) -> bytes:
    rows: list[list[str]] = [["original"], *([u] for u in urls)]
    if resume:
        rows += [[], [resume]]
    return json.dumps(rows).encode()


def test_a_cdx_request_asks_for_one_page_of_archived_addresses() -> None:
    query = parse_qs(urlsplit(cdx_url(GREENHOUSE, 100, "abc def")).query)

    assert query["url"] == ["boards.greenhouse.io/*"]
    assert (query["output"], query["fl"], query["collapse"]) == (["json"], ["original"], ["urlkey"])
    assert query["limit"] == ["100"] and query["resumeKey"] == ["abc def"]
    assert "matchType" not in query
    assert GREENHOUSE.root_filter in query["filter"] and "statuscode:200" in query["filter"]


def test_employers_on_subdomains_are_asked_for_by_domain() -> None:
    query = parse_qs(urlsplit(cdx_url(RECRUITEE)).query)

    assert query["url"] == ["recruitee.com"] and query["matchType"] == ["domain"]
    assert "resumeKey" not in query


def test_a_cdx_answer_gives_its_addresses_and_the_key_of_the_next_page() -> None:
    urls, resume = parse_cdx(cdx("https://boards.greenhouse.io/a", "https://x/y", resume="k1"))

    assert urls == ["https://boards.greenhouse.io/a", "https://x/y"] and resume == "k1"


def test_the_last_cdx_page_has_no_key_and_an_empty_answer_is_no_addresses() -> None:
    assert parse_cdx(cdx("https://boards.greenhouse.io/a")) == (
        ["https://boards.greenhouse.io/a"],
        None,
    )
    assert parse_cdx(b"") == ([], None)
    assert parse_cdx(b"[]") == ([], None)


@pytest.mark.parametrize("body", [b"<html>Temporarily Offline</html>", b'{"a": 1}', b'["x"]'])
def test_an_answer_that_is_not_cdx_is_refused(body: bytes) -> None:
    with pytest.raises(ValueError):
        parse_cdx(body)


def test_tokens_come_from_path_addresses_and_leave_platform_pages_out() -> None:
    urls = [
        "https://boards.greenhouse.io/Acme",
        "http://boards.greenhouse.io/acme/jobs/123",  # the same employer, lower case
        "https://boards.greenhouse.io/embed/job_board?for=x",
        "https://boards.greenhouse.io/robots.txt",
        "https://boards.greenhouse.io/globex-corp?gh_jid=9",
        "https://jobs.lever.co/other",  # another platform
        "https://boards.greenhouse.io/",
    ]

    assert tokens_in(GREENHOUSE, urls) == ["Acme", "globex-corp"]


def test_tokens_come_from_subdomains_and_leave_the_platforms_own_hosts_out() -> None:
    urls = [
        "https://acme.recruitee.com/o/engineer",
        "https://www.recruitee.com/pricing",
        "https://app.recruitee.com/",
        "https://support.recruitee.com/en/articles/1",
        "http://globex.recruitee.com:443/",
        "https://acme.example.org/",
    ]

    assert tokens_in(RECRUITEE, urls) == ["acme", "globex"]


def test_every_pattern_names_a_platform_with_a_connector() -> None:
    assert {p.source for p in PATTERNS} <= set(CONNECTORS)
    assert len({p.key for p in PATTERNS}) == len(PATTERNS)


def test_a_company_name_is_made_from_its_token() -> None:
    assert pretty("acme-corp") == "Acme Corp" and pretty("globex_inc") == "Globex Inc"


class Archive:
    """A fake CDX server: pages by resume key."""

    def __init__(self, pages: dict[str | None, bytes], status: int = 200) -> None:
        self.pages, self.status, self.requests = pages, status, []  # type: ignore[var-annotated]

    def get(self, url: str, etag: str | None = None) -> FetchResponse:
        self.requests.append(url)
        key = parse_qs(urlsplit(url).query).get("resumeKey", [None])[0]
        return FetchResponse(self.status, self.pages.get(key, cdx()))


class Boards:
    """A fake Greenhouse: some tokens have a board, the rest answer 404."""

    def __init__(self, live: set[str]) -> None:
        self.live, self.probed = live, []  # type: ignore[var-annotated]

    def get(self, url: str, etag: str | None = None) -> FetchResponse:
        token = url.split("/boards/")[1].split("/")[0]
        self.probed.append(token)
        if token in self.live:
            return FetchResponse(200, (FIXTURES / "truelayer.json").read_bytes())
        return FetchResponse(404, b'{"error": "Job not found"}')


def run(engine: Engine, archive: Archive, boards: Boards, state: MemoryState, **options):  # type: ignore[no-untyped-def]
    return discover_from_archive(
        engine,
        archive,
        boards,
        state,
        lambda: NOW,
        patterns=[GREENHOUSE],
        **options,
    )


@pytest.fixture
def engine(migrated_engine: Engine) -> Engine:
    sync_sources(migrated_engine)
    return migrated_engine


def test_a_board_the_platform_confirms_becomes_a_company_board(engine: Engine) -> None:
    archive = Archive(
        {None: cdx("https://boards.greenhouse.io/acme", "https://boards.greenhouse.io/ghost")}
    )
    boards, state = Boards({"acme"}), MemoryState()

    result = run(engine, archive, boards, state)

    assert (result.pages, result.candidates, result.probed) == (1, 2, 2)
    assert result.found == {"greenhouse": ["acme"]}
    with Session(engine) as session:
        board = session.scalars(
            select(CompanyBoard).where(CompanyBoard.board_token == "acme")
        ).one()
        assert session.get_one(Company, board.company_id).name == "Acme"
        assert (
            session.scalar(select(CompanyBoard).where(CompanyBoard.board_token == "ghost")) is None
        )
    assert state.rejected("greenhouse", ["ghost", "acme"]) == {"ghost"}


def test_a_rejected_or_known_board_is_not_probed_again(engine: Engine) -> None:
    page = cdx("https://boards.greenhouse.io/acme", "https://boards.greenhouse.io/ghost")
    state = MemoryState()
    run(engine, Archive({None: page}), Boards({"acme"}), state)
    again = Boards({"acme"})

    result = run(engine, Archive({None: page}), again, state)

    assert again.probed == [] and result.probed == 0 and result.found == {}


def test_a_probe_budget_stops_the_run(engine: Engine) -> None:
    urls = [f"https://boards.greenhouse.io/company{n}" for n in range(6)]

    result = run(engine, Archive({None: cdx(*urls)}), Boards(set()), MemoryState(), validate=3)

    assert result.probed == 3


def test_a_read_resumes_where_the_last_run_stopped(engine: Engine) -> None:
    archive = Archive(
        {
            None: cdx("https://boards.greenhouse.io/one", resume="next-page"),
            "next-page": cdx("https://boards.greenhouse.io/two"),
        }
    )
    state = MemoryState()

    first = run(engine, archive, Boards(set()), state, pages=1)
    second = run(engine, archive, Boards(set()), state, pages=1)

    assert (first.probed, second.probed) == (1, 1)
    assert "resumeKey=next-page" in archive.requests[1]
    # The archive was read to the end: it is left alone until the restart period passes.
    third = run(engine, archive, Boards(set()), state, pages=1)
    assert third.pages == 0 and len(archive.requests) == 2


def test_an_archive_that_is_offline_is_an_error_not_a_crash(engine: Engine) -> None:
    result = run(engine, Archive({}, status=503), Boards(set()), MemoryState())

    assert result.pages == 0 and "503" in result.errors[0]


def test_an_answer_that_is_not_cdx_is_reported(engine: Engine) -> None:
    result = run(
        engine, Archive({None: b"<html>Temporarily Offline</html>"}), Boards(set()), MemoryState()
    )

    assert result.pages == 0 and result.errors


def test_a_paused_platform_is_left_alone(engine: Engine) -> None:
    with Session(engine) as session, session.begin():
        session.execute(update(Source).where(Source.slug == "greenhouse").values(status="paused"))
    archive = Archive({None: cdx("https://boards.greenhouse.io/acme")})

    result = run(engine, archive, Boards({"acme"}), MemoryState())

    assert archive.requests == [] and result.found == {}


def test_the_archive_fetcher_waits_as_long_as_the_archive_needs() -> None:
    from erio_core.settings import get_settings
    from erio_ingest.worker import archive_fetcher

    fetcher = archive_fetcher()

    assert fetcher.client.timeout.read == get_settings().archive_timeout_s
    assert fetcher.allowed_hosts == frozenset({"web.archive.org"})


@pytest.mark.parametrize("pattern", PATTERNS, ids=lambda p: p.key)
def test_the_server_side_filter_has_no_python_only_syntax(pattern) -> None:  # type: ignore[no-untyped-def]
    # The CDX server runs Java regular expressions: no named groups or lookbehinds.
    assert pattern.root_filter.startswith("original:https?://")
    assert "(?P" not in pattern.root_filter and "(?<" not in pattern.root_filter


def test_the_filter_keeps_an_employers_board_address_and_drops_its_job_pages() -> None:
    board = re.compile(path_pattern("jobs.lever.co", "lever").root_filter.removeprefix("original:"))

    assert board.match("https://jobs.lever.co/acme")
    assert board.match("http://jobs.lever.co/acme-2/")
    assert not board.match("https://jobs.lever.co/acme/0085d175-c163-4569-95d1")
    assert not board.match("https://jobs.lever.co/acme?lever-via=x")
    assert not board.match("https://jobs.lever.co/%20Foschini")


def test_the_subdomain_filter_keeps_an_employers_home_and_drops_deeper_pages() -> None:
    home = re.compile(RECRUITEE.root_filter.removeprefix("original:"))

    assert home.match("https://acme.recruitee.com/")
    assert home.match("http://globex.recruitee.com")
    assert not home.match("https://acme.recruitee.com/o/engineer")
    assert not home.match("https://www.example.org/")


def test_a_run_that_runs_out_of_budget_mid_page_stays_on_that_page(engine: Engine) -> None:
    urls = [f"https://boards.greenhouse.io/company{n}" for n in range(5)]
    archive = Archive({None: cdx(*urls, resume="page-2"), "page-2": cdx()})
    boards, state = Boards(set()), MemoryState()

    first = run(engine, archive, boards, state, validate=3)
    second = run(engine, archive, boards, state, validate=3, pages=1)

    # The first run probed 3 of 5 and kept its place; the second read the same page again,
    # skipped the 3 already turned away, and probed the 2 that were left.
    assert (first.probed, second.probed) == (3, 2)
    assert sorted(boards.probed) == sorted(f"company{n}" for n in range(5))
    assert "resumeKey" not in archive.requests[1]  # the second run started at the same page
    assert state.resume_key(GREENHOUSE.key)[0] == "page-2"  # and then moved on


def test_a_pass_through_the_archive_is_only_done_when_it_reached_the_end(engine: Engine) -> None:
    state = MemoryState()
    archive = Archive({None: cdx("https://boards.greenhouse.io/a")})

    run(engine, archive, Boards(set()), state, validate=0)  # nothing probed: not even started
    assert state.resume_key(GREENHOUSE.key)[1] is None

    run(engine, archive, Boards(set()), state)
    assert state.resume_key(GREENHOUSE.key)[1] is not None  # read to the end
