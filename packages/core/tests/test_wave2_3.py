"""Wave 2/3 platforms: each connector runs against responses recorded from real career
sites (trimmed) in fixtures/wave2_3/."""

import json
from pathlib import Path
from typing import Any

import pytest

from erio_core.connectors import CONNECTORS, FetchResponse
from erio_core.normalize.job import normalize

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "wave2_3"


def body(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class FakeFetcher:
    """Serves recorded bodies for URLs that start with a registered prefix (longest wins)."""

    def __init__(self, pages: dict[str, bytes | dict[str, Any]]):
        self.pages = pages
        self.requested: list[str] = []
        self.headers: list[dict[str, str]] = []
        self.posted: list[Any] = []

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
        self.posted.append(payload)
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


def test_crelate_reads_the_portal_rss_feed() -> None:
    fetched, jobs = read(
        "crelate",
        "10thstreettalent",
        {"https://jobs.crelate.com/portal/10thstreettalent/rss": body("crelate.xml")},
    )
    assert fetched.complete and len(jobs) == 2
    job = jobs[0]
    assert job.title == "Director of People Operations"
    assert job.company_name == "10th St. Talent"
    assert job.location_text == "Wichita, KS, United States"
    assert str(job.apply_url).startswith("https://jobs.crelate.com/portal/10thstreettalent/job/")
    assert job.description_html and "people team" in job.description_html


def test_geekjob_reads_vacancy_pages_linked_from_its_list() -> None:
    fetched, jobs = read(
        "geekjob",
        "https://geekjob.ru/vacancies",
        {
            "https://geekjob.ru/vacancies": body("geekjob_list.html"),
            "https://geekjob.ru/vacancy/": body("geekjob_job.html"),
        },
    )
    assert fetched.complete and len(jobs) == 2
    job = jobs[0]
    assert job.title == "Account manager" and job.company_name == "AdTech"
    assert job.location_text and "Москва" in job.location_text
    assert str(job.apply_url).startswith("https://geekjob.ru/vacancy/")
    assert job.description_html


def test_beehire_reads_the_career_page_json_and_skips_the_standing_form() -> None:
    fetched, jobs = read(
        "beehire",
        "beehire",
        {"https://app.beehire.com/users/getPublicCampaigns/beehire": body("beehire.json")},
    )
    assert fetched.complete and len(jobs) == 1  # "Spontaneous Application" is not a job
    job = jobs[0]
    assert job.title == "Digital Marketing - Stage"  # the posting's own language (French)
    assert job.company_name == "Beehire" and job.city == "Bruxelles"
    assert job.employment_type == "Internship" and job.workplace_type == "onsite"
    assert str(job.apply_url).startswith("https://app.beehire.com/invite/")
    assert job.description_html


@pytest.mark.parametrize(
    ("slug", "token"),
    [
        ("crelate", "bad token"),
        ("crelate", "../x"),
        ("beehire", "a/b"),
        ("beehire", "x?y"),
    ],
)
def test_hostile_tokens_are_refused(slug: str, token: str) -> None:
    with pytest.raises(ValueError):
        CONNECTORS[slug].board_url(token)
