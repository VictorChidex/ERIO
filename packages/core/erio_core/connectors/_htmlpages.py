"""Shared by the platforms whose jobs are read from HTML pages: one request
lists the job pages of a board, then each page is fetched and read.

A crawl fetches at most ``max_pages`` job pages, one by one through the
polite fetcher. A board with more jobs is reported as an incomplete fetch, so
the jobs not read this time are never closed for being absent.
"""

import html as htmllib
import re
from abc import abstractmethod
from datetime import UTC, datetime
from typing import Any

from erio_core.connectors.base import BoardFetch, Connector, Fetcher, FetchError
from erio_core.connectors.feed import stable_id
from erio_core.schemas import RawPosting

MAX_PAGES = 150
COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
TAGS = re.compile(r"<[^>]+>")
SPACE = re.compile(r"\s+")
DATE_FORMATS = (
    "%Y-%m-%d",
    "%d %b %Y",
    "%b %d, %Y",
    "%B %d, %Y",
    "%d-%b-%Y",
    "%a %b %d %H:%M:%S UTC %Y",
)


def text_of(fragment: str) -> str:
    """Visible text of an HTML fragment, spaces collapsed."""
    spaced = re.sub(r"<(?:br|/p|/div|/li|/h\d)[^>]*>", " ", fragment, flags=re.IGNORECASE)
    return SPACE.sub(" ", htmllib.unescape(TAGS.sub("", spaced)).replace("\xa0", " ")).strip()


def element_at(html: str, start: int) -> str | None:
    """Inner HTML of the element whose opening tag begins at ``start``."""
    opening = re.compile(r"<([a-zA-Z][a-zA-Z0-9]*)[^>]*>").match(html, start)
    if not opening:
        return None
    name = opening.group(1)
    tag = re.compile(rf"<(/?){name}(?=[\s>/])[^>]*>", re.IGNORECASE)
    depth = 1
    for found in tag.finditer(html, opening.end()):
        depth += -1 if found.group(1) else 1
        if depth == 0:
            return html[opening.end() : found.start()]
    return None


def element_with(html: str, marker: str) -> str | None:
    """Inner HTML of the first element whose opening tag matches the regex ``marker``."""
    found = re.search(rf"<[a-zA-Z][^>]*{marker}[^>]*>", COMMENT.sub("", html))
    return element_at(COMMENT.sub("", html), found.start()) if found else None


def meta(html: str, name: str) -> str | None:
    """Content of ``<meta property|name|itemprop="name" content="...">``."""
    for tag in re.findall(r"<meta\s[^>]*>", html, flags=re.IGNORECASE):
        if re.search(rf'(?:property|name|itemprop)\s*=\s*["\']{re.escape(name)}["\']', tag):
            content = re.search(r'content\s*=\s*"([^"]*)"', tag)
            if content:
                return htmllib.unescape(content.group(1)).strip() or None
    return None


def read_date(value: str | None, formats: tuple[str, ...] = DATE_FORMATS) -> datetime | None:
    """A date as job pages write it; None when it is none of the unambiguous forms
    (callers add day-first or month-first forms for the platform they read)."""
    text = (value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        pass
    for form in formats:
        try:
            return datetime.strptime(text, form).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


class PageCrawler(Connector):
    """A platform read page by page. Subclasses say which pages a board has
    (``job_urls``) and what one page holds (``read_page``)."""

    max_pages = MAX_PAGES

    @abstractmethod
    def job_urls(self, fetcher: Fetcher, board_token: str) -> list[str]:
        """The job pages of one board, newest first where the source says."""

    @abstractmethod
    def read_page(self, url: str, body: bytes) -> dict[str, Any] | None:
        """What one job page holds, or None when it is not a job."""

    def item_id(self, url: str, page: dict[str, Any]) -> str:
        return stable_id(url)

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        raise ValueError(f"{self.slug}: a board is read page by page, see list_postings")

    def list_postings(
        self, fetcher: Fetcher, board_token: str, etag: str | None = None
    ) -> BoardFetch:
        urls = self.job_urls(fetcher, board_token)
        postings: list[RawPosting] = []
        unread = 0
        for url in urls[: self.max_pages]:
            try:
                response = fetcher.get(url)
            except FetchError:
                unread += 1  # one unreachable job page does not fail the board
                continue
            if response.status == 200:
                try:
                    page = self.read_page(url, response.body)
                except (ValueError, KeyError, TypeError):
                    unread += 1
                    continue
                if page:
                    postings.append(
                        RawPosting(
                            source_slug=self.slug,
                            board_token=board_token,
                            external_id=self.item_id(url, page),
                            payload={"url": url, **page},
                        )
                    )
            elif response.status not in (404, 410):
                unread += 1  # bot checks and errors: the job may still be there
        if urls and not postings:
            raise FetchError("parse_error", "job pages carry no readable job", 200)
        return BoardFetch(
            postings=postings,
            http_status=200,
            body=b"",
            complete=len(urls) <= self.max_pages and unread == 0,
        )


def listing(fetcher: Fetcher, url: str, attempts: int = 1) -> bytes:
    """A listing page's body; an empty or not-ready answer is retried, then an error."""
    for _ in range(attempts):
        response = fetcher.get(url)
        if response.status == 429:
            raise FetchError("rate_limited", "source rate limit", 429)
        if response.status == 200 and response.body.strip():
            return response.body
        if response.status not in (200, 202):
            raise FetchError("http_error", f"HTTP {response.status}", response.status)
    raise FetchError("http_error", "the listing came back empty", 200)
