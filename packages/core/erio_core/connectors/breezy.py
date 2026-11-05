"""Breezy HR openings API: GET https://{company}.breezy.hr/json
returns a JSON list of active postings with locations, departments, and descriptions.
"""

import json
import re
from typing import Any

from pydantic import HttpUrl

from erio_core.connectors._util import iso_datetime
from erio_core.connectors.base import Connector
from erio_core.schemas import PartialJob, RawPosting, RemoteStatus

TOKEN = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")


class BreezyConnector(Connector):
    slug = "breezy"
    hosts = frozenset({"*.breezy.hr"})

    def board_url(self, board_token: str) -> str:
        if not TOKEN.fullmatch(board_token):
            raise ValueError(f"not a Breezy HR company name: {board_token!r}")
        return f"https://{board_token}.breezy.hr/json"

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        data = json.loads(body)
        if not isinstance(data, list):
            raise ValueError(f"not a Breezy HR openings list: {type(data).__name__}")
        return [
            RawPosting(
                source_slug=self.slug,
                board_token=board_token,
                external_id=str(item["_id"] if "_id" in item else item["id"]),
                payload=item,
            )
            for item in data
            if isinstance(item, dict) and (item.get("_id") or item.get("id")) and item.get("name")
        ]

    def parse(self, raw: RawPosting) -> PartialJob:
        item = raw.payload
        location = item.get("location") or {}
        city = location.get("name") or location.get("city")
        state = location.get("state")
        country = location.get("country")
        country_name = country.get("name") if isinstance(country, dict) else (country or None)
        country_code = country.get("code") if isinstance(country, dict) else None

        parts = [city, state, country_name]
        loc_text = ", ".join(p for p in parts if p) or None

        is_remote = bool(location.get("is_remote"))
        workplace: RemoteStatus | None = "remote" if is_remote else None

        emp_type = item.get("type")
        emp_name = emp_type.get("name") if isinstance(emp_type, dict) else (str(emp_type) if emp_type else None)

        apply_url = item.get("url") or f"https://{raw.board_token}.breezy.hr/p/{raw.external_id}"
        company = item.get("company")
        company_name = company.get("name") if isinstance(company, dict) else (company or None)

        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(item["name"]).strip(),
            company_name=company_name,
            apply_url=HttpUrl(apply_url),
            posted_at=iso_datetime(item.get("creation_date") or item.get("updated_date")),
            location_text=loc_text,
            city=city or None,
            region=state or None,
            country_hint=country_code or country_name or None,
            workplace_type=workplace,
            employment_type=emp_name or None,
            departments=[str(item["department"])] if item.get("department") else [],
            description_html=item.get("description"),
        )

