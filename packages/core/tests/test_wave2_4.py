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


def test_talentadore_reads_the_position_list_a_career_site_embeds() -> None:
    fetched, jobs = read(
        "talentadore",
        "demo1",
        {"https://ats.talentadore.com/positions/demo1/json": body("talentadore_list.json")},
    )
    assert fetched.complete and len(jobs) == 1
    job = jobs[0]
    assert job.external_id == "JOB001"
    assert job.title.startswith("Määräaikainen lennonjohtaja")
    assert job.company_name == "Fintraffic Lennonvarmistus"
    assert job.location_text == "Vantaa"
    assert str(job.apply_url).endswith("/JOB001") and job.description_html


def test_huntflow_reads_vacancy_pages_listed_in_a_career_site_sitemap() -> None:
    site = "https://cryptopay.global.huntflow.io"
    fetched, jobs = read(
        "huntflow",
        "cryptopay.global",
        {
            f"{site}/sitemap.xml": body("huntflow_sitemap.xml"),
            f"{site}/vacancy/account-manager-b2b": body("huntflow_job.html"),
        },
    )
    # The sitemap also lists the home and list pages; the second vacancy page is a 404 (closed).
    assert len(jobs) == 1 and fetched.complete
    assert jobs[0].title == "Account Manager (B2B)"
    assert jobs[0].company_name == "Cryptopay"
    assert jobs[0].location_text == "Remote (Europe)" and jobs[0].description_html
    assert str(jobs[0].apply_url) == f"{site}/vacancy/account-manager-b2b"


def test_enlizt_reads_job_pages_linked_from_a_career_site() -> None:
    site = "https://dr.enlizt.me"
    job = f"{site}/vagas/chefe_de_bar_-_chica_parrilla_y_bar_-_porto_alegre-060826"
    fetched, jobs = read(
        "enlizt",
        f"{site}/",
        {f"{site}/": body("enlizt_list.html"), job: body("enlizt_job.html")},
    )
    # The talent-bank link is not a job page.
    assert fetched.complete and len(jobs) == 1
    assert jobs[0].title.startswith("Chefe de Bar")
    assert jobs[0].company_name == "Fermenta Pessoas"
    assert jobs[0].location_text and "Porto Alegre" in jobs[0].location_text
    assert jobs[0].description_html


def test_odoo_reads_microdata_pages_listed_on_a_jobs_page() -> None:
    site = "https://www.odoo.com"
    fetched, jobs = read(
        "odoo",
        f"{site}/jobs",
        {
            f"{site}/jobs": body("odoo_list.html"),
            f"{site}/jobs/page/2": b"<html></html>",
            f"{site}/jobs/fullstack-developer-698": body("odoo_job_microdata.html"),
        },
    )
    # The apply and paging links are not job pages.
    assert fetched.complete and len(jobs) == 1
    assert jobs[0].title == "Fullstack Developer"
    assert jobs[0].company_name == "Odoo IN Pvt Ltd"
    assert jobs[0].location_text and "Gandhinagar" in jobs[0].location_text
    assert jobs[0].description_html and "open source Odoo" in jobs[0].description_html


def test_odoo_reads_json_ld_pages_listed_in_a_sitemap() -> None:
    site = "https://www.odooexperts.nl"
    sitemap = (
        b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        b"<url><loc>https://www.odooexperts.nl/en/jobs</loc></url>"
        b"<url><loc>https://www.odooexperts.nl/en/jobs/accountmanager-21</loc></url></urlset>"
    )
    fetched, jobs = read(
        "odoo",
        f"{site}/sitemap.xml",
        {
            f"{site}/sitemap.xml": sitemap,
            f"{site}/en/jobs/accountmanager-21": body("odoo_job_jsonld.html"),
        },
    )
    assert fetched.complete and len(jobs) == 1
    assert jobs[0].title == "Accountmanager"
    assert jobs[0].company_name == "Odoo Experts B.V."


def test_bite_reads_job_pages_listed_in_the_portal_sitemap() -> None:
    page = "https://jobs.b-ite.com/jobposting/013a4943abd47fd20b4c87391ebd0b287ab7568f"
    fetched, jobs = read(
        "bite",
        "https://jobs.b-ite.com/sitemap.xml.gz",
        {
            "https://jobs.b-ite.com/sitemap.xml.gz": body("bite_sitemap.xml"),
            page: body("bite_job.html"),
        },
    )
    assert fetched.complete and len(jobs) == 1
    assert jobs[0].title.startswith("Ausbildung 2027")
    assert jobs[0].company_name == "acadon AG"  # the portal lists many employers
    assert jobs[0].location_text and "Krefeld" in jobs[0].location_text
    assert jobs[0].description_html


