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


def test_keka_reads_the_career_site_json_and_names_the_company() -> None:
    fetched, jobs = read(
        "keka",
        "pennanttech",
        {
            "https://pennanttech.keka.com/careers/api/jobs/default/active": body("keka_jobs.json"),
            "https://pennanttech.keka.com/careers/api/organization/default/careerportalinfo": body(
                "keka_info.json"
            ),
        },
    )
    assert fetched.complete and len(jobs) == 2
    job = jobs[0]
    assert job.title == "Chief Delivery Officer" and job.company_name == "Pennant Technologies"
    assert job.city == "Hyderabad" and job.country_hint == "IN"
    assert job.departments == ["Client Services"] and job.posted_at is not None
    assert str(job.apply_url) == "https://pennanttech.keka.com/careers/jobdetails/143320"
    assert job.description_html and "Role Overview" in job.description_html


def test_connectoor_reads_the_board_search_then_each_job_page() -> None:
    fetcher = FakeFetcher(
        {
            "https://api.connectoor.de/find": body("connectoor_find.json"),
            "https://app.connectoor.de/jobview": body("connectoor_job.html"),
        }
    )
    connector = CONNECTORS["connectoor"]
    fetched = connector.list_postings(fetcher, "https://www.connectoor.jobs")
    jobs = [connector.parse(raw) for raw in fetched.postings]
    assert len(jobs) == 2 and fetched.complete
    assert fetcher.requested[0].startswith("https://api.connectoor.de/find?s=")
    job = jobs[0]
    assert job.title.startswith("Ausbildung zur Pflegefachkraft")
    assert job.company_name == "Eilenriedestift e. V." and job.city == "Hannover"
    assert str(job.apply_url).startswith("https://app.connectoor.de/jobview?jobid=")
    assert job.description_html
    normalize(job, {})


def test_talos360_reads_the_career_site_sitemap_and_job_pages() -> None:
    fetched, jobs = read(
        "talos360",
        "https://ukas.talosats-careers.com/sitemap.xml",
        {
            "https://ukas.talosats-careers.com/sitemap.xml": body("talos360_sitemap.xml"),
            "https://ukas.talosats-careers.com/job/": body("talos360_job.html"),
        },
    )
    assert fetched.complete and len(jobs) == 2
    job = jobs[0]
    assert job.title == "Product Owner" and job.company_name == "Talos360 Internal"
    assert job.location_text and "United Kingdom" in job.location_text
    assert job.salary is not None and job.salary.currency == "GBP"
    assert str(job.apply_url).startswith("https://ukas.talosats-careers.com/job/")
    assert job.description_html


def test_recruitis_reads_the_list_and_job_pages() -> None:
    fetched, jobs = read(
        "recruitis",
        "recruitisio",
        {
            "https://jobs.recruitis.io/recruitisio/": body("recruitis_job.html"),
            "https://jobs.recruitis.io/recruitisio": body("recruitis_list.html"),
        },
    )
    assert fetched.complete and len(jobs) == 2
    job = jobs[0]
    assert job.title == "Obchodní zástupce pro SaaS řešení - junior"
    assert job.company_name == "Recruitis.io s.r.o."
    assert job.location_text == "Hradec Králové, CZ" and job.country_hint == "CZ"
    assert job.employment_type and "plný úvazek" in job.employment_type
    assert str(job.apply_url).startswith("https://jobs.recruitis.io/recruitisio/479319-")
    assert job.description_html and "Hledáme" in job.description_html


def test_applicantstack_reads_the_openings_list_and_detail_pages() -> None:
    fetched, jobs = read(
        "applicantstack",
        "conetrix",
        {
            "https://conetrix.applicantstack.com/x/detail/": body("applicantstack_job.html"),
            "https://conetrix.applicantstack.com/x/openings": body("applicantstack_list.html"),
        },
    )
    assert fetched.complete and len(jobs) == 5
    job = jobs[0]
    assert job.title == "Information Security (IT) Auditor"
    assert job.company_name == "CoNetrix" and job.location_text is None  # "N/A"
    assert job.departments == ["Security Audit"]
    assert str(job.apply_url).startswith("https://conetrix.applicantstack.com/x/detail/")
    assert job.description_html and "IT Auditor" in job.description_html


def test_opencats_reads_the_careers_module_and_skips_the_general_application() -> None:
    fetched, jobs = read(
        "opencats",
        "https://vectaur.com/ats/careers/",
        {
            "https://vectaur.com/ats/careers/index.php?m=careers&p=showJob": body(
                "opencats_job.html"
            ),
            "https://vectaur.com/ats/careers/index.php?m=careers&p=showAll": body(
                "opencats_list.html"
            ),
        },
    )
    # Four rows on the list; "Upload Resume for General Consideration" is not a job.
    assert fetched.complete and len(jobs) == 3
    job = jobs[0]
    assert job.title == "CFO/VP Finance" and job.company_name == "Vectaur"
    assert job.location_text == "Greater Toronto Area, ON"
    assert str(job.apply_url) == "https://vectaur.com/ats/careers/index.php?m=careers&p=showJob&ID=20"
    assert job.description_html and "Chief Financial Officer" in job.description_html


@pytest.mark.parametrize(
    ("slug", "token"),
    [
        ("opencats", "http://vectaur.com/ats/careers/"),
        ("opencats", "https://user@evil.example.org/careers/"),
        ("opencats", "https://vectaur.com/not-careers"),
        ("applicantstack", "a.b"),
        ("applicantstack", "evil/x"),
        ("recruitis", "a/b"),
        ("recruitis", "x.evil.org"),
        ("connectoor", "https://evil.example.org"),
        ("keka", "a/b/c"),
        ("keka", "evil.example.org"),
        ("crelate", "bad token"),
        ("crelate", "../x"),
        ("beehire", "a/b"),
        ("beehire", "x?y"),
    ],
)
def test_hostile_tokens_are_refused(slug: str, token: str) -> None:
    with pytest.raises(ValueError):
        CONNECTORS[slug].board_url(token)
