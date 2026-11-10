"""Jibe, JobScore, softgarden, Get on Board and SOLID.Jobs, read from trimmed real responses."""

import json
from typing import Any

import pytest

from erio_core.connectors import CONNECTORS, FetchResponse
from erio_core.normalize.job import normalize

JIBE_PAGE = {
    "jobs": [
        {
            "data": {
                "slug": "82604",
                "language": "en-us",
                "title": "Store Supervisor - #773",
                "description": "<p>Ready for a career with limitless growth?</p>",
                "city": "ALLENTOWN",
                "state": "Pennsylvania",
                "country_code": "US",
                "full_location": "ALLENTOWN, Pennsylvania",
                "categories": [{"name": "Food Service"}],
                "tags1": ["Full-Time"],
                "tags3": ["On-Site"],
                "employment_type": "FULL_TIME",
                "hiring_organization": "Sheetz, Inc",
                "posted_date": "2026-11-10T19:25:00+0000",
                "apply_url": "https://storecareers-sheetz.icims.com/jobs/82604/login",
                "qualifications": "<ul><li>Multi-task</li></ul>",
            }
        }
    ],
    "totalCount": 150,
}

JOBSCORE = b"""<?xml version="1.0" encoding="UTF-8"?>
<jobfeed><jobs type="array"><job>
<id>dpi9LtxFTluy3ZQtfTfYWo</id><title>Senior Front-End Engineer</title>
<company_name>JobScore</company_name>
<apply_url>https://careers.jobscore.com/apply_flow/applications/go?job_id=dpi9&amp;ref=rss</apply_url>
<detail_url>https://careers.jobscore.com/careers/jobscore/jobs/senior-front-end-engineer-dpi9?ref=rss&amp;sid=68</detail_url>
<department>Engineering</department><location>Remote in Joinville, Santa Catarina, Brazil</location>
<city>Joinville</city><state>Santa Catarina</state><country>BR</country>
<opened_date type="dateTime">2026-01-20T18:35:42Z</opened_date>
<description>&lt;p&gt;About us&lt;/p&gt;</description><job_type>Full Time</job_type>
<remote>Yes | Can telecommute / work remotely 100% of the time</remote>
<hiring_team><recruiters type="array"><recruiter><name>A</name>
</recruiter></recruiters></hiring_team>
</job></jobs></jobfeed>"""

SOFTGARDEN = json.dumps(
    {
        "@type": "DataFeed",
        "dataFeedElement": [
            {
                "@type": "DataFeedItem",
                "item": {
                    "@type": "JobPosting",
                    "title": "Senior Account Executive (m/w/d)",
                    "url": "https://softgarden.career.softgarden.de/jobs/62349294/Senior/",
                    "datePosted": "2026-09-23T10:37:06.121+02:00",
                    "identifier": {"name": "softgarden", "value": 62349294},
                    "description": "<b>Deine Rolle</b>",
                    "employmentType": "FULL_TIME",
                    "hiringOrganization": {"name": "softgarden e-recruiting GmbH"},
                    "jobLocation": {
                        "address": {
                            "addressLocality": "Berlin",
                            "addressRegion": "Berlin",
                            "addressCountry": "DE",
                        }
                    },
                },
            },
            {"@type": "DataFeedItem", "item": {"@type": "JobPosting"}},
        ],
    }
).encode()

GETONBRD_JOB = {
    "id": "head-of-cybersecurity-cumplo-santiago",
    "type": "job",
    "attributes": {
        "title": "Cybersecurity Lead",
        "description_headline": "Requirements",
        "description": "<ul><li>CISSP</li></ul>",
        "benefits_headline": "Benefits",
        "benefits": "<p>Health insurance</p>",
        "remote": False,
        "remote_modality": "hybrid",
        "countries": ["Chile"],
        "category_name": "Cybersecurity",
        "published_at": 1794227297,
        "company": {
            "data": {"id": "cumplo-cl", "type": "company", "attributes": {"name": "Cumplo"}}
        },
    },
    "links": {"public_url": "https://www.getonbrd.com/jobs/head-of-cybersecurity-cumplo-santiago"},
}


class Canned:
    """A fetcher answering from a table of URL -> JSON (or bytes)."""

    def __init__(self, table: dict[str, Any]) -> None:
        self.table = table
        self.urls: list[str] = []

    def get(self, url: str, etag: str | None = None) -> FetchResponse:
        self.urls.append(url)
        body = self.table.get(url)
        if body is None:
            return FetchResponse(404, b"")
        return FetchResponse(200, body if isinstance(body, bytes) else json.dumps(body).encode())


