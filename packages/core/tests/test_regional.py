"""Connectors for InHire, Solides, Senior Portal de Talentos, The Hub, Recrutei, Apploi,
Cegid DigitalRecruiters, Intervieweb, AppliTrack and CHECK-IN, against responses
recorded from the real sites (trimmed) in fixtures/regional/."""

import json
from pathlib import Path
from typing import Any

import pytest

from erio_core.connectors import CONNECTORS, FetchError, FetchResponse
from erio_core.normalize.job import normalize

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "regional"


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class Script:
    """A fetcher answering from a table of URL -> body; anything else is a 404."""

    def __init__(self, pages: dict[str, bytes]):
        self.pages = pages
        self.urls: list[str] = []
        self.headers: list[dict[str, str]] = []
        self.posted: list[Any] = []

    def get(self, url: str, etag: str | None = None) -> FetchResponse:
        self.urls.append(url)
        body = self.pages.get(url)
        return FetchResponse(200, body) if body is not None else FetchResponse(404, b"")

    def get_with(self, url: str, headers: dict[str, str]) -> FetchResponse:
        self.headers.append(headers)
        return self.get(url)

    def post_json(self, url: str, payload: Any) -> FetchResponse:
        self.urls.append(url)
        self.posted.append(payload)
        body = self.pages.get(url)
        return FetchResponse(200, body) if body is not None else FetchResponse(404, b"")


def read(slug: str, fetcher: Script, token: str) -> Any:
    connector = CONNECTORS[slug]
    fetched = connector.list_postings(fetcher, token)
    jobs = [connector.parse(raw) for raw in fetched.postings]
    for job in jobs:
        assert job.title and str(job.apply_url).startswith("https://")
        normalize(job, {})
    return fetched, jobs


def test_inhire_sends_the_tenant_header_and_builds_the_job_address() -> None:
    url = "https://api.inhire.app/job-posts/public/pages"
    fetcher = Script({url: fixture("inhire.json")})
    fetched, jobs = read("inhire", fetcher, "riachuelo")
    assert fetcher.headers == [{"X-Tenant": "riachuelo"}]
    assert fetched.complete and len(jobs) == 4
    first = jobs[0]
    assert first.company_name == "Riachuelo"
    assert first.location_text and first.workplace_type in ("hybrid", "onsite", "remote")
    assert str(first.apply_url).startswith("https://riachuelo.inhire.app/vagas/")
    assert str(first.apply_url).split("/")[-1].islower()


def test_inhire_refuses_a_token_that_is_not_a_tenant() -> None:
    for token in ("a b", "x.evil.example", "https://evil.example"):
        with pytest.raises(ValueError):
            CONNECTORS["inhire"].board_url(token)


def test_solides_reads_the_portals_list_and_pages_until_the_last_page() -> None:
    data = json.loads(fixture("solides.json"))
    data["totalPages"] = 1
    url = "https://vagas.solides.com.br/api/vacancies?page=1&take=20&locations="
    fetcher = Script({url: json.dumps(data).encode()})
    fetched, jobs = read("solides", fetcher, "https://vagas.solides.com.br")
    assert fetched.complete and len(jobs) == 2
    assert jobs[0].company_name and jobs[0].country_hint == "BR"
    assert str(jobs[0].apply_url) == f"https://vagas.solides.com.br/vaga/{jobs[0].external_id}"
    assert jobs[0].description_html


def test_solides_reports_a_partial_read_when_the_portal_has_more_pages() -> None:
    data = json.loads(fixture("solides.json"))
    data["totalPages"] = 3500
    pages = {
        f"https://vagas.solides.com.br/api/vacancies?page={n}&take=20&locations=": json.dumps(
            {**data, "data": [{**data["data"][0], "id": 1000 + n}]}
        ).encode()
        for n in range(1, 26)
    }
    fetched = CONNECTORS["solides"].list_postings(Script(pages), "https://vagas.solides.com.br")
    assert not fetched.complete and len(fetched.postings) == 25


def test_senior_talentos_posts_the_search_and_links_to_the_employers_portal() -> None:
    data = json.loads(fixture("senior_talentos.json"))
    data["totalPages"] = 1
    connector = CONNECTORS["senior_talentos"]
    url = connector.board_url("https://platform.senior.com.br")
    fetcher = Script({url: json.dumps(data).encode()})
    fetched, jobs = read("senior_talentos", fetcher, "https://platform.senior.com.br")
    assert fetcher.posted == [{"page": 0, "size": 100, "filter": "", "match": {}}]
    assert fetched.complete and len(jobs) == 3
    assert jobs[0].company_name and jobs[0].country_hint == "BR"
    assert ".portaldetalentos.senior.com.br/vacancy/" in str(jobs[0].apply_url)


