"""Contract tests for Lever, Ashby, Workable, Recruitee and SmartRecruiters.

Every adapter runs the same contract against responses recorded from real
boards in fixtures/<source>/, so a broken fixture or adapter fails only the
tests named after that source. Greenhouse has its own file.
"""

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from erio_core.connectors import CONNECTORS, Connector, FetchError, FetchResponse
from erio_core.connectors.smartrecruiters import SmartRecruitersConnector
from erio_core.normalize.job import normalize
from erio_core.schemas import PartialJob

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"


class FakeFetcher:
    def __init__(self, responses: dict[str, FetchResponse]):
        self.responses = responses
        self.requested: list[str] = []

    def get(self, url: str, etag: str | None = None) -> FetchResponse:
        self.requested.append(url)
        return self.responses.get(url, FetchResponse(404, b'{"status":404}'))


@dataclass(frozen=True)
class Board:
    source: str
    token: str
    fixture: str
    count: int


BOARDS = [
    Board("lever", "kavak", "kavak", 3),
    Board("lever", "spotify", "spotify", 2),
    Board("ashby", "andela", "andela", 3),
    Board("ashby", "linear", "linear", 2),
    Board("workable", "huggingface", "huggingface", 3),
    Board("recruitee", "channable", "channable", 2),
    Board("recruitee", "bunq", "bunq", 2),
]
EMPTY = {"lever": "empty", "ashby": "empty", "workable": "typeform", "recruitee": "empty"}
SOURCES = sorted({board.source for board in BOARDS} | {"smartrecruiters"})


def body(source: str, name: str) -> bytes:
    return (FIXTURES / source / f"{name}.json").read_bytes()


def connector(source: str) -> Connector:
    return CONNECTORS[source]


def fetch_board(board: Board) -> FakeFetcher:
    c = connector(board.source)
    return FakeFetcher(
        {c.board_url(board.token): FetchResponse(200, body(board.source, board.fixture))}
    )


def parsed(board: Board) -> list[PartialJob]:
    c = connector(board.source)
    return [c.parse(raw) for raw in c.list_postings(fetch_board(board), board.token).postings]


@pytest.fixture
def smartrecruiters() -> Iterator[SmartRecruitersConnector]:
    sr = SmartRecruitersConnector()
    sr.page_size = 3  # the recorded pages hold 3 and 2 postings
    yield sr


def sr_fetcher(sr: SmartRecruitersConnector) -> FakeFetcher:
    pages = [body("smartrecruiters", f"boschgroup-page{n}") for n in (1, 2)]
    return FakeFetcher({
        sr.board_url("BoschGroup"): FetchResponse(200, pages[0]),
        sr._page_url("BoschGroup", 3): FetchResponse(200, pages[1]),
    })  # fmt: skip


# The shared contract ---------------------------------------------------------


@pytest.mark.parametrize("source", SOURCES)
def test_registered_with_a_board_url_on_its_own_hosts(source: str) -> None:
    c = connector(source)
    assert c.slug == source
    host = c.board_url("acme").split("/")[2]
    assert host in c.hosts or "*." + host.split(".", 1)[1] in c.hosts


@pytest.mark.parametrize("board", BOARDS, ids=lambda b: f"{b.source}-{b.token}")
def test_lists_every_posting_on_a_board(board: Board) -> None:
    result = connector(board.source).list_postings(fetch_board(board), board.token)

    assert result.http_status == 200
    assert len(result.postings) == board.count
    assert {p.source_slug for p in result.postings} == {board.source}
    assert {p.board_token for p in result.postings} == {board.token}
    assert len({p.external_id for p in result.postings}) == board.count
    assert len({p.content_hash for p in result.postings}) == board.count


@pytest.mark.parametrize("board", BOARDS, ids=lambda b: f"{b.source}-{b.token}")
def test_every_posting_parses_and_normalizes(board: Board) -> None:
    for job in parsed(board):
        assert job.source_slug == board.source
        assert job.title and job.title == job.title.strip()
        assert str(job.apply_url).startswith("https://")
        assert job.posted_at is not None and job.posted_at.tzinfo is not None
        assert job.location_text
        assert job.description_html and job.description_html.lstrip().startswith("<")
        record = normalize(job, {"USD": 1.0, "EUR": 1.08, "MXN": 0.055})
        # Every recorded posting names a place ERIO can put on the map.
        assert record.location.country_code or record.location.eligible_country_codes