def test_jibe_pages_through_the_career_site_and_links_to_its_job_page() -> None:
    connector = CONNECTORS["jibe"]
    page2 = {"jobs": [], "totalCount": 150}
    fetcher = Canned(
        {
            "https://jobs.sheetz.com/api/jobs?page=1&limit=100": JIBE_PAGE,
            "https://jobs.sheetz.com/api/jobs?page=2&limit=100": page2,
        }
    )
    result = connector.list_postings(fetcher, "https://jobs.sheetz.com")
    assert len(fetcher.urls) == 2 and result.complete
    [raw] = result.postings
    job = connector.parse(raw)
    assert (job.title, job.company_name, job.external_id) == (
        "Store Supervisor - #773", "Sheetz, Inc", "82604",
    )  # fmt: skip
    assert str(job.apply_url) == "https://jobs.sheetz.com/jobs/82604?lang=en-us"
    assert (job.city, job.region, job.country_hint, job.workplace_type) == (
        "ALLENTOWN", "Pennsylvania", "US", "onsite",
    )  # fmt: skip
    assert job.departments == ["Food Service"] and "limitless" in (job.description_html or "")
    normalize(job, {})


def test_jibe_refuses_a_token_that_is_not_an_https_url() -> None:
    with pytest.raises(ValueError):
        CONNECTORS["jibe"].board_url("jobs.sheetz.com")


def test_jobscore_reads_the_company_feed() -> None:
    connector = CONNECTORS["jobscore"]
    assert connector.board_url("Catrike") == "https://careers.jobscore.com/careers/catrike/feed.xml"
    with pytest.raises(ValueError):
        connector.board_url("../x")
    [raw] = connector.extract(JOBSCORE, "jobscore")
    job = connector.parse(raw)
    assert job.title == "Senior Front-End Engineer" and job.company_name == "JobScore"
    assert str(job.apply_url) == (
        "https://careers.jobscore.com/careers/jobscore/jobs/senior-front-end-engineer-dpi9"
    )
    assert (job.country_hint, job.workplace_type, job.departments) == (
        "BR",
        "remote",
        ["Engineering"],
    )
    assert job.description_html == "<p>About us</p>"
    assert job.posted_at is not None
    normalize(job, {})


def test_softgarden_reads_the_job_feed_and_skips_empty_items() -> None:
    connector = CONNECTORS["softgarden"]
    assert connector.board_url("demo") == "https://demo.career.softgarden.de/jobs.feed.json"
    with pytest.raises(ValueError):
        connector.board_url("a.b")
    [raw] = connector.extract(SOFTGARDEN, "demo")
    assert raw.external_id == "62349294"
    job = connector.parse(raw)
    assert job.company_name == "softgarden e-recruiting GmbH" and job.city == "Berlin"
    assert str(job.apply_url).startswith("https://softgarden.career.softgarden.de/jobs/")
    normalize(job, {})


def test_getonbrd_reads_each_category_and_names_the_employer() -> None:
    connector = CONNECTORS["getonbrd"]
    assert connector.multi_employer
    base = "https://www.getonbrd.com/api/v0"
    query = "per_page=100&page=1&expand=%5B%22company%22%5D"
    fetcher = Canned(
        {
            f"{base}/categories": {"data": [{"id": "programming"}, {"id": "sales"}]},
            f"{base}/categories/programming/jobs?{query}": {
                "data": [GETONBRD_JOB],
                "meta": {"page": 1, "per_page": 100, "total_pages": 1},
            },
            f"{base}/categories/sales/jobs?{query}": {
                "data": [GETONBRD_JOB],  # a job listed in two categories counts once
                "meta": {"page": 1, "per_page": 100, "total_pages": 1},
            },
        }
    )
    result = connector.list_postings(fetcher, "https://www.getonbrd.com")
    assert len(result.postings) == 1 and result.complete
    job = connector.parse(result.postings[0])
    assert (job.title, job.company_name, job.location_text) == (
        "Cybersecurity Lead",
        "Cumplo",
        "Chile",
    )
    assert job.workplace_type == "hybrid" and job.posted_at is not None
    assert "<h3>Benefits</h3>" in (job.description_html or "")
    assert str(job.apply_url).startswith("https://www.getonbrd.com/jobs/")
    normalize(job, {})
    with pytest.raises(ValueError):
        connector.board_url("https://evil.example.org")


def test_solidjobs_reads_offer_pages_newest_first() -> None:
    connector = CONNECTORS["solidjobs"]
    sitemap = (
        b'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        b"<url><loc>https://solid.jobs/offer/1/old</loc></url>"
        b"<url><loc>https://solid.jobs/offer/2/new</loc></url>"
        b"<url><loc>https://solid.jobs/blog/x</loc></url></urlset>"
    )
    token = "https://solid.jobs/sitemap-offers.xml"
    page = (
        b'<script type="application/ld+json">{"@type":"JobPosting","title":"QA","datePosted":'
        b'"2026-11-10","hiringOrganization":{"name":"DCG"},"url":"https://solid.jobs/offer/2/new",'
        b'"jobLocation":{"address":{"addressLocality":"Warszawa","addressCountry":"PL"}}}</script>'
    )
    fetcher = Canned({token: sitemap, "https://solid.jobs/offer/2/new": page})
    pages = connector.job_pages(fetcher, token)  # type: ignore[attr-defined]
    assert pages == ["https://solid.jobs/offer/2/new", "https://solid.jobs/offer/1/old"]
    [raw] = connector.list_postings(fetcher, token).postings
    job = connector.parse(raw)
    assert (job.title, job.company_name, job.country_hint) == ("QA", "DCG", "PL")
