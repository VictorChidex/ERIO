"""Platforms whose job pages carry schema.org JobPosting data, each read by a
``JsonLdConnector`` with its own start page and job-page pattern.

The board token is the page a crawl starts from: a sitemap of job URLs, or a
listing page that links to them. Platforms that host their boards on one
domain list it in ``hosts``; boards on customers' own domains are admitted
because they are registered by address (see PoliteFetcher).

How each platform was found to work, and its limits, is in docs/sources.md.
"""

import re
from urllib.parse import parse_qs, urlsplit

from erio_core.connectors.base import Connector
from erio_core.connectors.jsonld import JsonLdConnector


def hosts(*names: str) -> frozenset[str]:
    return frozenset(names)


def hirebridge_details(url: str) -> str:
    """The list links to JobDetails.aspx, which has no structured data; the v2
    details page for the same job does."""
    query = parse_qs(urlsplit(url).query)
    job, client = (query.get(name, [""])[0] for name in ("jid", "cid"))
    if re.fullmatch(r"\d{1,12}", job) and re.fullmatch(r"\d{1,12}", client):
        return (
            f"https://recruit.hirebridge.com/v3/careercenter/v2/details.aspx?jid={job}&cid={client}"
        )
    return url


JSONLD_CONNECTORS: list[Connector] = [
    # Listing pages.
    JsonLdConnector(
        "careerplug", r"^/jobs/\d+", hosts("*.careerplug.com"), page_param="page", listing_pages=5
    ),
    JsonLdConnector("firststage", r"^/jobs/[A-Za-z0-9]+/view", hosts("*.firststage.co")),
    JsonLdConnector("freshteam", r"^/jobs/[A-Za-z0-9_-]+/", hosts("*.freshteam.com")),
    JsonLdConnector(
        "hirebridge",
        r"details\.aspx",
        hosts("recruit.hirebridge.com"),
        rewrite=hirebridge_details,
    ),
    JsonLdConnector("kula", r"^/[^/]+/\d+-", hosts("careers.kula.ai")),
    JsonLdConnector(
        "recooty",
        r"^/[a-z0-9-]+/[a-z0-9-]+$",
        hosts("jobs.recooty.com"),
        page_param="page",
        listing_pages=8,
    ),
    JsonLdConnector(
        "rival",
        r"/Careers/jobs/\d+",
        hosts("jobs.silkroad.com"),
        page_param="page",
        listing_pages=6,
    ),
    # Sitemaps of job URLs.
    JsonLdConnector(
        "careersitecloud",
        r"^/job-[0-9a-f]{24}",
        hosts("*.careersitecloud.com"),
        multi_employer=True,
    ),
    JsonLdConnector("deel", r"/job-details/", hosts("jobs.deel.com")),
    JsonLdConnector("icims", r"^/jobs/\d+/", hosts("*.icims.com"), page_query="in_iframe=1"),
    JsonLdConnector("jboard", r"^/jobs/\d+", multi_employer=True),
    JsonLdConnector("jobboard_com", r"^/jobs/[^/]+/\d+-", multi_employer=True),
    JsonLdConnector("jobboardfire", r"^/j/", multi_employer=True),
    JsonLdConnector("jobiqo", r"^/job/", multi_employer=True),
    JsonLdConnector("jobmount", r"^/career/\d+", multi_employer=True),
    JsonLdConnector("niceboard", r"^/job/\d+", hosts("*.niceboard.co"), multi_employer=True),
    JsonLdConnector("nodex", r"^/job/", country_from_host=True, multi_employer=True),
    JsonLdConnector("paradox", r"/job/[0-9a-f]{32}"),
    JsonLdConnector(
        "solidjobs",
        r"^/offer/\d+/",
        hosts("solid.jobs"),
        multi_employer=True,
        newest_first=True,
    ),
]
