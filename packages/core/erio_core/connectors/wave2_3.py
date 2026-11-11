"""Platforms of connector wave 2/3, found by reading the reference index
(docs/reference-sources-jobindex.md). Each reads a public, unauthenticated surface that the
platform's own sites serve to every visitor; how each was found, and its limits, is in
docs/connectors.md.

- Crelate: the RSS feed behind every candidate portal (``/portal/{org}/rss``).
- GeekJob: server-rendered ``/vacancies/{n}`` lists; every vacancy page carries JobPosting data.
"""

import re

from erio_core.connectors._util import as_url
from erio_core.connectors.base import Connector, Fetcher, FetchError
from erio_core.connectors.feed import feed_date, stable_id, xml_items
from erio_core.connectors.jsonld import JsonLdConnector, page_links
from erio_core.schemas import PartialJob, RawPosting

TOKEN = re.compile(r"[a-z0-9][a-z0-9_-]{0,62}")


# ---------------------------------------------------------------- Crelate


class CrelateConnector(Connector):
    slug = "crelate"
    hosts = frozenset({"jobs.crelate.com"})

    def board_url(self, board_token: str) -> str:
        if not TOKEN.fullmatch(board_token):
            raise ValueError(f"not a Crelate portal name: {board_token!r}")
        return f"https://jobs.crelate.com/portal/{board_token}/rss"

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        items = xml_items(body)
        # The first <title> in the document is the channel's: "{Organisation} Jobs Feed".
        channel = re.search(rb"<title>([^<]*)</title>", body)
        company = channel.group(1).decode("utf-8", "replace") if channel else ""
        company = re.sub(r"\s+Jobs Feed$", "", company).strip()
        postings = []
        for item in items:
            link = (item.get("link") or [""])[0]
            title = (item.get("title") or [""])[0]
            if not link or not title:
                continue
            postings.append(
                RawPosting(
                    source_slug=self.slug,
                    board_token=board_token,
                    external_id=link.rstrip("/").rsplit("/", 1)[-1] or stable_id(link),
                    payload={
                        "url": link,
                        "title": title,
                        "description": (item.get("description") or [""])[0] or None,
                        "location": (item.get("location") or [""])[0] or None,
                        "published": (item.get("pubdate") or [""])[0] or None,
                        "company": company or None,
                    },
                )
            )
        return postings

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["title"]).strip(),
            company_name=job.get("company"),
            apply_url=as_url(str(job["url"])),
            posted_at=feed_date(job.get("published")),
            location_text=job.get("location"),
            description_html=job.get("description"),
        )


# ---------------------------------------------------------------- GeekJob


class PathPagedJsonLdConnector(JsonLdConnector):
    """A JobPosting platform whose list is paged by path: the first page is the board
    token and page n is ``{board token}/{n}`` (GeekJob's ``/vacancies/2``)."""

    def job_pages(self, fetcher: Fetcher, board_token: str) -> list[str]:
        base = self.board_url(board_token).rstrip("/")
        links: list[str] = []
        for number in range(1, self.listing_pages + 1):
            response = fetcher.get(base if number == 1 else f"{base}/{number}")
            if response.status != 200:
                if number == 1:
                    raise FetchError("http_error", f"HTTP {response.status}", response.status)
                break
            found = page_links(response.body.decode("utf-8", "replace"), base, self.job_path)
            fresh = [link for link in found if link not in links]
            if not fresh:
                break
            links += fresh
        return links


WAVE2_3_CONNECTORS: list[Connector] = [
    CrelateConnector(),
    PathPagedJsonLdConnector(
        "geekjob",
        r"^/vacancy/[0-9a-f]{24}$",
        frozenset({"geekjob.ru"}),
        multi_employer=True,
        listing_pages=6,
        max_pages=120,
    ),
]
