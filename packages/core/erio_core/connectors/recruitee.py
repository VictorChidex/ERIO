"""Recruitee careers-site API.

GET https://{company}.recruitee.com/api/offers/ returns {"offers": [...]}
with every published offer, no authentication needed. An unknown company
answers 404. Each company has its own subdomain, so the host allow-list
holds a wildcard.
"""

import json
import re

from erio_core.connectors._util import iso_datetime, join_html, salary
from erio_core.connectors.base import Connector
from erio_core.schemas import PartialJob, RawPosting, RemoteStatus

# Recruitee subdomains are lowercase letters, digits and hyphens.
TOKEN = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")


class RecruiteeConnector(Connector):
    slug = "recruitee"
    hosts = frozenset({"*.recruitee.com"})

    def board_url(self, board_token: str) -> str:
        if not TOKEN.fullmatch(board_token):
            raise ValueError(f"not a Recruitee subdomain: {board_token!r}")
        return f"https://{board_token}.recruitee.com/api/offers/"

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        offers = json.loads(body)["offers"]
        if not isinstance(offers, list):
            raise ValueError("'offers' is not a list")
        return [
            RawPosting(
                source_slug=self.slug,
                board_token=board_token,
                external_id=str(offer["id"]),
                payload=offer,
            )
            for offer in offers
            if offer.get("status", "published") == "published"
        ]

    def parse(self, raw: RawPosting) -> PartialJob:
        offer = raw.payload
        workplace: RemoteStatus | None = (
            "remote" if offer.get("remote") else
            "hybrid" if offer.get("hybrid") else
            "onsite" if offer.get("on_site") else None
        )  # fmt: skip
        pay = offer.get("salary") or {}
        places = [place.get("name") for place in offer.get("locations") or []]
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(offer["title"]).strip(),
            company_name=offer.get("company_name"),
            apply_url=offer["careers_url"],
            posted_at=iso_datetime(offer.get("published_at") or offer.get("created_at")),
            location_text=offer.get("location") or "; ".join(p for p in places if p) or None,
            city=offer.get("city") or None,
            region=offer.get("state_name") or None,
            country_hint=offer.get("country_code") or offer.get("country") or None,
            workplace_type=workplace,
            employment_type=offer.get("employment_type_code"),
            departments=[offer["department"]] if offer.get("department") else [],
            salary=salary(pay.get("min"), pay.get("max"), pay.get("currency"), pay.get("period")),
            description_html=join_html(offer.get("description"), offer.get("requirements")),
        )
