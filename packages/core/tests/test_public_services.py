"""Public job services: open job feeds and government job services."""

import json
from typing import Any

import pytest

from erio_core.connectors import CONNECTORS, FetchError, FetchResponse
from erio_core.connectors.public_feeds import (
    ArbeitnowConnector,
    JobicyConnector,
    PythonJobsConnector,
    RemoteOKConnector,
    WeWorkRemotelyConnector,
    WorkingNomadsConnector,
    split_python_title,
)
from erio_core.connectors.public_services import (
    WVN_SITEMAP,
    ArbetsformedlingenConnector,
    EuresConnector,
    WerkenVoorNederlandConnector,
)
from erio_core.normalize.job import normalize

SERVICES = [
    "arbeitnow",
    "remoteok",
    "weworkremotely",
    "jobicy",
    "workingnomads",
    "pythonjobs",
    "arbetsformedlingen",
    "eures",
    "werkenvoornederland",
]


class Script:
    """A fetcher that answers from a list of (substring of the URL, status, body)."""

    def __init__(self, *answers: tuple[str, int, Any]):
        self.answers = answers
        self.urls: list[str] = []
        self.posted: list[Any] = []

    def _answer(self, url: str) -> FetchResponse:
        self.urls.append(url)
        for part, status, body in self.answers:
            if part in url:
                data = body if isinstance(body, bytes) else json.dumps(body).encode()
                return FetchResponse(status, data)
        return FetchResponse(404, b"")

    def get(self, url: str, etag: str | None = None) -> FetchResponse:
        return self._answer(url)

    def post_json(self, url: str, payload: Any) -> FetchResponse:
        self.posted.append(payload)
        return self._answer(url)


def test_every_service_is_registered_and_lists_many_employers() -> None:
    for slug in SERVICES:
        connector = CONNECTORS[slug]
        assert connector.multi_employer is True  # type: ignore[attr-defined]


@pytest.mark.parametrize("slug", SERVICES)
def test_a_service_reads_only_its_own_hosts(slug: str) -> None:
    connector = CONNECTORS[slug]
    for token in ("https://evil.example.org", "http://localhost", "https://x.test/y", "a b"):
        with pytest.raises(ValueError):
            connector.board_url(token)


def test_service_tokens_name_the_host_and_nothing_else() -> None:
    arbeitnow = CONNECTORS["arbeitnow"]
    assert arbeitnow.board_url("https://www.arbeitnow.com").startswith(
        "https://www.arbeitnow.com/api/job-board-api"
    )
    assert arbeitnow.board_url("https://www.arbeitnow.co.uk/").startswith(
        "https://www.arbeitnow.co.uk/"
    )
    for token in (
        "https://www.arbeitnow.com/x",
        "https://www.arbeitnow.com?a=b",
        "https://u@www.arbeitnow.com",
    ):
        with pytest.raises(ValueError):
            arbeitnow.board_url(token)
    assert CONNECTORS["werkenvoornederland"].board_url(WVN_SITEMAP) == WVN_SITEMAP


def test_arbeitnow_decodes_the_description_and_pages_to_a_cap() -> None:
    job = {
        "slug": "dev-berlin-1",
        "company_name": "Acme GmbH",
        "title": "Backend Developer",
        "description": "&lt;p&gt;Build &amp;amp; run things&lt;/p&gt;",
        "remote": True,
        "url": "https://www.arbeitnow.com/jobs/companies/acme/dev-berlin-1",
        "tags": ["Backend"],
        "job_types": ["Full Time", "Experienced"],
        "location": "Berlin",
        "created_at": 1794250529,
    }
    page = {"data": [job], "links": {"next": "https://www.arbeitnow.com/api/job-board-api?page=2"}}
    connector = ArbeitnowConnector()
    connector.max_pages = 2
    script = Script(("page=1", 200, page), ("page=2", 200, page))
    fetched = connector.list_postings(script, "https://www.arbeitnow.com")
    assert len(fetched.postings) == 1  # the repeated job is listed once
    assert fetched.complete is False  # a third page exists that one crawl does not read
    parsed = connector.parse(fetched.postings[0])
    assert parsed.company_name == "Acme GmbH"
    assert parsed.description_html == "<p>Build &amp; run things</p>"
    assert parsed.workplace_type == "remote" and parsed.employment_type == "Full Time, Experienced"
    assert parsed.posted_at is not None and parsed.location_text == "Berlin"
    normalize(parsed, {})
    last = Script(("page=1", 200, {"data": [job], "links": {"next": None}}))
    assert connector.list_postings(last, "https://www.arbeitnow.com").complete is True


