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


def test_hrmos_reads_the_company_job_list_and_its_job_pages() -> None:
    site = "https://hrmos.co/pages/uzabase"
    _, jobs, fetcher = read(
        "hrmos",
        f"{site}/jobs",
        {
            f"{site}/jobs": body("hrmos_list.html"),
            f"{site}/jobs/MIMIR_005": body("hrmos_job.html"),
        },
    )
    # The entry link is not a job page; the second job page is not recorded (404, closed).
    assert not any(u.endswith("/entry") for u in fetcher.requested)
    assert len(jobs) == 1
    job = jobs[0]
    assert job.company_name == "株式会社ユーザベース"
    assert job.salary is not None and job.salary.currency == "JPY"
    assert str(job.apply_url) == f"{site}/jobs/MIMIR_005"
    assert job.description_html


def test_loxo_reads_the_agency_list_and_job_pages() -> None:
    fetched, jobs, fetcher = read(
        "loxo",
        "syndesus",
        {
            "https://app.loxo.co/syndesus": body("loxo_list.html"),
            "https://syndesus.app.loxo.co/job/NDUwNjktNXk3dDdscW1xZWZiMGp5eg==": body(
                "loxo_job.html"
            ),
        },
    )
    assert [j.title for j in jobs] == [
        "Accountant, Payroll & Billing Operations",
        "Founding Solution Engineer / Technical AI Lead (Europe)",
    ]
    first = jobs[0]
    assert first.company_name == "Syndesus"
    assert first.location_text == "Toronto, Ontario, Canada"
    assert first.employment_type == "Full Time"
    assert first.description_html and "<p" in first.description_html
    assert str(first.apply_url).startswith("https://syndesus.app.loxo.co/job/")
    assert jobs[1].description_html is None  # its job page is not recorded (404)
    assert fetched.complete
    assert len(fetcher.requested) == 3


def test_gestmax_reads_the_search_list_and_job_pages() -> None:
    site = "https://cned-recrutement.gestmax.fr"
    fetched, jobs, fetcher = read(
        "gestmax",
        "cned-recrutement",
        {
            f"{site}/search": body("gestmax_list.html"),
            f"{site}/1367/1/": body("gestmax_job.html"),
        },
    )
    # Page 2 of the list answers 404 (not recorded) and ends the paging; the second job page
    # is not recorded either (closed), and the spontaneous-application link is not a job.
    assert [u for u in fetcher.requested if "multipleunsolicited" in u] == []
    assert len(jobs) == 1
    job = jobs[0]
    assert job.title == "Technicien(ne) de support informatique H/F"
    assert job.location_text == "Lyon (69)"
    assert job.country_hint == "FR"
    assert job.description_html and "Cned" in job.description_html
    assert str(job.apply_url) == f"{site}/1367/1/technicien-ne-de-support-informatique-h-f"
    assert fetched.complete


def test_djinni_reads_the_job_postings_on_its_list_pages() -> None:
    fetched, jobs, fetcher = read(
        "djinni",
        "https://djinni.co/jobs/",
        {"https://djinni.co/jobs/": body("djinni_list.html")},
    )
    # Page 2 answers 404 (not recorded): the list has ended, so the read is complete.
    assert fetched.complete
    assert len(jobs) == 2 and len(fetcher.requested) == 2
    job = jobs[0]
    assert job.company_name and job.title
    assert str(job.apply_url).startswith("https://djinni.co/jobs/")
    assert job.description_html and job.description_html.startswith("<p>")
    assert job.posted_at is not None


def test_taleez_reads_job_pages_from_the_job_sitemap_newest_first() -> None:
    site = "https://taleez.com"
    fetched, jobs, fetcher = read(
        "taleez",
        f"{site}/sitemap-job.xml",
        {
            f"{site}/sitemap-job.xml": body("taleez_sitemap.xml"),
            f"{site}/apply/technico-commercial": body("taleez_job.html"),
        },
    )
    # The sitemap lists its newest job last: it is read first.
    assert fetcher.requested[1].endswith("chausson-materiaux-cdi-1")
    assert [j.title for j in jobs] == ["Technico-commercial Itinérant - H/F"]
    assert jobs[0].city == "Angoulême" and jobs[0].country_hint == "FR"
    assert jobs[0].company_name
    assert fetched.complete


# --- end of tests ---