def test_senior_talentos_fails_the_fetch_on_a_payload_it_does_not_know() -> None:
    connector = CONNECTORS["senior_talentos"]
    url = connector.board_url("https://platform.senior.com.br")
    with pytest.raises(FetchError) as error:
        connector.list_postings(
            Script({url: b'{"unexpected": true}'}), "https://platform.senior.com.br"
        )
    assert error.value.outcome == "parse_error"


SITEMAP = """<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{}</urlset>"""


def sitemap(*urls: str) -> bytes:
    return SITEMAP.format("".join(f"<url><loc>{u}</loc></url>" for u in urls)).encode()


@pytest.mark.parametrize(
    ("slug", "token", "job_url", "page", "other"),
    [
        (
            "thehub",
            "https://thehub.io/sitemap-jobs.xml",
            "https://thehub.io/jobs/6aa95a32eb03374734bd1fe2",
            "thehub_job.html",
            "https://thehub.io/startups/some-company",
        ),
        (
            "recrutei",
            "https://empregos.recrutei.com.br/sitemap-vagas-1.xml",
            "https://empregos.recrutei.com.br/vaga/prosul/165146-almoxarife",
            "recrutei_job.html",
            "https://empregos.recrutei.com.br/vagas/dados",
        ),
        (
            "cegid",
            "https://recrutement.example.fr/sitemap.xml",
            "https://recrutement.example.fr/fr/annonce/4687379-ergotherapeute",
            "cegid_job.html",
            "https://recrutement.example.fr/fr/offres",
        ),
    ],
)
def test_sitemap_platforms_read_only_job_pages(
    slug: str, token: str, job_url: str, page: str, other: str
) -> None:
    fetcher = Script({token: sitemap(job_url, other), job_url: fixture(page)})
    _, jobs = read(slug, fetcher, token)
    assert len(jobs) == 1 and other not in fetcher.urls
    assert jobs[0].company_name and jobs[0].description_html


def test_apploi_reads_a_company_page_and_strips_tracking_from_job_links() -> None:
    board = "https://apply-jobs.apploi.com/jobs/elcor"
    job = "https://apply-jobs.apploi.com/job/590965/elcor/social-worker"
    listing = (
        b'<a href="/job/590965/elcor/social-worker?utm_source=company_profile_page">x</a>'
        b'<a href="/jobs/other">other company</a>'
    )
    fetcher = Script({board: listing, job: fixture("apploi_job.html")})
    _, jobs = read("apploi", fetcher, board)
    assert len(jobs) == 1 and str(jobs[0].apply_url) == job
    assert "https://apply-jobs.apploi.com/jobs/other" not in fetcher.urls


def test_intervieweb_reports_a_partial_read_when_the_career_page_has_more_pages() -> None:
    board = "https://inrecruiting.intervieweb.it/orbyta/it/career"
    job = "https://inrecruiting.intervieweb.it/orbyta/jobs/sistemista-it-torino-738225/it/"
    one = f'Pagina 1 di 1 <a href="{job}">x</a>'.encode()
    more = f'Pagina 1 di 2 <a href="{job}">x</a>'.encode()
    page = fixture("intervieweb_job.html")
    whole, jobs = read("intervieweb", Script({board: one, job: page}), board)
    assert whole.complete and len(jobs) == 1
    part, _ = read("intervieweb", Script({board: more, job: page}), board)
    assert not part.complete


def test_applitrack_reads_every_posting_on_the_embedded_list() -> None:
    url = CONNECTORS["applitrack"].board_url("keyport")
    _, jobs = read("applitrack", Script({url: fixture("applitrack_keyport.html")}), "keyport")
    assert [j.title for j in jobs] == [
        "Substitute Custodian",
        "Student Interns - Custodial/Technology",
    ]
    first = jobs[0]
    assert first.company_name == "Keyport Board of Education"
    assert first.location_text == "Keyport Public Schools"
    assert first.posted_at and first.posted_at.date().isoformat() == "2023-06-01"
    assert "AppliTrackJobId=2173" in str(first.apply_url)


def test_checkin_follows_the_list_to_the_job_pages_and_reads_their_microdata() -> None:
    host = "https://sparkassenversicherung-karriereportal.mein-check-in.de"
    first = "/detail/03efcf07-a5e7-11f1-9115-005056017160"
    pages = {
        f"{host}/list?keywords=&page=1": fixture("checkin_list.html"),
        f"{host}/list?keywords=&page=2": b"<html></html>",
        host + first: fixture("checkin_job.html"),
    }
    _, jobs = read("checkin", Script(pages), "sparkassenversicherung-karriereportal")
    assert len(jobs) == 1  # the other two listed jobs are not in the script: 404, skipped
    job = jobs[0]
    assert job.company_name == "SV SparkassenVersicherung"
    assert job.city == "Stuttgart" and job.region == "Baden-Württemberg"
    assert job.description_html and str(job.apply_url) == host + first


def test_checkin_refuses_a_portal_name_that_is_not_a_subdomain() -> None:
    with pytest.raises(ValueError):
        CONNECTORS["checkin"].board_url("evil.example/x")