@pytest.mark.parametrize("source", sorted(EMPTY))
def test_an_empty_board_is_a_success(source: str) -> None:
    c = connector(source)
    fetcher = FakeFetcher({c.board_url("quiet"): FetchResponse(200, body(source, EMPTY[source]))})
    assert c.list_postings(fetcher, "quiet").postings == []


MALFORMED: dict[str, list[bytes]] = {
    "lever": [b'{"ok": false}', b"<html>maintenance</html>"],
    "ashby": [b'{"jobs": "nope"}', b"{}", b"<html>maintenance</html>"],
    "workable": [b'{"jobs": []}', b'{"name": "Acme"}', b"<html>maintenance</html>"],
    "recruitee": [b'{"offers": {}}', b"{}", b"<html>maintenance</html>"],
    "smartrecruiters": [b'{"content": []}', b'{"totalFound": 1}', b"<html>maintenance</html>"],
}
FAILURES = [
    (source, response, outcome)
    for source in SOURCES
    for response, outcome in [
        (FetchResponse(404, b'{"status":404}'), "http_error"),
        (FetchResponse(500, b"oops"), "http_error"),
        (FetchResponse(429, b""), "rate_limited"),
        *[(FetchResponse(200, bad), "parse_error") for bad in MALFORMED[source]],
    ]
]


@pytest.mark.parametrize(
    ("source", "response", "outcome"),
    FAILURES,
    ids=[f"{s}-{r.status}-{i}" for i, (s, r, _) in enumerate(FAILURES)],
)
def test_failed_fetches_raise_with_their_outcome(
    source: str, response: FetchResponse, outcome: str
) -> None:
    c = connector(source)
    with pytest.raises(FetchError) as error:
        c.list_postings(FakeFetcher({c.board_url("board"): response}), "board")
    assert error.value.outcome == outcome


@pytest.mark.parametrize("board", BOARDS[::2], ids=lambda b: b.source)
def test_discover_returns_the_first_board_that_exists(board: Board) -> None:
    c, fetcher = connector(board.source), fetch_board(board)
    assert c.discover(fetcher, ["no-such-board", board.token]) == board.token
    assert c.discover(fetcher, ["no-such-board"]) is None


# What each source says -------------------------------------------------------


def by_title(jobs: list[PartialJob]) -> dict[str, PartialJob]:
    return {job.title: job for job in jobs}


def test_lever_reads_workplace_country_and_both_offices() -> None:
    kavak = parsed(BOARDS[0])
    assert {job.country_hint for job in kavak} == {"MX", "BR"}
    assert {job.workplace_type for job in kavak} == {"hybrid"}
    assert all(str(job.apply_url).startswith("https://jobs.lever.co/kavak/") for job in kavak)

    remote = next(job for job in parsed(BOARDS[1]) if job.workplace_type == "remote")
    assert remote.location_text == "London; Stockholm"
    location = normalize(remote, {"USD": 1.0}).location
    assert (location.remote_scope, location.eligible_country_codes) == ("region", ["GB", "SE"])


def test_ashby_reads_compensation_and_regions() -> None:
    linear = parsed(BOARDS[3])
    paid = next(job for job in linear if job.salary)
    assert paid.salary is not None
    assert (paid.salary.min, paid.salary.max, paid.salary.currency, paid.salary.period) == (
        204000, 264000, "USD", "year",
    )  # fmt: skip
    europe = next(job for job in linear if job.location_text == "Europe")
    assert europe.workplace_type == "remote"
    location = normalize(europe, {"USD": 1.0}).location
    assert location.remote_scope == "region"
    assert {"DE", "PL", "PT"} <= set(location.eligible_country_codes)


def test_ashby_leaves_out_unlisted_postings() -> None:
    raw: dict[str, Any] = json.loads(body("ashby", "linear"))
    raw["jobs"][0]["isListed"] = False
    c = connector("ashby")
    fetcher = FakeFetcher({c.board_url("linear"): FetchResponse(200, json.dumps(raw).encode())})
    assert len(c.list_postings(fetcher, "linear").postings) == 1


