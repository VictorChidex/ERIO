"""Platforms whose job pages carry schema.org JobPosting data, each read by a
``JsonLdConnector`` with its own start page and job-page pattern.

The board token is the page a crawl starts from: a sitemap of job URLs, or a
listing page that links to them. Platforms that host their boards on one
domain list it in ``hosts``; boards on customers' own domains are admitted
because they are registered by address (see PoliteFetcher).

How each platform was found to work, and its limits, is in docs/sources.md.
"""

import re
from urllib.parse import parse_qs, urljoin, urlsplit

from erio_core.connectors.base import Connector, Fetcher, FetchError
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


class ConcludisConnector(JsonLdConnector):
    """concludis career pages: the job list opens each job with a script call
    (``cJobboard.openJob('...')``), not a link, and every job page carries a JobPosting."""

    OPEN_JOB = re.compile(r"openJob\('([^']+)'")

    def job_pages(self, fetcher: Fetcher, board_token: str) -> list[str]:
        response = fetcher.get(self.board_url(board_token))
        if response.status != 200:
            raise FetchError("http_error", f"HTTP {response.status}", response.status)
        found = self.OPEN_JOB.findall(response.body.decode("utf-8", "replace"))
        host = urlsplit(board_token).hostname
        pages = [urljoin(board_token, url.replace("&amp;", "&")) for url in found]
        return list(dict.fromkeys(u for u in pages if urlsplit(u).hostname == host))


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
    JsonLdConnector(
        "airswift",
        r"^/jobs/[a-z0-9-]+-\d+$",
        hosts("www.airswift.com", "airswift.com"),
        multi_employer=True,
        page_param="page_num",
        listing_pages=5,
    ),
    JsonLdConnector("herp", r"^/v1/[^/]+/[A-Za-z0-9_-]{12}$", hosts("herp.careers")),
    JsonLdConnector("rexx", r"-j\d+\.html$", hosts("*.rexx-systems.com")),
    ConcludisConnector("concludis", r"^/prj/shw/", hosts("*.concludis.de")),
    # Sitemaps of job URLs.
    JsonLdConnector(
        "careersitecloud",
        r"^/job-[0-9a-f]{24}",
        hosts("*.careersitecloud.com"),
        multi_employer=True,
    ),
    JsonLdConnector("deel", r"/job-details/", hosts("jobs.deel.com")),
    JsonLdConnector("icims", r"^/jobs/\d+/", hosts("*.icims.com"), page_query="in_iframe=1"),
    JsonLdConnector("jobylon", r"^/jobs/\d+-", hosts("emp.jobylon.com"), multi_employer=True),
    JsonLdConnector("jboard", r"^/jobs/\d+", multi_employer=True),
    JsonLdConnector("jobboard_com", r"^/jobs/[^/]+/\d+-", multi_employer=True),
    JsonLdConnector("jobboardfire", r"^/j/", multi_employer=True),
    JsonLdConnector("jobiqo", r"^/job/", multi_employer=True),
    JsonLdConnector("jobmount", r"^/career/\d+", multi_employer=True),
    JsonLdConnector("niceboard", r"^/job/\d+", hosts("*.niceboard.co"), multi_employer=True),
    JsonLdConnector("nodex", r"^/job/", country_from_host=True, multi_employer=True),
    JsonLdConnector("paradox", r"/job/[0-9a-f]{32}"),
    # Found by comparing with the reference index (docs/reference-study-jobindex.md).
    JsonLdConnector(
        "pandape",
        r"^/Detail/\d+",
        hosts("*.pandape.infojobs.com.br"),
        page_param="PageNumber",
        listing_pages=5,
    ),
    JsonLdConnector("factorial", r"^/job_posting/", hosts("*.factorialhr.com", "*.factorial.com")),
    JsonLdConnector("coveto", r"^/job-.+\.html$", hosts("*.coveto.de")),
    # Every language of a site lists the same job, and each site has a spontaneous-application
    # page per language that is not an opening.
    JsonLdConnector(
        "jobtoolz",
        r"^/[a-z]{2}/(?!spontaan|apply-spontaneously|candidature-spontanee|initiativ)[^/]+$",
        hosts("*.jobtoolz.com"),
    ),
    JsonLdConnector(
        "instaffo",
        r"^/en/job/",
        hosts("jobs.instaffo.com"),
        max_pages=100,
        multi_employer=True,
    ),
    JsonLdConnector(
        "jobberman", r"^/listings/", hosts("www.jobberman.com"), max_pages=100, multi_employer=True
    ),
    JsonLdConnector(
        "brightermonday",
        r"^/listings/",
        hosts("www.brightermonday.co.ke", "www.brightermonday.co.ug"),
        max_pages=100,
        multi_employer=True,
    ),
    JsonLdConnector("torre", r"^/post/", hosts("torre.ai"), max_pages=100, multi_employer=True),
    JsonLdConnector(
        "solidjobs",
        r"^/offer/\d+/",
        hosts("solid.jobs"),
        multi_employer=True,
        newest_first=True,
    ),
]
