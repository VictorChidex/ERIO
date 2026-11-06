"""Jobvite career sites on jobs.jobvite.com.

``https://jobs.jobvite.com/{company}/jobs`` lists every open job on one page
and each job page carries its title, categories, locations and description
as HTML (no structured data, no public JSON). The board token is the company
slug.
"""

import re
from typing import Any

from erio_core.connectors._htmlpages import PageCrawler, element_with, listing, text_of
from erio_core.connectors._util import as_url
from erio_core.connectors.base import Fetcher
from erio_core.schemas import PartialJob, RawPosting

SLUG = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,80}")
HEADER = re.compile(r'<h2 class="jv-header"[^>]*>(.*?)</h2>', re.DOTALL)
META = re.compile(r'<p class="jv-job-detail-meta"[^>]*>(.*?)</p>', re.DOTALL)
SEPARATOR = re.compile(r"<span[^>]*jv-inline-separator[^>]*></span>")
REQUISITION = re.compile(r"Req\.?\s*Num\.?:?\s*(\S+)")


class JobviteConnector(PageCrawler):
    slug = "jobvite"
    hosts = frozenset({"jobs.jobvite.com"})

    def board_url(self, board_token: str) -> str:
        if not SLUG.fullmatch(board_token):
            raise ValueError(f"not a Jobvite company slug: {board_token!r}")
        return f"https://jobs.jobvite.com/{board_token}/jobs"

    def job_urls(self, fetcher: Fetcher, board_token: str) -> list[str]:
        html = listing(fetcher, self.board_url(board_token)).decode("utf-8", "replace")
        found = re.findall(rf'href="(/{re.escape(board_token)}/job/[A-Za-z0-9]+)"', html)
        return [f"https://jobs.jobvite.com{path}" for path in dict.fromkeys(found)]

    def item_id(self, url: str, page: dict[str, Any]) -> str:
        return url.rstrip("/").rsplit("/", 1)[-1]

    def read_page(self, url: str, body: bytes) -> dict[str, Any] | None:
        html = body.decode("utf-8", "replace")
        header = HEADER.search(html)
        if not header or not text_of(header.group(1)):
            return None
        meta_block = META.search(html)
        parts = (
            [text_of(part) for part in SEPARATOR.split(meta_block.group(1))] if meta_block else []
        )
        requisition = REQUISITION.search(parts[-1]) if parts else None
        if requisition:
            parts[-1] = REQUISITION.sub("", parts[-1]).strip()
        return {
            "title": text_of(header.group(1)),
            "parts": [p for p in parts if p],
            "requisition": requisition.group(1) if requisition else None,
            "description": element_with(html, r'class="jv-job-detail-description"'),
        }

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        parts: list[str] = job["parts"]
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["title"]),
            apply_url=as_url(str(job["url"])),
            location_text="; ".join(parts[1:]) or None,
            departments=parts[:1],
            description_html=job.get("description"),
        )