def test_workable_carries_the_account_name_and_remote_flag() -> None:
    jobs = parsed(BOARDS[4])
    assert {job.company_name for job in jobs} == {"Hugging Face"}
    assert {job.workplace_type for job in jobs} == {"remote"}
    paris = next(job for job in jobs if job.city == "Paris")
    assert paris.location_text == "Paris, Île-de-France, France"


def test_recruitee_reads_monthly_and_yearly_salaries() -> None:
    jobs = by_title(parsed(BOARDS[5]))
    writer = jobs["Technical Writer, Customer Education"]
    assert writer.salary is not None
    assert (writer.salary.min, writer.salary.max, writer.salary.period) == (2976, 4252, "month")
    assert writer.salary.currency == "EUR"
    assert writer.workplace_type == "hybrid"
    assert {job.country_hint for job in jobs.values()} == {"NL"}


def test_recruitee_refuses_a_token_that_is_not_a_subdomain() -> None:
    c = connector("recruitee")
    for token in ("evil.example/x", "a.b", "", "UPPER"):
        with pytest.raises(ValueError):
            c.board_url(token)
    assert c.discover(FakeFetcher({}), ["evil.example/x"]) is None


def test_smartrecruiters_reads_every_page(smartrecruiters: SmartRecruitersConnector) -> None:
    fetcher = sr_fetcher(smartrecruiters)

    result = smartrecruiters.list_postings(fetcher, "BoschGroup")

    assert len(fetcher.requested) == 2
    assert len(result.postings) == 5
    jobs = [smartrecruiters.parse(raw) for raw in result.postings]
    assert {job.company_name for job in jobs} == {"Bosch Group"}
    assert {job.country_hint for job in jobs} == {"BE", "DE", "VN", "SE"}
    assert str(jobs[0].apply_url) == "https://jobs.smartrecruiters.com/BoschGroup/744000159799549"
    assert all(job.description_html is None for job in jobs)  # not in the list endpoint


def test_smartrecruiters_fails_the_whole_board_when_a_page_fails(
    smartrecruiters: SmartRecruitersConnector,
) -> None:
    fetcher = sr_fetcher(smartrecruiters)
    fetcher.responses[smartrecruiters._page_url("BoschGroup", 3)] = FetchResponse(500, b"")
    with pytest.raises(FetchError):
        smartrecruiters.list_postings(fetcher, "BoschGroup")


def test_smartrecruiters_discovery_needs_postings(
    smartrecruiters: SmartRecruitersConnector,
) -> None:
    # An unknown company answers 200 with nothing, like an empty board.
    fetcher = sr_fetcher(smartrecruiters)
    fetcher.responses[smartrecruiters.board_url("NoSuchCo")] = FetchResponse(
        200, body("smartrecruiters", "empty")
    )
    assert smartrecruiters.discover(fetcher, ["NoSuchCo", "BoschGroup"]) == "BoschGroup"
    assert smartrecruiters.discover(fetcher, ["NoSuchCo"]) is None


def test_discovery_rejects_empty_placeholder_accounts() -> None:
    # Workable answers for placeholder accounts under well-known names, with no jobs.
    c = connector("workable")
    fetcher = FakeFetcher({c.board_url("stripe"): FetchResponse(200, body("workable", "typeform"))})
    assert c.discover(fetcher, ["stripe"], company="Stripe") is None


def test_discovery_checks_the_employer_name_when_the_source_gives_one() -> None:
    fetcher = fetch_board(BOARDS[4])  # Workable account "Hugging Face"
    c = connector("workable")
    assert c.discover(fetcher, ["huggingface"], company="Hugging Face") == "huggingface"
    assert c.discover(fetcher, ["huggingface"], company="Hugging Face Inc") == "huggingface"
    assert c.discover(fetcher, ["huggingface"], company="Huggy Bank") is None
    # Lever postings do not name the employer: the token is all there is.
    assert (
        connector("lever").discover(fetch_board(BOARDS[0]), ["kavak"], company="Kavak") == "kavak"
    )
