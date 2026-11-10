"""CATS (catsone.com) career portals: ``https://{account}.catsone.com/careers/{portalId}``.

The portal lists every open job on one page and renders each job page on the server, with
its title, tags (place, pay) and description as HTML; there is no public JSON (CATS's API
needs a key) and no structured data. The board token is "{account}/{portalId}", for
example "gmcc/45645".
"""

import re
from typing import Any

from erio_core.connectors._htmlpages import PageCrawler, element_with, listing, text_of
from erio_core.connectors._util import as_url
from erio_core.connectors.base import Fetcher
from erio_core.schemas import PartialJob, RawPosting

TOKEN = re.compile(r"([a-z0-9][a-z0-9-]{0,62})/(\d{1,10})")
TITLE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.DOTALL)
TAGS = re.compile(r'<ul class="job-tags">(.*?)</ul>', re.DOTALL)
LOGO = re.compile(r'<img class="logo-image"[^>]*\balt="([^"]*)"')


def _parts(board_token: str) -> tuple[str, str]:
    match = TOKEN.fullmatch(board_token)
    if not match:
        raise ValueError(f"not a CATS portal token (account/portalId): {board_token!r}")
    return match[1], match[2]


class CatsConnector(PageCrawler):
    slug = "cats"
    hosts = frozenset({"*.catsone.com"})

    def board_url(self, board_token: str) -> str:
        account, portal = _parts(board_token)
        return f"https://{account}.catsone.com/careers/{portal}"

    def job_urls(self, fetcher: Fetcher, board_token: str) -> list[str]:
        account, portal = _parts(board_token)
        html = listing(fetcher, self.board_url(board_token)).decode("utf-8", "replace")
        found = re.findall(rf'href="(/careers/{portal}/jobs/\d+[^"]*)"', html)
        return [f"https://{account}.catsone.com{path}" for path in dict.fromkeys(found)]

    def item_id(self, url: str, page: dict[str, Any]) -> str:
        match = re.search(r"/jobs/(\d+)", url)
        return match[1] if match else super().item_id(url, page)

    def read_page(self, url: str, body: bytes) -> dict[str, Any] | None:
        html = body.decode("utf-8", "replace")
        title = TITLE.search(html)
        if not title or not text_of(title.group(1)):
            return None
        tags = TAGS.search(html)
        logo = LOGO.search(html)
        return {
            "title": text_of(title.group(1)),
            "tags": [text_of(t) for t in re.findall(r"<li[^>]*>(.*?)</li>", tags[1], re.DOTALL)]
            if tags
            else [],
            "company": text_of(logo.group(1)) if logo else None,
            "description": element_with(html, r'class="job-description"'),
        }

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        tags: list[str] = [t for t in job["tags"] if t]
        # The first tag is the place; a later one that shows money is the pay, which the
        # normalizer reads from the page text, not from here.
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["title"]),
            company_name=job.get("company") or None,
            apply_url=as_url(str(job["url"])),
            location_text=tags[0] if tags and "$" not in tags[0] else None,
            description_html=job.get("description"),
        )
