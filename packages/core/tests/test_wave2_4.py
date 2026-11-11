"""Second-wave platforms (batch 4): each connector runs against responses recorded from
real career sites (trimmed) in fixtures/wave2_4/."""

import json
from pathlib import Path
from typing import Any

import pytest

from erio_core.connectors import CONNECTORS, FetchError, FetchResponse
from erio_core.normalize.job import normalize

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "wave2_4"


def body(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class FakeFetcher:
    """Serves recorded bodies for URLs that start with a registered prefix (longest wins)."""

    def __init__(self, pages: dict[str, bytes | dict[str, Any]]):
        self.pages = pages
        self.requested: list[str] = []
        self.headers: list[dict[str, str]] = []

    def _answer(self, url: str) -> FetchResponse:
        self.requested.append(url)
        matches = [prefix for prefix in self.pages if url.startswith(prefix)]
        if not matches:
            return FetchResponse(404, b"")
        page = self.pages[max(matches, key=len)]
        return FetchResponse(200, page if isinstance(page, bytes) else json.dumps(page).encode())

    def get(self, url: str, etag: str | None = None) -> FetchResponse:
        return self._answer(url)

    def get_with(self, url: str, headers: dict[str, str]) -> FetchResponse:
        self.headers.append(headers)
        return self._answer(url)

    def post_json(self, url: str, payload: Any) -> FetchResponse:
        return self._answer(url)

    def post_json_with(self, url: str, payload: Any, headers: dict[str, str]) -> FetchResponse:
        self.headers.append(headers)
        return self._answer(url)


def read(slug: str, token: str, pages: dict[str, bytes | dict[str, Any]]) -> Any:
    connector = CONNECTORS[slug]
    fetched = connector.list_postings(FakeFetcher(pages), token)
    jobs = [connector.parse(raw) for raw in fetched.postings]
    for job in jobs:
        assert job.source_slug == slug
        assert str(job.apply_url).startswith("https://")
        normalize(job, {})
    return fetched, jobs


def test_homerun_reads_the_atom_feed_of_a_career_site() -> None:
    fetched, jobs = read(
        "homerun", "jobs", {"https://feed.homerun.co/jobs": body("homerun_feed.xml")}
    )
    # The standing open application is not a vacancy.
    assert fetched.complete and len(jobs) == 2
    assert jobs[0].title == "Sales Executive - Amsterdam"
    assert jobs[0].company_name == "Homerun"
    assert jobs[0].location_text == "Amsterdam"
    assert str(jobs[0].apply_url) == "https://jobs.homerun.co/sales-executive-amsterdam"
    assert jobs[0].description_html


def test_hroffice_reads_job_pages_listed_in_a_career_site_sitemap() -> None:
    site = "https://www.werkenbijsantepartners.nl"
    job = f"{site}/vacatures/337109-leefondersteuner-verpleegkundige---de-bilt"
    fetched, jobs = read(
        "hroffice",
        f"{site}/sitemap.xml",
        {f"{site}/sitemap.xml": body("hroffice_sitemap.xml"), job: body("hroffice_job.html")},
    )
    # The sitemap also lists the application form and other pages: only the job page is read.
    assert fetched.complete and len(jobs) == 1
    assert jobs[0].title == "Leefondersteuner Verpleegkundige - De Bilt"
    assert jobs[0].company_name == "Santé Partners"
    assert jobs[0].location_text == "De Bilt" and jobs[0].description_html


def test_recrutor_reads_the_job_pages_a_career_space_feed_lists() -> None:
    space = "https://www.recrutor.pro/advance-emploi"
    page = f"{space}/emploi-preparateur-de-commandes-agroalimentaire_29572.html"
    fetched, jobs = read(
        "recrutor",
        "advance-emploi",
        {f"{space}/rss/flux-rss.xml": body("recrutor_feed.xml"), page: body("recrutor_job.html")},
    )
    # The feed lists two jobs; only the first page is served, the other is a 404 (closed).
    assert len(jobs) == 1 and fetched.complete
    assert jobs[0].title == "Préparateur de commandes agroalimentaire"
    assert jobs[0].company_name == "Advance Emploi"
    assert jobs[0].location_text and jobs[0].description_html


@pytest.mark.parametrize(
    ("slug", "token"),
    [
        ("homerun", "bad token"),
        ("recrutor", "bad token"),
    ],
)
def test_wave2_4_refuse_a_token_that_is_not_theirs(slug: str, token: str) -> None:
    with pytest.raises(ValueError):
        CONNECTORS[slug].board_url(token)


def test_wave2_4_fetch_errors_are_fetch_errors() -> None:
    with pytest.raises(FetchError):
        CONNECTORS["homerun"].list_postings(FakeFetcher({}), "jobs")
