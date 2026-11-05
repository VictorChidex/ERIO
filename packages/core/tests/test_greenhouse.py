"""Greenhouse contract tests against recorded responses in fixtures/greenhouse/."""

from pathlib import Path

import pytest

from erio_core.connectors import CONNECTORS, FetchError, FetchResponse
from erio_core.connectors.greenhouse import GreenhouseConnector

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "greenhouse"


class FakeFetcher:
    """Answers each URL with a canned response and records what was asked."""

    def __init__(self, responses: dict[str, FetchResponse]):
        self.responses = responses
        self.requested: list[str] = []

    def get(self, url: str, etag: str | None = None) -> FetchResponse:
        self.requested.append(url)
        if etag and etag == self.responses.get(url, FetchResponse(404, b"")).headers.get("ETag"):
            return FetchResponse(304, b"")
        return self.responses.get(url, FetchResponse(404, b"{}"))


def fixture(name: str) -> bytes:
    return (FIXTURES / f"{name}.json").read_bytes()


@pytest.fixture
def greenhouse() -> GreenhouseConnector:
    return GreenhouseConnector()


def _fetch(connector: GreenhouseConnector, token: str, response: FetchResponse) -> FakeFetcher:
    return FakeFetcher({connector.board_url(token): response})


def test_registered_under_its_slug() -> None:
    assert isinstance(CONNECTORS["greenhouse"], GreenhouseConnector)


def test_board_url_is_the_public_jobs_endpoint(greenhouse: GreenhouseConnector) -> None:
    url = greenhouse.board_url("truelayer")
    assert url == "https://boards-api.greenhouse.io/v1/boards/truelayer/jobs?content=true"
    assert url.split("/")[2] in greenhouse.hosts


def test_lists_every_posting_on_a_board(greenhouse: GreenhouseConnector) -> None:
    fetcher = _fetch(greenhouse, "truelayer", FetchResponse(200, fixture("truelayer")))

    result = greenhouse.list_postings(fetcher, "truelayer")

    assert result.http_status == 200
    assert len(result.postings) == 3
    assert {p.source_slug for p in result.postings} == {"greenhouse"}
    assert {p.board_token for p in result.postings} == {"truelayer"}
    assert all(p.external_id.isdigit() for p in result.postings)
    assert len({p.content_hash for p in result.postings}) == 3


def test_parses_a_posting(greenhouse: GreenhouseConnector) -> None:
    fetcher = _fetch(greenhouse, "truelayer", FetchResponse(200, fixture("truelayer")))
    raw = greenhouse.list_postings(fetcher, "truelayer").postings[0]

    job = greenhouse.parse(raw)

    assert job.title == "Customer Success Manager - iGaming"
    assert job.company_name == "TrueLayer"
    assert job.location_text == "London, United Kingdom"
    assert job.city == "London"
    assert job.country_hint == "United Kingdom"
    assert job.departments == ["Commercial"]
    assert str(job.apply_url).startswith("https://job-boards.eu.greenhouse.io/truelayer/jobs/")
    assert job.posted_at is not None and job.posted_at.tzinfo is not None
    # Greenhouse escapes its HTML; the parsed description is real markup.
    assert job.description_html is not None
    assert job.description_html.startswith("<")
    assert "&lt;" not in job.description_html[:200]


def test_parses_remote_and_african_postings(greenhouse: GreenhouseConnector) -> None:
    fetcher = _fetch(greenhouse, "moniepoint", FetchResponse(200, fixture("moniepoint")))
    jobs = [
        greenhouse.parse(raw) for raw in greenhouse.list_postings(fetcher, "moniepoint").postings
    ]

    locations = [job.location_text for job in jobs]
    assert "Remote, Nigeria" in locations
    assert "Bauchi, Nigeria" in locations
    assert all(job.company_name for job in jobs)


def test_unchanged_board_answers_304_to_its_etag(greenhouse: GreenhouseConnector) -> None:
    response = FetchResponse(200, fixture("truelayer"), {"ETag": 'W/"abc"'})
    fetcher = _fetch(greenhouse, "truelayer", response)

    first = greenhouse.list_postings(fetcher, "truelayer")
    again = greenhouse.list_postings(fetcher, "truelayer", etag=first.etag)

    assert first.etag == 'W/"abc"'
    assert not first.unchanged
    assert again.unchanged
    assert again.http_status == 304
    assert again.postings == []


def test_an_explicitly_empty_board_is_a_success(greenhouse: GreenhouseConnector) -> None:
    fetcher = _fetch(greenhouse, "quiet", FetchResponse(200, fixture("empty")))
    assert greenhouse.list_postings(fetcher, "quiet").postings == []


@pytest.mark.parametrize(
    ("response", "outcome"),
    [
        (FetchResponse(404, b'{"status":404}'), "http_error"),
        (FetchResponse(500, b"oops"), "http_error"),
        (FetchResponse(429, b""), "rate_limited"),
        (FetchResponse(200, b"<html>maintenance</html>"), "parse_error"),
        (FetchResponse(200, b'{"jobs": "nope"}'), "parse_error"),
        (FetchResponse(200, b'{"jobs": []}'), "parse_error"),
        (FetchResponse(200, b'{"meta": {}}'), "parse_error"),
    ],
)
def test_failed_fetches_raise_with_their_outcome(
    greenhouse: GreenhouseConnector, response: FetchResponse, outcome: str
) -> None:
    fetcher = _fetch(greenhouse, "board", response)
    with pytest.raises(FetchError) as error:
        greenhouse.list_postings(fetcher, "board")
    assert error.value.outcome == outcome


def test_discover_returns_the_first_board_that_exists(greenhouse: GreenhouseConnector) -> None:
    fetcher = _fetch(greenhouse, "truelayer", FetchResponse(200, fixture("truelayer")))

    assert greenhouse.discover(fetcher, ["true-layer", "truelayer"]) == "truelayer"
    assert greenhouse.discover(fetcher, ["nope"]) is None
