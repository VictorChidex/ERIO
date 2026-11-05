"""Teamtailor career sites: GET https://{company}.teamtailor.com/jobs.json is a
JSON Feed whose items carry the full description and a schema.org JobPosting
(``_jobposting``), read with the same code as JobPosting pages. Career sites
on an employer's own domain serve the same feed: register the full URL."""

import re
from typing import Any

from erio_core.connectors._paged import PagedJsonConnector
from erio_core.connectors.jsonld import parse_job_posting
from erio_core.schemas import PartialJob, RawPosting

TOKEN = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")


class TeamtailorConnector(PagedJsonConnector):
    slug = "teamtailor"
    hosts = frozenset({"*.teamtailor.com"})

    def list_url(self, board_token: str, page: int) -> str:
        if board_token.startswith("https://"):
            return board_token.rstrip("/") + "/jobs.json"
        if not TOKEN.fullmatch(board_token):
            raise ValueError(f"not a Teamtailor subdomain: {board_token!r}")
        return f"https://{board_token}.teamtailor.com/jobs.json"

    def items(self, data: Any) -> list[dict[str, Any]]:
        return list(data["items"])

    def parse(self, raw: RawPosting) -> PartialJob:
        item = raw.payload
        posting = dict(item.get("_jobposting") or {})
        posting.setdefault("title", item["title"])
        posting.setdefault("datePosted", item.get("date_published"))
        posting["description"] = item.get("content_html") or posting.get("description")
        posting["url"] = item["url"]
        return parse_job_posting(self.slug, raw.external_id, item["url"], posting)