def test_remote_ok_skips_the_legal_notice_and_ignores_placeholder_salaries() -> None:
    body = json.dumps(
        [
            {"last_updated": 1, "legal": "API Terms of Service: link back"},
            {
                "id": "7",
                "slug": "x",
                "epoch": 1794153615,
                "date": "2026-11-08T16:00:15+00:00",
                "company": "Acme",
                "position": "Engineer",
                "location": "",
                "url": "https://remoteOK.com/remote-jobs/x",
                "tags": ["dev"],
                "salary_min": 120000,
                "salary_max": 150000,
                "description": "<p>Hi</p>",
            },
            {
                "id": "8",
                "company": "Beta",
                "position": "Support",
                "salary_min": 110,
                "salary_max": 0,
                "url": "https://remoteOK.com/remote-jobs/y",
                "date": None,
                "epoch": 1794153615,
            },
        ]
    ).encode()
    connector = RemoteOKConnector()
    first, second = (connector.parse(r) for r in connector.extract(body, "https://remoteok.com"))
    assert str(first.apply_url).startswith("https://remoteok.com/")
    assert first.salary is not None and (first.salary.min, first.salary.currency) == (120000, "USD")
    assert second.salary is None and second.posted_at is not None
    assert first.workplace_type == "remote" and first.company_name == "Acme"
    with pytest.raises(ValueError):
        connector.extract(b'{"not": "a list"}', "https://remoteok.com")


RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>WWR</title>
<item><title>Anchour: Marketing Designer</title><region>USA Only</region><category>Design</category>
<type>Full-Time</type><description>&lt;p&gt;Design things&lt;/p&gt;</description>
<pubDate>Mon, 09 Nov 2026 17:43:52 +0000</pubDate>
<guid>https://weworkremotely.com/remote-jobs/anchour-marketing-designer</guid></item>
<item><title>No employer in the title</title><guid>https://weworkremotely.com/remote-jobs/z</guid></item>
</channel></rss>"""


def test_we_work_remotely_splits_employer_and_title() -> None:
    connector = WeWorkRemotelyConnector()
    first, second = (
        connector.parse(r) for r in connector.extract(RSS, "https://weworkremotely.com")
    )
    assert (first.company_name, first.title) == ("Anchour", "Marketing Designer")
    assert first.location_text == "USA Only" and first.employment_type == "Full-Time"
    assert first.description_html == "<p>Design things</p>" and first.posted_at is not None
    assert second.company_name is None and second.title == "No employer in the title"
    with pytest.raises(ValueError):
        connector.extract(b"<rss><channel/></rss>", "https://weworkremotely.com")


def test_jobicy_follows_the_cursor_and_reports_a_partial_read() -> None:
    def job(number: int) -> dict[str, Any]:
        return {
            "id": number, "url": f"https://jobicy.com/jobs/{number}-x", "jobTitle": f"Role &amp; {number}",  # noqa: E501
            "companyName": "Databricks", "jobIndustry": ["Sales"], "jobType": ["Full-Time"],
            "jobGeo": "USA", "jobDescription": "<p>x</p>", "pubDate": "2026-11-09T16:32:48+00:00",
            "salaryMin": 100000, "salaryMax": 120000, "salaryCurrency": "USD", "salaryPeriod": "yearly",  # noqa: E501
        }  # fmt: skip

    connector = JobicyConnector()
    connector.max_pages = 2
    script = Script(
        ("cursor=c1", 200, {"jobs": [job(2)], "nextCursor": "c2", "hasMore": True}),
        ("count=", 200, {"jobs": [job(1)], "nextCursor": "c1", "hasMore": True}),
    )
    fetched = connector.list_postings(script, "https://jobicy.com")
    assert [p.external_id for p in fetched.postings] == ["1", "2"]
    assert fetched.complete is False
    parsed = connector.parse(fetched.postings[0])
    assert parsed.title == "Role & 1" and parsed.salary is not None
    assert (parsed.salary.min, parsed.salary.period) == (100000, "year")
    assert str(parsed.apply_url) == "https://jobicy.com/jobs/1-x"
    done = Script(("count=", 200, {"jobs": [job(1)], "nextCursor": None, "hasMore": False}))
    assert connector.list_postings(done, "https://jobicy.com").complete is True
    with pytest.raises(FetchError):
        connector.list_postings(Script(("count=", 200, b"not json")), "https://jobicy.com")


def test_working_nomads_uses_the_job_number_in_the_link() -> None:
    body = json.dumps(
        [
            {
                "url": "https://www.workingnomads.com/job/go/2007977/",
                "title": "SecOps Engineer",
                "description": "<p>x</p>",
                "company_name": "Proxify",
                "category_name": "Development",
                "tags": "a,b",
                "location": "Europe",
                "pub_date": "2026-11-09T08:52:38-05:00",
            },
            {"url": "https://www.workingnomads.com/other", "title": "no number"},
        ]
    ).encode()
    connector = WorkingNomadsConnector()
    [raw] = connector.extract(body, "https://www.workingnomads.com")
    job = connector.parse(raw)
    assert raw.external_id == "2007977" and job.company_name == "Proxify"
    assert job.departments == ["Development"] and job.posted_at is not None


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Senior Python Developer, Eliassen Group", ("Senior Python Developer", "Eliassen Group")),
        (
            "SENIOR Back-End Engineer, ActivePrime, Inc.",
            ("SENIOR Back-End Engineer", "ActivePrime, Inc."),
        ),
        ("Python Engineer, Acme, Berlin", ("Python Engineer, Acme", "Berlin")),
        ("No employer here", ("No employer here", None)),
    ],
)
def test_python_job_titles_end_with_the_employer(
    title: str, expected: tuple[str, str | None]
) -> None:
    assert split_python_title(title) == expected


def test_python_jobs_read_the_place_from_the_first_line() -> None:
    body = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>x</title>
<item><title>ML Engineer, Micro1</title><link>https://www.python.org/jobs/8201/</link>
<description>Remote, Worldwide
&lt;p&gt;Build models&lt;/p&gt;</description><guid>https://www.python.org/jobs/8201/</guid></item>
</channel></rss>"""
    connector = PythonJobsConnector()
    [raw] = connector.extract(body, "https://www.python.org")
    job = connector.parse(raw)
    assert raw.external_id == "8201" and job.company_name == "Micro1"
    assert job.location_text == "Remote, Worldwide" and job.workplace_type == "remote"
    assert job.description_html == "<p>Build models</p>" and job.posted_at is None


SWEDISH_AD = {
    "id": "31707149", "removed": False, "headline": "Barnskoetare", "webpage_url": "https://arbetsformedlingen.se/platsbanken/annonser/31707149",
    "description": {"text": "Hej\n\nVi soker <dig> & dig"}, "publication_date": "2026-11-09T20:32:09",  # noqa: E501
    "employer": {"name": "Frida Forskola AB"}, "working_hours_type": {"label": "Deltid"},
    "employment_type": {"label": "Vanlig anställning"}, "scope_of_work": {"min": 50, "max": 50},
    "application_details": {"url": "https://fridaskolan.varbi.com/what:job/jobID:9"},
    "workplace_address": {"municipality": "Uddevalla", "region": "Västra Götalands län"},
    "occupation_field": {"label": "Pedagogik"}, "workplace_model": {"label": None},
}  # fmt: skip


def test_arbetsformedlingen_pages_by_offset_and_parses_swedish_labels() -> None:
    connector = ArbetsformedlingenConnector()
    assert "offset=100" in connector.list_url("https://jobsearch.api.jobtechdev.se", 2)
    removed = SWEDISH_AD | {"id": "1", "removed": True}
    page = {"total": {"value": 150}, "hits": [SWEDISH_AD, removed]}
    script = Script(("offset=0", 200, page), ("offset=100", 200, {**page, "hits": []}))
    fetched = connector.list_postings(script, "https://jobsearch.api.jobtechdev.se")
    [raw] = fetched.postings
    job = connector.parse(raw)
    assert job.company_name == "Frida Forskola AB" and job.employment_type == "Part-time"
    assert str(job.apply_url) == "https://fridaskolan.varbi.com/what:job/jobID:9"
    assert job.location_text == "Uddevalla, Västra Götalands län" and job.country_hint == "SE"
    assert job.description_html == "<p>Hej</p><p>Vi soker &lt;dig&gt; &amp; dig</p>"
    assert normalize(job, {}).location.country_code == "SE"
    # Without an application link the job's own Platsbanken page is the apply URL.
    bare = SWEDISH_AD | {"application_details": {"url": None}}
    [raw_bare] = connector.extract(
        json.dumps({"hits": [bare]}).encode(), "https://jobsearch.api.jobtechdev.se"
    )
    assert str(connector.parse(raw_bare).apply_url) == SWEDISH_AD["webpage_url"]


