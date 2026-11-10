"""Platforms found by reading the reference site: each connector runs against responses
recorded from real career sites (trimmed) in fixtures/reference/."""

import json
from pathlib import Path
from typing import Any

import pytest

from erio_core.connectors import CONNECTORS, FetchError, FetchResponse
from erio_core.normalize.job import normalize

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "reference"


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


def test_clearcompany_reads_the_widget_feed_its_career_page_names() -> None:
    site = "267abd6d-94d0-8e81-c032-409a340fd526"
    fetched, jobs = read(
        "clearcompany",
        "coopereic",
        {
            "https://apply.clearcompany.com/coopereic": body("clearcompany_page.html"),
            f"https://careers-api.clearcompany.com/v1/{site}": body("clearcompany_jobs.json"),
        },
    )
    assert fetched.complete and len(jobs) == 2
    first = jobs[0]
    assert first.title == "BIM Modeler"
    assert first.company_name == "Cooper Electrical Construction Company"
    assert first.location_text == "Greensboro NC" and first.country_hint == "US"
    assert str(first.apply_url).startswith("https://coopereic.clearcompany.com/careers/jobs/")
    assert first.description_html and "BIM" in first.description_html


def test_clearcompany_without_a_job_widget_is_a_parse_error() -> None:
    with pytest.raises(FetchError) as error:
        read("clearcompany", "nobody", {"https://apply.clearcompany.com/nobody": b"<html></html>"})
    assert error.value.outcome == "parse_error"


def test_schoolspring_lists_an_employers_jobs_and_reads_each_detail() -> None:
    fetched, jobs = read(
        "schoolspring",
        "Butts County Schools",
        {
            "https://api.schoolspring.com/api/Jobs/GetPagedJobsWithSearch": body(
                "schoolspring_list.json"
            ),
            "https://api.schoolspring.com/api/Jobs/5988682": body("schoolspring_job.json"),
        },
    )
    assert len(jobs) == 1 and not fetched.complete  # the other job's detail was unreachable
    job = jobs[0]
    assert job.title == "Transportation Support Coordinator"
    assert job.company_name == "Butts County Schools"
    assert job.location_text == "Jackson, Georgia"
    assert job.employment_type == "Full-time" and job.departments == ["Administration"]
    assert str(job.apply_url) == "https://www.schoolspring.com/jobs?jobid=5988682"
    assert job.description_html and "Transportation" in job.description_html


def test_pyjamahr_reads_the_career_page_api_with_the_company_name() -> None:
    fetched, jobs = read(
        "pyjamahr",
        "pyjamahr/C9047F0152",
        {
            "https://api.pyjamahr.com/api/career/jobs/?company_uuid=C9047F0152&page=1": body(
                "pyjamahr_list.json"
            ),
            "https://api.pyjamahr.com/api/career/jobs/315177/": body("pyjamahr_job.json"),
            "https://jobs.pyjamahr.com/pyjamahr": body("pyjamahr_page.html"),
        },
    )
    assert len(jobs) == 1  # the second job's detail was not served
    job = jobs[0]
    assert job.title == "Marketing Manager" and job.company_name == "PyjamaHR"
    assert job.location_text == "Bangalore, Karnataka, India" and job.workplace_type == "onsite"
    assert str(job.apply_url) == "https://jobs.pyjamahr.com/pyjamahr/marketing-manager-315177"
    assert job.description_html and "Opportunity" in job.description_html
    assert not fetched.complete


def test_recruitify_names_its_company_by_the_portal_address() -> None:
    guid = "d0e29593-9189-4e0c-83f3-94dc95dc306b"
    fetcher = FakeFetcher(
        {
            "https://api.recruitify.ai/apply/config": body("recruitify_config.json"),
            f"https://api.recruitify.ai/apply/project/{guid}": body("recruitify_job.json"),
            "https://api.recruitify.ai/apply/project": body("recruitify_list.json"),
        }
    )
    connector = CONNECTORS["recruitify"]
    fetched = connector.list_postings(fetcher, "jobs.recruitify.ai")
    [job] = [connector.parse(raw) for raw in fetched.postings]
    assert fetched.complete and job.company_name == "Recruitify"
    assert str(job.apply_url) == f"https://jobs.recruitify.ai/job/{guid}"
    assert job.description_html and "Marketing Manager" in job.description_html
    assert all(h["Origin"] == "https://jobs.recruitify.ai" for h in fetcher.headers)


def test_velora_reads_the_career_site_offers() -> None:
    fetched, jobs = read(
        "velora",
        "axactor/109",
        {"https://api.velorahr.com/api/public/career-site/109/offers": body("velora_offers.json")},
    )
    assert fetched.complete and len(jobs) == 2
    job = jobs[0]
    assert job.title == "Asset Manager GGCC" and job.company_name == "Axactor"
    assert job.city == "Madrid" and job.country_hint == "ES" and job.workplace_type == "onsite"
    assert str(job.apply_url) == "https://axactor.career.velorahr.com/axactor-109/offers/14707"
    assert job.description_html and "Axactor" in job.description_html


