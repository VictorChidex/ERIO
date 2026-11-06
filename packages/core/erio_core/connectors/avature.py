"""Avature career sites: the portal sitemap lists every job page.

The board token is the portal's sitemap URL, on Avature's own domain or on
the employer's: ``https://bloomberg.avature.net/careers/sitemap.xml`` or
``https://jobs.ea.com/en_US/careers/sitemap.xml``. Its ``JobDetail`` pages
carry the job as labelled fields (no structured data), whose labels differ by
tenant, so they are matched by meaning. A sitemap that answers empty is asked
for again: some of Avature's servers do.
"""

import re
from itertools import pairwise
from typing import Any
from urllib.parse import urlsplit

from defusedxml import ElementTree

from erio_core.connectors._htmlpages import (
    PageCrawler,
    element_at,
    listing,
    meta,
    read_date,
    text_of,
)
from erio_core.connectors._util import as_url
from erio_core.connectors.base import Fetcher, FetchError
from erio_core.connectors.jsonld import sitemap_locations
from erio_core.schemas import PartialJob, RawPosting, RemoteStatus

SITEMAP = re.compile(r"/sitemap(?:_index)?\.xml")
JOB_PAGE = re.compile(r"/JobDetail/[^/]+/(\d+)/?$")
FIELD = re.compile(
    r'<(?:div|dl)\s+class="article__content__view__field(?:\s[^"]*)?"[^>]*>', re.IGNORECASE
)
LABEL = re.compile(
    r'class="article__content__view__field__label"[^>]*>(.*?)</(?:div|dt)>', re.DOTALL
)
LISTS = re.compile(r'<ul class="MultipleDataSetFields">(.*?)</ul>', re.DOTALL)
VALUES = re.compile(r'MultipleDataSetFieldValue">(.*?)</span>', re.DOTALL)
VALUE = re.compile(r'<(?:div|dd)\s+class="article__content__view__field__value[^"]*"[^>]*>')
LOCATION_LABEL = re.compile(r"location|city", re.IGNORECASE)
COUNTRY_LABEL = re.compile(r"country", re.IGNORECASE)
TYPE_LABEL = re.compile(r"employ|contract|worker type|job type|time type|schedule", re.IGNORECASE)
DEPARTMENT_LABEL = re.compile(
    r"department|business area|domain|function|category|team", re.IGNORECASE
)
DATE_LABEL = re.compile(r"posted|publication|post date", re.IGNORECASE)
MODEL_LABEL = re.compile(r"work model|workplace|work type|remote", re.IGNORECASE)


def read_fields(html: str, title: str) -> tuple[dict[str, str], str]:
    """(labelled fields, description HTML) of a JobDetail page."""
    fields: dict[str, str] = {}
    description: list[str] = []
    starts = [m.start() for m in FIELD.finditer(html)] + [len(html)]
    for begin, end in pairwise(starts):
        block = html[begin:end]
        if "visibility--hidden" in block[:200]:
            continue
        label = LABEL.search(block)
        value = VALUE.search(block)
        inner = element_at(block, value.start()) if value else None
        if label and inner is not None:
            fields[text_of(label.group(1))] = text_of(inner)
        elif "field--locations" in block[:200] and inner is not None:
            fields["Locations"] = read_locations(inner)
        elif inner and text_of(inner) and text_of(inner) != title:
            description.append(inner.strip())
    return fields, "".join(description)


def read_locations(inner: str) -> str:
    """A locations field: the first place in text, others as lists of place, state, country."""
    first = re.sub(r"^Locations?\s*:\s*", "", text_of(inner.split("<ul", 1)[0]))
    others = [
        ", ".join(text_of(v) for v in VALUES.findall(group)) for group in LISTS.findall(inner)
    ]
    return "; ".join(dict.fromkeys(p for p in [first, *others] if p))


def pick(fields: dict[str, str], pattern: re.Pattern[str]) -> str | None:
    return next((v for k, v in fields.items() if pattern.search(k) and v), None)


class AvatureConnector(PageCrawler):
    slug = "avature"
    hosts = frozenset({"*.avature.net"})

    def board_url(self, board_token: str) -> str:
        path = urlsplit(board_token).path
        if not board_token.startswith("https://") or not SITEMAP.search(path):
            raise ValueError("an Avature board token is the https URL of the portal's sitemap.xml")
        return board_token

    def job_urls(self, fetcher: Fetcher, board_token: str) -> list[str]:
        url = self.board_url(board_token)
        try:
            pages, nested = sitemap_locations(listing(fetcher, url, attempts=4))
            for sitemap in nested[:1]:
                pages += sitemap_locations(listing(fetcher, sitemap, attempts=4))[0]
        except ElementTree.ParseError as error:
            raise FetchError("parse_error", f"malformed sitemap: {error}", 200) from error
        return [p for p in dict.fromkeys(pages) if JOB_PAGE.search(urlsplit(p).path)]

    def item_id(self, url: str, page: dict[str, Any]) -> str:
        match = JOB_PAGE.search(urlsplit(url).path)
        return match.group(1) if match else super().item_id(url, page)

    def read_page(self, url: str, body: bytes) -> dict[str, Any] | None:
        html = body.decode("utf-8", "replace")
        title = meta(html, "og:title")
        if not title:
            return None
        fields, description = read_fields(html, title)
        return {
            "title": title,
            "company": meta(html, "og:site_name"),
            "fields": fields,
            "description": description or None,
        }

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        fields: dict[str, str] = job["fields"]
        model = (pick(fields, MODEL_LABEL) or "").lower()
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
            posted_at=read_date(pick(fields, DATE_LABEL)),
            location_text=pick(fields, LOCATION_LABEL) or pick(fields, COUNTRY_LABEL),
            workplace_type=workplace,
            employment_type=pick(fields, TYPE_LABEL),
            departments=[department] if department else [],
            description_html=job.get("description"),
        )