def test_tecla_reads_the_public_job_list() -> None:
    fetched, jobs = read(
        "tecla",
        "https://api.tecla.io",
        {"https://api.tecla.io/api/jobs/getPublicJobs/": body("tecla_jobs.json")},
    )
    assert fetched.complete and len(jobs) == 2
    first = jobs[0]
    assert first.title == "Applied AI Engineer"
    assert first.company_name == "Crux Analytics"
    assert first.workplace_type == "remote" and first.location_text == "Remote"
    assert str(first.apply_url) == "https://app.tecla.io/job?id=3419"
    assert first.salary and first.salary.currency == "USD" and first.salary.period == "month"
    assert first.description_html


def test_hr4you_reads_job_pages_listed_in_a_career_site_sitemap() -> None:
    site = "https://wupersonal.hr4you.org"
    job = f"{site}/job/view/2633/it-techniker-m-w-d-2nd-level-support?page_lang=de"
    fetched, jobs = read(
        "hr4you",
        f"{site}/sitemap.xml",
        {f"{site}/sitemap.xml": body("hr4you_sitemap.xml"), job: body("hr4you_job.html")},
    )
    assert fetched.complete and len(jobs) == 1
    assert jobs[0].title == "IT Techniker (m/w/d) 2nd Level Support"
    assert jobs[0].company_name == "wu personal GmbH"
    assert jobs[0].location_text == "Hannover, Niedersachsen, DE"
    assert jobs[0].description_html


def test_hrworks_reads_job_pages_linked_from_a_portal() -> None:
    portal = "https://jobapplication.hrworks.de/de?companyId=jf9bb77"
    fetched, jobs = read(
        "hrworks",
        portal,
        {
            portal: body("hrworks_list.html"),
            f"{portal}&id=1413cb": body("hrworks_job.html"),
        },
    )
    # The second job page is a 404 (closed); the language and XING links are not jobs.
    assert fetched.complete and len(jobs) == 1
    assert jobs[0].title.startswith("Initiativbewerbung")
    assert jobs[0].company_name == "Kerberos Compliance Managementsysteme"
    assert jobs[0].description_html


def test_recruiterflow_reads_the_job_pages_a_career_page_lists() -> None:
    board = "https://recruiterflow.com/believeresourcing/jobs"
    fetched, jobs = read(
        "recruiterflow",
        board,
        {
            board: body("recruiterflow_list.html"),
            f"{board}/2314": body("recruiterflow_job.html"),
        },
    )
    # The second job page in the list is not served by the fake: it is skipped.
    assert fetched.complete and len(jobs) == 1
    assert jobs[0].title.startswith("Call Centre Agent")
    assert jobs[0].company_name == "Believe Resourcing"
    assert jobs[0].location_text and "Cape Town" in jobs[0].location_text
    assert jobs[0].description_html


def test_talentio_reads_the_job_pages_a_career_page_lists() -> None:
    board = "https://open.talentio.com/r/1/c/doublebz/homes/4401"
    page = "https://open.talentio.com/r/1/c/doublebz/pages/94073"
    fetched, jobs = read(
        "talentio",
        board,
        {board: body("talentio_home.html"), page: body("talentio_job.html")},
    )
    # The part-time page is not served by the fake and is skipped; the apply links are not read.
    assert fetched.complete and len(jobs) == 1
    assert jobs[0].title == "【正社員】ジビエ処理加工施設スタッフ"
    assert jobs[0].company_name and jobs[0].description_html
    assert str(jobs[0].apply_url) == page


def test_jobsoid_reads_the_job_list_a_career_portal_loads() -> None:
    fetched, jobs = read(
        "jobsoid",
        "co-impact",
        {"https://co-impact.jobsoid.com/api/v1/jobs": body("jobsoid_jobs.json")},
    )
    assert fetched.complete and len(jobs) == 2
    first = jobs[0]
    assert first.title == "Regional Director, Asia"
    assert str(first.apply_url) == "https://co-impact.jobsoid.com/j/136792/regional-director-asia"
    assert first.location_text == "Bengaluru, Delhi, or Mumbai (Remote), India"
    assert first.workplace_type == "remote" and first.description_html


@pytest.mark.parametrize(
    ("slug", "token"),
    [
        ("homerun", "bad token"),
        ("jobsoid", "bad/token"),
        ("talentio", "https://example.com/x"),
        ("recruiterflow", "https://example.com/x/jobs"),
        ("tecla", "https://example.com"),
        ("huntflow", "bad/token"),
        ("recrutor", "bad token"),
        ("talentadore", "bad/token"),
    ],
)
def test_wave2_4_refuse_a_token_that_is_not_theirs(slug: str, token: str) -> None:
    with pytest.raises(ValueError):
        CONNECTORS[slug].board_url(token)


def test_wave2_4_fetch_errors_are_fetch_errors() -> None:
    with pytest.raises(FetchError):
        CONNECTORS["homerun"].list_postings(FakeFetcher({}), "jobs")
