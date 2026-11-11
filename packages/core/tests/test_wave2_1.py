"""Second reference wave, batch 1: each connector runs against responses recorded from real
career sites (trimmed) in fixtures/wave2_1/."""

import json
from pathlib import Path
from typing import Any

import pytest

from erio_core.connectors import CONNECTORS, FetchError, FetchResponse
from erio_core.normalize.job import normalize

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "wave2_1"


def body(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class FakeFetcher:
    """Serves recorded bodies for URLs that start with a registered prefix (longest wins)."""

    def __init__(self, pages: dict[str, bytes | dict[str, Any]]):
        self.pages = pages
        self.requested: list[str] = []

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
        return self._answer(url)

    def post_json(self, url: str, payload: Any) -> FetchResponse:
        return self._answer(url)

    def post_json_with(self, url: str, payload: Any, headers: dict[str, str]) -> FetchResponse:
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


# ------------------------------------------------------------- greytHR Hire


def test_greythr_reads_the_career_page_calls_and_resolves_place_names() -> None:
    base = "https://basiscloud.greythr.com/hire/api"
    fetched, jobs = read(
        "greythr",
        "basiscloud",
        {
            f"{base}/career/published_jobs/": body("greythr_jobs.json"),
            f"{base}/career/get_company_details/": body("greythr_company.json"),
            f"{base}/greythr/emp-category/": body("greythr_lookup.json"),
        },
    )
    assert fetched.complete and len(jobs) == 2
    first = jobs[0]
    assert first.title == "Trainee - BTP"
    assert first.company_name == "Basis Cloud Solutions Private Limited"
    assert first.location_text == "Chennai"
    assert first.employment_type == "Full-time"
    assert str(first.apply_url) == "https://basiscloud.greythr.com/hire/jobs/trainee-btp"
    assert first.description_html and first.posted_at
    assert "added_by_email" not in fetched.postings[0].payload


def test_greythr_without_a_jobs_list_is_a_parse_error() -> None:
    with pytest.raises(FetchError) as error:
        read("greythr", "nobody", {"https://nobody.greythr.com/hire/api/career/published_jobs/": {}})
    assert error.value.outcome == "parse_error"


# ----------------------------------------------------------------- d.vinci


def test_dvinci_reads_the_sitemap_and_each_job_page_posting() -> None:
    site = "https://dein-weg-zu.dvinci.de"
    fetched, jobs = read(
        "dvinci",
        f"{site}/sitemap.xml",
        {
            f"{site}/sitemap.xml": body("dvinci_sitemap.xml"),
            f"{site}/de/jobs/": body("dvinci_job.html"),
        },
    )
    assert fetched.complete and len(jobs) == 2
    first = jobs[0]
    assert first.title.startswith("System Owner")
    assert first.location_text and "Hamburg" in first.location_text
    assert str(first.apply_url).startswith(f"{site}/de/jobs/")
    assert first.description_html