def eures_job(number: int) -> dict[str, Any]:
    return {
        "id": f"id{number}", "title": f"Vacancy {number}", "description": "<p>Work</p>",
        "creationDate": 1794247928097, "locationMap": {"NO": ["NO0A2"]},
        "positionScheduleCodes": ["fulltime"], "employer": {"name": "BERGEN SMARTREPAIR AS"},
    }  # fmt: skip


def test_eures_posts_searches_page_by_page_and_stops_at_a_cap() -> None:
    connector = EuresConnector()
    connector.max_pages = 2
    full = {"numberRecords": 1000, "jvs": [eures_job(i) for i in range(50)]}
    script = Script(("jv-search/search", 200, full))
    fetched = connector.list_postings(script, "https://europa.eu")
    assert [p["page"] for p in script.posted] == [1, 2]
    assert fetched.complete is False and len(fetched.postings) == 50  # same ids on both pages
    job = connector.parse(fetched.postings[0])
    assert job.company_name == "BERGEN SMARTREPAIR AS" and job.country_hint == "NO"
    assert str(job.apply_url) == "https://europa.eu/eures/portal/jv-se/jv-details/id0?lang=en"
    assert job.employment_type == "Full-time" and job.posted_at is not None
    assert normalize(job, {}).location.country_code == "NO"
    short = Script(("jv-search/search", 200, {"numberRecords": 1, "jvs": [eures_job(1)]}))
    assert connector.list_postings(short, "https://europa.eu").complete is True
    with pytest.raises(FetchError):
        connector.list_postings(Script(("jv-search/search", 400, b"")), "https://europa.eu")
    with pytest.raises(FetchError):  # a fetcher that cannot POST cannot read EURES
        connector.list_postings(_GetOnly(), "https://europa.eu")


class _GetOnly:
    def get(self, url: str, etag: str | None = None) -> FetchResponse:
        return FetchResponse(200, b"")


WVN_PAGE = """<html><head><script type="application/ld+json">
{"@context":"https://schema.org/","@type":"JobPosting","title":"Stagebegeleider",
"description":"Korte samenvatting","datePosted":"2026-11-05","employmentType":"TEMPORARY",
"hiringOrganization":{"@type":"Organization","name":" Ministerie van Defensie"},
"jobLocation":{"@type":"Place","address":{"@type":"PostalAddress","addressLocality":"Hoogerheide","addressCountry":"NL"}}}
</script></head><body><div class="s-article-content"><p>Wat ga je doen?</p></div>
<div class="o"><div class="s-article-content"><p>Wie ben jij?</p></div></div></body></html>"""


def test_werken_voor_nederland_reads_the_vacancy_text_from_the_page() -> None:
    connector = WerkenVoorNederlandConnector()
    sitemap = (
        b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        b"<url><loc>https://www.werkenvoornederland.nl/vacatures/stage-KLU-1</loc></url>"
        b"<url><loc>https://www.werkenvoornederland.nl/organisaties/defensie</loc></url></urlset>"
    )
    script = Script(
        ("sitemap-vacatures", 200, sitemap), ("/vacatures/stage-KLU-1", 200, WVN_PAGE.encode())
    )
    fetched = connector.list_postings(script, WVN_SITEMAP)
    [raw] = fetched.postings
    job = connector.parse(raw)
    assert job.title == "Stagebegeleider" and job.company_name == "Ministerie van Defensie"
    assert job.description_html is not None
    assert "Wat ga je doen?" in job.description_html and "Wie ben jij?" in job.description_html
    assert "Korte samenvatting" not in job.description_html
    assert normalize(job, {}).location.country_code == "NL"
    assert fetched.complete is True
