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


def test_speedrun_reads_the_feed_and_role_pages_but_not_decoys() -> None:
    site = "https://speedrun-talent-network.com"
    fetched, jobs, fetcher = read(
        "speedrun",
        f"{site}/jobs.rss",
        {
            f"{site}/jobs.rss": body("speedrun_feed.xml"),
            f"{site}/jobs/head-of-legal": body("speedrun_job.html"),
        },
    )
    assert not any("ad00000" in u for u in fetcher.requested)
    assert len(jobs) == 1
    assert jobs[0].title == "Head of Legal Engineering, APAC"
    assert jobs[0].company_name == "Harvey"
    assert jobs[0].description_html
    assert fetched.complete


def test_simplifyhr_follows_list_links_to_employer_vacancy_pages() -> None:
    fetched, jobs, fetcher = read(
        "simplifyhr",
        "https://jobs.simplify.hr/",
        {
            "https://jobs.simplify.hr/": body("simplifyhr_list.html"),
            "https://atlasfinance.simplify.hr/vacancy/5bomty": body("simplifyhr_job.html"),
        },
    )
    # The second vacancy page is not recorded (closed); the footer link is not a vacancy.
    assert "https://www.simplify.hr/" not in fetcher.requested
    assert [j.title for j in jobs] == ["Consultant"]
    assert jobs[0].company_name == "Atlas Finance"
    assert jobs[0].description_html
    assert str(jobs[0].apply_url) == "https://atlasfinance.simplify.hr/vacancy/5bomty"
    assert fetched.complete


def test_quickin_reads_the_public_career_page_api() -> None:
    account = "000000000000000000000001"
    fetched, jobs, fetcher = read(
        "quickin",
        account,
        {f"https://api.quickin.io/public/{account}/jobs": body("quickin_jobs.json")},
    )
    assert fetcher.requested == [f"https://api.quickin.io/public/{account}/jobs?sort=-created_at"]
    assert len(jobs) == 3 and fetched.complete
    assert jobs[0].title == "Desenhista Projetista Mecânico - Presencial RJ"
    assert jobs[0].country_hint == "BR"
    assert str(jobs[0].apply_url).startswith("https://jobs.quickin.io/talentsclub/jobs/")
    assert jobs[0].description_html and "<ul>" in jobs[0].description_html
    paid = [j for j in jobs if j.salary]
    assert paid and paid[0].salary and paid[0].salary.currency == "BRL"
    assert paid[0].salary.period == "month"


def test_jobtrain_reads_the_job_card_list_and_job_pages() -> None:
    site = "https://www.jobtrain.co.uk/enwl"
    fetched, jobs, fetcher = read(
        "jobtrain",
        "enwl",
        {
            f"{site}/Home/_JobCard?Skip=0": body("jobtrain_cards.html"),
            f"{site}/Job/JobDetail?JobId=13981": body("jobtrain_job.html"),
        },
    )
    # The list's second page (Skip=2) is not recorded: it ends the listing. The second job
    # page is not recorded either (closed).
    assert any(u.endswith("Skip=2") for u in fetcher.requested)
    assert len(jobs) == 1 and fetched.complete
    job = jobs[0]
    assert job.title == "Electrical Engineering Graduate"
    assert job.company_name == "ENWL" and job.country_hint == "GB"
    assert str(job.apply_url) == f"{site}/Job/JobDetail?JobId=13981"
    assert job.description_html


def test_gupy_reads_the_career_page_data_and_skips_talent_pools() -> None:
    site = "https://ambev.gupy.io"
    fetched, jobs, fetcher = read(
        "gupy",
        "ambev",
        {
            f"{site}/jobs/12202203": body("gupy_job.html"),
            f"{site}/": body("gupy_career.html"),
        },
    )
    # The talent-pool entry is not a job; the second job's page is not recorded (404).
    assert len(jobs) == 2 and fetched.complete
    assert not any(u.endswith("/jobs/12682950") for u in fetcher.requested)
    job = jobs[0]
    assert job.title.startswith("Ambev | Aprendiz")
    assert job.company_name == "Ambev"
    assert job.city == "Juatuba" and job.region == "MG" and job.country_hint == "BR"
    assert job.employment_type == "Apprenticeship"
    assert job.description_html
    assert jobs[1].description_html is None
    assert str(job.apply_url) == f"{site}/jobs/12202203"


def test_hireclick_reads_the_job_board_call_and_job_pages() -> None:
    employer = "00000000-0000-0000-0000-000000000001"
    site = "https://careers.hireclick.com"
    fetched, jobs, fetcher = read(
        "hireclick",
        employer,
        {
            f"{site}/api/Controllers/JobBoard/GetSettingsAndJobs?orgGUID={employer}": body(
                "hireclick_jobs.json"
            ),
            f"{site}/jb/sales-account-executive-software/view/163100": body("hireclick_job.html"),
        },
    )
    assert len(jobs) == 2 and fetched.complete and len(fetcher.requested) == 3
    first, second = jobs
    assert first.title.startswith("Sales Account Executive")
    assert first.company_name == "HIRECLICK" and first.city == "Sioux Falls"
    assert first.description_html and len(first.description_html) > 200
    # The second job page is not recorded: only the list's own fields are known.
    assert second.city == "Minneapolis" and second.company_name is None
    assert str(first.apply_url) == f"{site}/jb/sales-account-executive-software/view/163100"


# --- end of tests ---
