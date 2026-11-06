"""SAP SuccessFactors career sites (Career Site Builder) on employers' own domains.

The site's ``/sitemap.xml`` lists every job page, and each page marks its job
up with schema.org microdata plus labelled tokens whose labels differ by site
(location, requisition, job type). The board token is the site's address,
``https://jobs.ball.com``. The ``/services/`` paths, including its RSS feed,
are disallowed by these sites' robots.txt and are never read.
"""

import re
from itertools import pairwise
from typing import Any
from urllib.parse import urlsplit

from defusedxml import ElementTree

from erio_core.connectors._htmlpages import (
    COMMENT,
    PageCrawler,
    element_at,
    listing,
    meta,
    read_date,
    text_of,
)
from erio_core.connectors._paged import base_url
from erio_core.connectors._util import as_url
from erio_core.connectors.base import Fetcher, FetchError
from erio_core.connectors.jsonld import sitemap_locations
from erio_core.schemas import PartialJob, RawPosting, RemoteStatus

JOB_PAGE = re.compile(r"/job/[^/]+/(\d+)/?$")
NOISE = re.compile(r"<(style|script)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
TOKEN = re.compile(r'<div class="joblayouttoken[^"]*"[^>]*>')
LABEL = re.compile(r"joblayouttoken-label[^>]*>(.*?)</span>", re.DOTALL)
DESCRIPTION = re.compile(r'<[a-z]+[^>]*itemprop="description"[^>]*>', re.IGNORECASE)
TITLE = re.compile(r'<[a-z]+[^>]*itemprop="title"[^>]*>', re.IGNORECASE)
JOB_LOCATION = re.compile(r'<p id="job-location"[^>]*>')
LOCATION_LABEL = re.compile(r"^location", re.IGNORECASE)
TYPE_LABEL = re.compile(r"job type|employment type|time type|schedule|worker type", re.IGNORECASE)
WORKPLACE_LABEL = re.compile(r"workplace|work model|remote", re.IGNORECASE)
DEPARTMENT_LABEL = re.compile(r"department|category|function|job family", re.IGNORECASE)
DATE_LABEL = re.compile(r"date", re.IGNORECASE)
DATES = ("%m/%d/%y", "%d/%m/%Y", "%d %b %Y", "%b %d, %Y", "%B %d, %Y")


def tokens(html: str) -> tuple[dict[str, str], str | None]:
    """(labelled tokens, the first short unlabelled token before the description)."""
    fields: dict[str, str] = {}
    unlabelled: str | None = None
    starts = [m.start() for m in TOKEN.finditer(html)] + [len(html)]
    for begin, end in pairwise(starts):
        block = html[begin:end]
        if DESCRIPTION.search(block):
            break
        label = LABEL.search(block)
        if label:
            name = text_of(label.group(1)).rstrip(":").strip()
            value = text_of(block[label.end() :])
            if name and value:
                fields[name] = value
        elif not TITLE.search(block) and unlabelled is None:
            text = text_of(block)
            if text and len(text) <= 100:
                unlabelled = text
    return fields, unlabelled


def address(html: str) -> str | None:
    parts = [meta(html, name) for name in ("addressLocality", "addressRegion", "addressCountry")]
    joined = ", ".join(p for p in parts if p)
    return joined or meta(html, "streetAddress")


def pick(fields: dict[str, str], pattern: re.Pattern[str]) -> str | None:
    return next((v for k, v in fields.items() if pattern.search(k)), None)


class SuccessFactorsConnector(PageCrawler):
    slug = "successfactors"
    hosts: frozenset[str] = frozenset()

    def board_url(self, board_token: str) -> str:
        return f"{base_url(board_token)}/sitemap.xml"

    def job_urls(self, fetcher: Fetcher, board_token: str) -> list[str]:
        try:
            pages, nested = sitemap_locations(listing(fetcher, self.board_url(board_token)))
            for sitemap in nested[:1]:
                pages += sitemap_locations(listing(fetcher, sitemap))[0]
        except ElementTree.ParseError as error:
            raise FetchError("parse_error", f"malformed sitemap: {error}", 200) from error
        return [p for p in dict.fromkeys(pages) if JOB_PAGE.search(urlsplit(p).path)]

    def item_id(self, url: str, page: dict[str, Any]) -> str:
        match = JOB_PAGE.search(urlsplit(url).path)
        return match.group(1) if match else super().item_id(url, page)

    def read_page(self, url: str, body: bytes) -> dict[str, Any] | None:
        html = NOISE.sub("", COMMENT.sub("", body.decode("utf-8", "replace")))
        found = TITLE.search(html)
        title = text_of(element_at(html, found.start()) or "") if found else ""
        title = title or meta(html, "og:title") or ""
        if not title:
            return None
        fields, unlabelled = tokens(html)
        place = JOB_LOCATION.search(html)
        location = (
            pick(fields, LOCATION_LABEL)
            or address(html)
            or (text_of(element_at(html, place.start()) or "") if place else None)
            or unlabelled
        )
        description = "".join(
            (element_at(html, m.start()) or "").strip() for m in DESCRIPTION.finditer(html)
        )
        return {
            "title": title,
            "company": meta(html, "hiringOrganization"),
            "location": location or None,
            "posted": meta(html, "datePosted") or pick(fields, DATE_LABEL),
            "fields": fields,
            "description": description or None,
        }

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        fields: dict[str, str] = job["fields"]
        model = (pick(fields, WORKPLACE_LABEL) or "").lower()
        workplace: RemoteStatus | None = next(
            (w for w in ("remote", "hybrid") if w in model), "onsite" if "site" in model else None
        )
        department = pick(fields, DEPARTMENT_LABEL)
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["title"]).strip(),
            company_name=job.get("company"),
            apply_url=as_url(str(job["url"])),
            posted_at=read_date(job.get("posted"), (*DATES, "%a %b %d %H:%M:%S UTC %Y")),
            location_text=job.get("location"),
            workplace_type=workplace,
            employment_type=pick(fields, TYPE_LABEL),
            departments=[department] if department else [],
            description_html=job.get("description"),
        )
