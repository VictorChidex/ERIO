"""Platforms found by reading the reference site jobindex.space, second wave, batch 2.

Each reads a public, anonymous surface of the platform; how each was found, and its
limits, is in docs/connectors.md.

- AcademicTransfer: ``sitemap-vacancies.xml`` lists every vacancy page, and each page
  carries a schema.org JobPosting. robots.txt allows crawlers (crawl-delay 10 s, which
  the polite fetcher honours), so a crawl reads the newest 100 pages.
- HRMOS: the company's server-rendered ``/pages/{company}/jobs`` list (100 per page, paged
  with ``?page=n``) links each job page, and every job page carries a JobPosting.
"""

from erio_core.connectors.base import Connector
from erio_core.connectors.jsonld import JsonLdConnector

WAVE2_2_CONNECTORS: list[Connector] = [
    JsonLdConnector(
        "academictransfer",
        r"^/(en|nl)/jobs/\d+/",
        frozenset({"www.academictransfer.com"}),
        max_pages=100,
        multi_employer=True,
        newest_first=True,
    ),
    JsonLdConnector(
        "hrmos",
        r"^/pages/[^/]+/jobs/[^/]+$",
        frozenset({"hrmos.co"}),
        page_param="page",
        listing_pages=5,
    ),
]