def test_feishu_sends_the_anonymous_token_and_reads_the_search() -> None:
    fetcher = FakeFetcher(
        {
            "https://tigertech.jobs.feishu.cn/api/v1/csrf/token": {
                "code": 0,
                "data": {"token": "anonymous-visitor-token"},
            },
            "https://tigertech.jobs.feishu.cn/api/v1/search/job/posts": body("feishu_search.json"),
        }
    )
    connector = CONNECTORS["feishu"]
    fetched = connector.list_postings(fetcher, "tigertech/index")
    jobs = [connector.parse(raw) for raw in fetched.postings]
    assert len(jobs) == 2 and not fetched.complete  # the site reports 10000 jobs; two were served
    assert fetcher.headers[-1]["x-csrf-token"] == "anonymous-visitor-token"
    assert fetcher.headers[-1]["website-path"] == "index"
    job = jobs[0]
    assert job.title and job.description_html
    assert str(job.apply_url).startswith("https://tigertech.jobs.feishu.cn/index/position/")
    assert job.posted_at is not None and job.location_text
    normalize(job, {})


def test_cats_reads_the_server_rendered_job_pages() -> None:
    fetched, jobs = read(
        "cats",
        "gmcc/45645",
        {
            "https://gmcc.catsone.com/careers/45645/jobs/": body("cats_job.html"),
            "https://gmcc.catsone.com/careers/45645": body("cats_list.html"),
        },
    )
    assert fetched.complete and len(jobs) == 4
    job = jobs[0]
    assert job.title == "Project Manager - Civil Construction"
    assert job.company_name == "Gary Merlino Construction"
    assert job.location_text == "Seattle, WA"
    assert str(job.apply_url).startswith("https://gmcc.catsone.com/careers/45645/jobs/")
    assert job.description_html and "PROJECT MANAGER" in job.description_html


def test_concludis_opens_jobs_from_script_calls_not_links() -> None:
    list_url = "https://saarstahl.concludis.de/prj/lst/a181a603769c1f98ad927e7367c7aa51/Alle.htm"
    fetched, jobs = read(
        "concludis",
        list_url,
        {
            "https://saarstahl.concludis.de/prj/shw/": body("concludis_job.html"),
            list_url: body("concludis_list.html"),
        },
    )
    assert fetched.complete and len(jobs) == 3
    assert jobs[0].title == "Software-Architekt (m/w/d)"
    assert str(jobs[0].apply_url).startswith("https://saarstahl.concludis.de/prj/shw/")
    assert jobs[0].description_html


def sitemap(*urls: str) -> bytes:
    locs = "".join(f"<url><loc>{u}</loc></url>" for u in urls)
    return f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{locs}</urlset>'.encode()


def links(*paths: str) -> bytes:
    return (
        "<html><body>" + "".join(f'<a href="{p}">job</a>' for p in paths) + "</body></html>"
    ).encode()


def test_jobylon_reads_its_sitemap_of_job_pages() -> None:
    job = "https://emp.jobylon.com/jobs/336423-sectra-cloud-engineer-healthcare-it-pacs/"
    fetched, jobs = read(
        "jobylon",
        "https://emp.jobylon.com/sitemap-jobs.xml",
        {
            "https://emp.jobylon.com/sitemap-jobs.xml": sitemap(
                job, "https://emp.jobylon.com/companies/6/jobylon/"
            ),
            job: body("jobylon_job.html"),
        },
    )
    assert fetched.complete and len(jobs) == 1
    assert jobs[0].title == "Cloud Engineer, Healthcare IT PACS"
    assert jobs[0].company_name and jobs[0].description_html


def test_airswift_reads_job_pages_linked_from_its_list() -> None:
    _fetched, jobs = read(
        "airswift",
        "https://www.airswift.com/jobs",
        {
            "https://www.airswift.com/jobs?page_num=": b"<html></html>",
            "https://www.airswift.com/jobs": links(
                "/jobs/staff-electrical-engineer-1283191", "/jobs/", "/about"
            ),
            "https://www.airswift.com/jobs/staff-electrical-engineer-1283191": body(
                "airswift_job.html"
            ),
        },
    )
    assert len(jobs) == 1 and jobs[0].title == "Staff Electrical Engineer"
    assert jobs[0].description_html and jobs[0].location_text


def test_herp_reads_job_pages_linked_from_a_company_list() -> None:
    fetched, jobs = read(
        "herp",
        "https://herp.careers/v1/herpinc",
        {
            "https://herp.careers/v1/herpinc": links(
                "/v1/herpinc/fIFcX_YmojdI", "/v1/herpinc/requisition-groups/64654cdc"
            ),
            "https://herp.careers/v1/herpinc/fIFcX_YmojdI": body("herp_job.html"),
        },
    )
    assert fetched.complete and len(jobs) == 1
    assert "HERP" in jobs[0].title and jobs[0].description_html


def test_rexx_reads_job_pages_of_a_customer_portal() -> None:
    page = "https://nobix-portal.rexx-systems.com/Account-Manager-mwd-Region-Nord-de-j271.html"
    fetched, jobs = read(
        "rexx",
        "https://nobix-portal.rexx-systems.com/stellenangebote.html",
        {
            "https://nobix-portal.rexx-systems.com/stellenangebote.html": links(
                page, "https://nobix-portal.rexx-systems.com/jobalert.html"
            ),
            page: body("rexx_job.html"),
        },
    )
    assert fetched.complete and len(jobs) == 1
    assert jobs[0].title == "Account Manager (m/w/d) Region Nord"
    assert jobs[0].company_name and jobs[0].description_html


@pytest.mark.parametrize(
    ("slug", "token"),
    [
        ("clearcompany", "bad token"),
        ("pyjamahr", "no-uuid"),
        ("velora", "axactor"),
        ("feishu", "no-path"),
        ("cats", "gmcc"),
        ("recruitify", "not a host"),
        ("schoolspring", ""),
    ],
)
def test_tokens_that_are_not_boards_are_refused(slug: str, token: str) -> None:
    with pytest.raises(ValueError):
        CONNECTORS[slug].board_url(token)
