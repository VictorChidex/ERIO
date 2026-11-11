"""Second-wave platforms, batch 2: each connector runs against responses recorded from real
career sites (trimmed) in fixtures/wave2_2/."""

import json
from pathlib import Path
from typing import Any

from erio_core.connectors import CONNECTORS, FetchResponse
from erio_core.normalize.job import normalize
from erio_core.schemas import PartialJob

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "wave2_2"


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
    fetcher = FakeFetcher(pages)
    fetched = connector.list_postings(fetcher, token)
    jobs: list[PartialJob] = [connector.parse(raw) for raw in fetched.postings]
    for job in jobs:
        assert job.source_slug == slug
        assert str(job.apply_url).startswith("https://")
        normalize(job, {})
    return fetched, jobs, fetcher


def test_academictransfer_reads_vacancy_pages_from_the_sitemap() -> None:
    site = "https://www.academictransfer.com"
    fetched, jobs, _ = read(
        "academictransfer",
        f"{site}/sitemap-vacancies.xml",
        {
            f"{site}/sitemap-vacancies.xml": body("academictransfer_sitemap.xml"),
            f"{site}/en/jobs/361517/": body("academictransfer_job.html"),
        },
    )
    # The Dutch page of the sitemap is not recorded: unread, so the fetch is not complete only
    # if it answered with an error; a 404 is a closed job.
    assert [j.title for j in jobs] == ["Electrical Technician"]
    job = jobs[0]
    assert job.company_name and "Wageningen" in job.company_name
    assert job.city == "Bleiswijk"
    assert job.salary is not None and job.salary.currency == "EUR"
    assert job.description_html and "greenhouse" in job.description_html.lower()
    assert fetched.complete
