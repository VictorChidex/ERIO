"""The generic connectors: job feeds and schema.org JobPosting pages."""

import json

import pytest

from erio_core.connectors import FetchError, FetchResponse
from erio_core.connectors.feed import FeedConnector, feed_date, parse_feed
from erio_core.connectors.jsonld import (
    JsonLdConnector,
    job_postings,
    page_links,
    sitemap_locations,
)
from erio_core.normalize.employment import employment_type

RSS = b"""<?xml version="1.0"?>
<rss version="2.0" xmlns:job="https://example.org/job">
<channel><title>Jobs</title>
<item><title>Backend Engineer</title><link>https://jobs.example.org/job/1</link>
<guid>job-1</guid><pubDate>Tue, 04 Nov 2026 10:00:00 GMT</pubDate>
<description><![CDATA[<p>Build APIs.</p>]]></description>
<job:location>Lagos, Nigeria</job:location><job:company>Paystack</job:company>
<job:type>Full-time</job:type></item>
<item><title>No link</title></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><id>urn:job:7</id><title>Designer</title><link href="https://jobs.example.org/job/7"/>
<updated>2026-11-01T09:00:00Z</updated><summary>Design things. Remote.</summary></entry></feed>"""

INDEED = b"""<?xml version="1.0"?><source><publisher>Board</publisher>
<job><title><![CDATA[Nurse]]></title><date>Mon, 03 Nov 2026 08:00:00 GMT</date>
<referencenumber>N-77</referencenumber><url>https://board.example.org/jobs/77</url>
<company>Clinic</company><city>Nairobi</city><country>KE</country>
<description>Care for patients.</description><jobtype>contract</jobtype>
<remotetype></remotetype></job></source>"""


def test_rss_atom_and_indeed_feeds_read_alike() -> None:
    [rss] = parse_feed(RSS)  # the item without a link is dropped
    assert (rss["title"], rss["url"], rss["id"]) == (
        "Backend Engineer", "https://jobs.example.org/job/1", "job-1",
    )  # fmt: skip
    assert (rss["location"], rss["company"], rss["employment_type"]) == (
        "Lagos, Nigeria", "Paystack", "Full-time",
    )  # fmt: skip
    assert rss["description"] == "<p>Build APIs.</p>"
    [atom] = parse_feed(ATOM)
    assert (atom["id"], atom["url"], atom["description"]) == (
        "urn:job:7", "https://jobs.example.org/job/7", "Design things. Remote.",
    )  # fmt: skip
    [indeed] = parse_feed(INDEED)
    assert (indeed["id"], indeed["location"], indeed["employment_type"]) == (
        "N-77", "Nairobi, KE", "contract",
    )  # fmt: skip


@pytest.mark.parametrize("body", [b"not xml", b"<html><body>hi</body></html>"])
def test_anything_else_is_not_a_feed(body: bytes) -> None:
    with pytest.raises(ValueError):
        parse_feed(body)


def test_feed_dates() -> None:
    assert feed_date("Tue, 04 Nov 2026 10:00:00 GMT").isoformat() == "2026-11-04T10:00:00+00:00"  # type: ignore[union-attr]
    assert feed_date("2026-11-01T09:00:00Z").isoformat() == "2026-11-01T09:00:00+00:00"  # type: ignore[union-attr]
    assert feed_date("someday") is None


def test_feed_connector_end_to_end() -> None:
    connector = FeedConnector(
        "niceboard", frozenset({"*.niceboard.co"}), "https://{token}.niceboard.co/rss"
    )
    assert connector.board_url("techjobs") == "https://techjobs.niceboard.co/rss"
    assert connector.board_url("https://jobs.example.org/feed") == "https://jobs.example.org/feed"
    with pytest.raises(ValueError):
        connector.board_url("../etc")
    [raw] = connector.extract(RSS, "techjobs")
    job = connector.parse(raw)
    assert (job.title, str(job.apply_url), job.company_name) == (
        "Backend Engineer", "https://jobs.example.org/job/1", "Paystack",
    )  # fmt: skip
    assert job.posted_at is not None and job.employment_type == "Full-time"
    # Remote comes from the location or a remote field, not from words in the description.
    assert connector.parse(connector.extract(ATOM, "x")[0]).workplace_type is None
    # Stable IDs: the same item always gets the same external ID.
    assert raw.external_id == connector.extract(RSS, "techjobs")[0].external_id


POSTING = {
    "@context": "https://schema.org",
    "@type": "JobPosting",
    "title": "Data Analyst",
    "description": "<p>Analyse data.</p>",
    "datePosted": "2026-10-30",
    "employmentType": ["FULL_TIME"],
    "hiringOrganization": {"@type": "Organization", "name": "Flutterwave"},
    "jobLocation": [
        {"@type": "Place", "address": {"addressLocality": "Lagos", "addressCountry": "NG"}}
    ],
    "baseSalary": {
        "@type": "MonetaryAmount",
        "currency": "NGN",
        "value": {
            "@type": "QuantitativeValue",
            "minValue": 500000,
            "maxValue": 800000,
            "unitText": "MONTH",
        },
    },
    "identifier": {"@type": "PropertyValue", "value": "FW-12"},
}


