"""eJobSiteSoftware boards: self-hosted PHP job sites with RSS feeds per industry.

``/industry_rss.php`` links one feed per industry (``/rss/{industryId}.xml``);
a board's jobs are the union of those feeds. A crawl reads up to ``max_feeds``
of them; a board with more is reported as an incomplete fetch. The token is
``https://{board}/industry_rss.php``. Feed items carry no date and no employer.
"""

import hashlib
import html
import re
from typing import Any
from urllib.parse import urljoin, urlsplit

from erio_core.connectors._util import as_url
from erio_core.connectors.base import BoardFetch, Connector, Fetcher, FetchError
from erio_core.connectors.feed import xml_items
from erio_core.connectors.xml_boards import first
from erio_core.schemas import PartialJob, RawPosting


def site(url: str) -> str:
    """The host of a URL without a leading ``www.``."""
    return (urlsplit(url).hostname or "").removeprefix("www.")


FEED = re.compile(r"""href=["']([^"']*/rss/\d+\.xml)["']""", re.IGNORECASE)
JOB_ID = re.compile(r"^/(\d+)/")


class EJobSiteConnector(Connector):
    slug = "ejobsite"
    hosts = frozenset()
    max_feeds = 300

    def board_url(self, board_token: str) -> str:
        parts = urlsplit(board_token)
        if parts.scheme != "https" or not parts.hostname or not parts.path.endswith(".php"):
            raise ValueError(
                f"not an eJobSite token (https://{{board}}/industry_rss.php): {board_token!r}"
            )
        return board_token

    def feed_urls(self, body: bytes, board_token: str) -> list[str]:
        links = (urljoin(board_token, m) for m in FEED.findall(body.decode("utf-8", "replace")))
        return list(dict.fromkeys(u for u in links if site(u) == site(board_token)))

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        """The jobs in one industry feed (the board token is the index page)."""
        postings = []
        host = site(board_token)
        for item in xml_items(body):
            link = first(item, "link")
            if not link or not first(item, "title"):
                continue
            parts = urlsplit(link)
            if site(link) != host:
                continue  # a job must apply on the board itself, never at a stray address
            link = parts._replace(scheme="https").geturl()
            item["link"] = [link]
            match = JOB_ID.match(urlsplit(link).path)
            ident = match[1] if match else hashlib.sha256(link.encode()).hexdigest()[:24]
            postings.append(
                RawPosting(
                    source_slug=self.slug,
                    board_token=board_token,
                    external_id=ident,
                    payload=item,
                )
            )
        return postings

    def list_postings(
        self, fetcher: Fetcher, board_token: str, etag: str | None = None
    ) -> BoardFetch:
        index = fetcher.get(self.board_url(board_token))
        if index.status == 429:
            raise FetchError("rate_limited", "source rate limit", 429)
        if index.status != 200:
            raise FetchError("http_error", f"HTTP {index.status}", index.status)
        feeds = self.feed_urls(index.body, board_token)
        if not feeds:
            raise FetchError("parse_error", "no industry feeds listed", 200)
        found: dict[str, RawPosting] = {}
        unread = 0
        for url in feeds[: self.max_feeds]:
            try:
                response = fetcher.get(url)
                if response.status in (404, 410):
                    continue  # the index lists industries whose feed does not exist
                if response.status != 200:
                    unread += 1
                    continue
                for posting in self.extract(response.body, board_token):
                    found.setdefault(posting.external_id, posting)
            except (FetchError, ValueError):
                unread += 1
        if unread == len(feeds[: self.max_feeds]):
            raise FetchError("http_error", "no industry feed could be read", 200)
        return BoardFetch(
            postings=list(found.values()),
            http_status=200,
            body=index.body,
            complete=len(feeds) <= self.max_feeds and unread == 0,
        )

    def parse(self, raw: RawPosting) -> PartialJob:
        job: dict[str, Any] = raw.payload
        parts = [first(job, k) for k in ("location", "state", "country")]
        text = first(job, "description")
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=html.unescape(str(first(job, "title"))).strip(),
            apply_url=as_url(str(first(job, "link"))),
            location_text=", ".join(p for p in parts if p) or None,
            city=first(job, "location"),
            region=first(job, "state"),
            country_hint=first(job, "country"),
            description_html=text,
        )
