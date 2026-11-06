"""Comeet career pages: GET https://www.comeet.com/jobs/{company}/{uid} embeds every
open position, with its description, as a JSON array (``COMPANY_POSITIONS_DATA``).

The board token is "{company}/{uid}" from the address of the careers page, for
example "vastdata/43.001". The token-based Careers API is not used.
"""

import json
import re
from typing import Any

from erio_core.connectors._util import as_url
from erio_core.connectors.base import Connector
from erio_core.schemas import PartialJob, RawPosting, RemoteStatus

TOKEN = re.compile(r"([a-z0-9][a-z0-9_-]{0,80})/([0-9A-Za-z]{2,3}\.[0-9A-Za-z]{3})")
MARKER = "COMPANY_POSITIONS_DATA = "
WORKPLACE: dict[str, RemoteStatus] = {"remote": "remote", "hybrid": "hybrid", "on-site": "onsite"}


def _parts(board_token: str) -> tuple[str, str]:
    match = TOKEN.fullmatch(board_token)
    if not match:
        raise ValueError(f"not a Comeet token (company/uid): {board_token!r}")
    return match[1], match[2]


class ComeetConnector(Connector):
    slug = "comeet"
    hosts = frozenset({"www.comeet.com"})

    def board_url(self, board_token: str) -> str:
        company, uid = _parts(board_token)
        return f"https://www.comeet.com/jobs/{company}/{uid}"

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        text = body.decode("utf-8", "replace")
        start = text.find(MARKER)
        if start < 0:
            raise ValueError("the page carries no positions data")
        data, _ = json.JSONDecoder().raw_decode(text, start + len(MARKER))
        return [
            RawPosting(
                source_slug=self.slug,
                board_token=board_token,
                external_id=str(job["uid"]),
                payload=job,
            )
            for job in data
            if not job.get("is_internal")
        ]

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        company, uid = _parts(raw.board_token)
        place = job.get("location") or {}
        remote = job.get("workplace_type") or ("Remote" if place.get("is_remote") else None)
        details: list[dict[str, Any]] = (job.get("custom_fields") or {}).get("details") or []
        description = "".join(
            f"<h3>{d['name']}</h3>{d['value']}" if d.get("name") != "Description" else d["value"]
            for d in details
            if d.get("value")
        )
        department = job.get("department")
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["name"]).strip(),
            company_name=job.get("company_name"),
            apply_url=as_url(
                job.get("url_comeet_hosted_page") or f"https://www.comeet.com/jobs/{company}/{uid}"
            ),
            location_text=place.get("name") or None,
            city=place.get("city") or None,
            region=place.get("state") or None,
            country_hint=place.get("country") or None,
            workplace_type=WORKPLACE.get(str(remote or "").lower()),
            employment_type=job.get("employment_type"),
            departments=[department] if department else [],
            description_html=description or None,
        )