def page(*objects: object) -> str:
    blocks = "".join(
        f'<script type="application/ld+json">{json.dumps(o)}</script>' for o in objects
    )
    return f"<html><head>{blocks}<script type='application/ld+json'>{{broken</script></head></html>"


def test_job_postings_are_found_anywhere_in_the_json_ld() -> None:
    assert job_postings(page(POSTING)) == [POSTING]
    graph = {"@context": "https://schema.org", "@graph": [{"@type": "WebPage"}, POSTING]}
    assert job_postings(page(graph)) == [POSTING]
    assert job_postings(page({"@type": ["JobPosting", "Thing"], "title": "X"}))[0]["title"] == "X"
    assert job_postings("<html>no data</html>") == []


def test_listing_links_and_sitemaps() -> None:
    import re

    html = """<a href="/jobs/1-analyst">A</a><a href="/jobs/1-analyst#apply">A</a>
    <a href="https://other.example.org/jobs/2">B</a><a href="/about">C</a>
    <a href="http://board.example.org/jobs/3">insecure</a>"""
    assert page_links(html, "https://board.example.org/jobs", re.compile(r"^/jobs/\d")) == [
        "https://board.example.org/jobs/1-analyst"
    ]
    urls = b"""<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url><loc>https://board.example.org/jobs/1</loc></url><url><loc>https://board.example.org/about</loc></url></urlset>"""
    assert sitemap_locations(urls) == (
        ["https://board.example.org/jobs/1", "https://board.example.org/about"], [],
    )  # fmt: skip
    index = b"""<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <sitemap><loc>https://board.example.org/sitemap-jobs.xml</loc></sitemap></sitemapindex>"""
    assert sitemap_locations(index) == ([], ["https://board.example.org/sitemap-jobs.xml"])


class Site:
    def __init__(self, pages: dict[str, tuple[int, str]]):
        self.pages = pages
        self.asked: list[str] = []

    def get(self, url: str, etag: str | None = None) -> FetchResponse:
        self.asked.append(url)
        status, body = self.pages.get(url, (404, ""))
        return FetchResponse(status, body.encode())


def test_jsonld_connector_crawls_listing_then_job_pages() -> None:
    connector = JsonLdConnector("talenetic", r"^/jobs/\d", max_pages=2)
    site = Site(
        {
            "https://board.example.org/jobs": (
                200,
                '<a href="/jobs/1">1</a><a href="/jobs/2">2</a><a href="/jobs/3">3</a>',
            ),
            "https://board.example.org/jobs/1": (200, page(POSTING)),
            "https://board.example.org/jobs/2": (500, ""),
        }
    )

    fetched = connector.list_postings(site, "https://board.example.org/jobs")

    # At most max_pages job pages a crawl; a failing page is skipped.
    assert site.asked == [
        "https://board.example.org/jobs",
        "https://board.example.org/jobs/1",
        "https://board.example.org/jobs/2",
    ]
    [raw] = fetched.postings
    assert raw.board_token == "https://board.example.org/jobs"
    job = connector.parse(raw)
    assert (job.title, job.company_name, job.city, job.country_hint) == (
        "Data Analyst", "Flutterwave", "Lagos", "NG",
    )  # fmt: skip
    assert str(job.apply_url) == "https://board.example.org/jobs/1"
    assert job.salary is not None and (job.salary.min, job.salary.currency, job.salary.period) == (
        500000, "NGN", "month",
    )  # fmt: skip
    assert employment_type(job.employment_type) == "full_time"


def test_jsonld_connector_fails_the_fetch_when_pages_have_no_data() -> None:
    connector = JsonLdConnector("x", r"^/jobs/")
    site = Site(
        {
            "https://b.example.org/": (200, '<a href="/jobs/1">1</a>'),
            "https://b.example.org/jobs/1": (200, "<html>no data</html>"),
        }
    )
    with pytest.raises(FetchError) as error:
        connector.list_postings(site, "https://b.example.org/")
    assert error.value.outcome == "parse_error"
    with pytest.raises(ValueError):
        connector.board_url("b.example.org")


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("FULL_TIME", "full_time"), ("Full-time, permanent", "full_time"),
        ("FullTime", "full_time"), ("fulltime_permanent", "full_time"),
        ("Part time", "part_time"), ("CONTRACTOR", "contract"), ("Freelance", "contract"),
        ("Fixed-term", "temporary"), ("INTERN", "internship"), ("Graduate trainee", "internship"),
        ("Volunteer", "volunteer"), ("Hybrid", None), (None, None),
    ],
)  # fmt: skip
def test_employment_type_wording(text: str | None, kind: str | None) -> None:
    assert employment_type(text) == kind
