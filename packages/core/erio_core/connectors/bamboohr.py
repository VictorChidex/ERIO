"""BambooHR careers list API: GET https://{company}.bamboohr.com/careers/list
returns {"result": [...]} with active job openings, locations, and departments.
"""

import json
import re
from typing import Any

from pydantic import HttpUrl

from erio_core.connectors._util import iso_datetime
from erio_core.connectors.base import Connector
from erio_core.schemas import PartialJob, RawPosting, RemoteStatus

TOKEN = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")


class BambooHRConnector(Connector):
    slug = "bamboohr"
    hosts = frozenset({"*.bamboohr.com"})

    def board_url(self, board_token: str) -> str:
        if not TOKEN.fullmatch(board_token):
            raise ValueError(f"not a BambooHR company name: {board_token!r}")
        return f"https://{board_token}.bamboohr.com/careers/list"

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        data = json.loads(body)
        items = data.get("result") if isinstance(data, dict) else data
        if not isinstance(items, list):
            raise ValueError(f"not a BambooHR openings result: {type(data).__name__}")
        return [
            RawPosting(
                source_slug=self.slug,
                board_token=board_token,
                external_id=str(item["id"]),
                payload=item,
            )
            for item in items
            if isinstance(item, dict) and item.get("id") and (item.get("jobOpeningName") or item.get("title"))
        ]

    def parse(self, raw: RawPosting) -> PartialJob:
        item = raw.payload
        location = item.get("location") or {}
        city = location.get("city")
        state = location.get("state")
        country = location.get("country")

        parts = [city, state, country]
        loc_text = ", ".join(p for p in parts if p) or None

        is_remote = bool(item.get("isRemote") or location.get("isRemote"))
        workplace: RemoteStatus | None = "remote" if is_remote else None

        dept = item.get("department")
        dept_name = dept.get("label") if isinstance(dept, dict) else (str(dept) if dept else None)

        title = str(item.get("jobOpeningName") or item.get("title")).strip()
        apply_url = f"https://{raw.board_token}.bamboohr.com/careers/{raw.external_id}"

        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=title,
            apply_url=HttpUrl(apply_url),
            posted_at=iso_datetime(item.get("datePosted") or item.get("createdAt")),
            location_text=loc_text,
            city=city or None,
            region=state or None,
            country_hint=country or None,
            workplace_type=workplace,
            employment_type=item.get("employmentType") or None,
            departments=[dept_name] if dept_name else [],
            description_html=item.get("description"),
        )

