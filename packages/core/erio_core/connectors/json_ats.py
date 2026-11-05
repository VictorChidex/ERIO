"""Connectors for JSON-based Applicant Tracking Systems:
Comeet, Freshteam, GoHire, HireHive, HiringThing, HiBob, Gem, Dover, Deel, Join, Workday.
"""

import json
import re
from typing import Any
from urllib.parse import urlsplit

from pydantic import HttpUrl

from erio_core.connectors._paged import PagedJsonConnector
from erio_core.connectors._util import iso_datetime
from erio_core.connectors.base import Connector, Fetcher, BoardFetch
from erio_core.schemas import PartialJob, RawPosting, RemoteStatus

TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,62}")


class ComeetConnector(Connector):
    slug = "comeet"
    hosts = frozenset({"www.comeet.co", "api.comeet.me"})

    def board_url(self, board_token: str) -> str:
        return f"https://www.comeet.co/careers-api/2.0/company/{board_token}/positions"

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        data = json.loads(body)
        items = data if isinstance(data, list) else data.get("positions", [])
        return [
            RawPosting(
                source_slug=self.slug,
                board_token=board_token,
                external_id=str(item["uid"]),
                payload=item,
            )
            for item in items
            if isinstance(item, dict) and item.get("uid") and item.get("name")
        ]

    def parse(self, raw: RawPosting) -> PartialJob:
        item = raw.payload
        location = item.get("location") or {}
        city = location.get("city") or location.get("name")
        country = location.get("country")
        is_remote = bool(location.get("is_remote") or item.get("is_remote"))

        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(item["name"]).strip(),
            company_name=item.get("company_name"),
            apply_url=HttpUrl(item.get("url_active_page") or item.get("url_comeet_hosted_page") or f"https://www.comeet.co/jobs/{raw.board_token}/{raw.external_id}"),
            posted_at=iso_datetime(item.get("time_updated") or item.get("time_created")),
            location_text=location.get("name") or (f"{city}, {country}" if city and country else city or country),
            city=city or None,
            country_hint=country or None,
            workplace_type="remote" if is_remote else None,
            employment_type=item.get("employment_type"),
            departments=[item["department"]] if item.get("department") else [],
            description_html=item.get("description"),
        )


class FreshteamConnector(Connector):
    slug = "freshteam"
    hosts = frozenset({"*.freshteam.com"})

    def board_url(self, board_token: str) -> str:
        return f"https://{board_token}.freshteam.com/jobs.json"

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        data = json.loads(body)
        items = data if isinstance(data, list) else data.get("jobs", [])
        return [
            RawPosting(
                source_slug=self.slug,
                board_token=board_token,
                external_id=str(item["id"]),
                payload=item,
            )
            for item in items
            if isinstance(item, dict) and item.get("id") and item.get("title")
        ]

    def parse(self, raw: RawPosting) -> PartialJob:
        item = raw.payload
        branch = item.get("branch") or {}
        city = branch.get("city")
        country = branch.get("country")
        remote = bool(item.get("remote"))

        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(item["title"]).strip(),
            apply_url=HttpUrl(item.get("url") or f"https://{raw.board_token}.freshteam.com/jobs/{raw.external_id}"),
            posted_at=iso_datetime(item.get("created_at")),
            location_text=branch.get("name") or (f"{city}, {country}" if city and country else city or country),
            city=city or None,
            country_hint=country or None,
            workplace_type="remote" if remote else None,
            employment_type=item.get("type"),
            departments=[item["department"]] if item.get("department") else [],
            description_html=item.get("description"),
        )


class JoinConnector(Connector):
    slug = "join"
    hosts = frozenset({"api.join.com", "*.join.com"})

    def board_url(self, board_token: str) -> str:
        return f"https://api.join.com/v1/companies/{board_token}/jobs"

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        data = json.loads(body)
        items = data if isinstance(data, list) else data.get("jobs", [])
        return [
            RawPosting(
                source_slug=self.slug,
                board_token=board_token,
                external_id=str(item["id"]),
                payload=item,
            )
            for item in items
            if isinstance(item, dict) and item.get("id") and item.get("title")
        ]

    def parse(self, raw: RawPosting) -> PartialJob:
        item = raw.payload
        location = item.get("location") or {}
        city = location.get("city")
        country = location.get("country")
        remote = item.get("isRemote") or location.get("isRemote")

        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(item["title"]).strip(),
            apply_url=HttpUrl(item.get("url") or f"https://join.com/companies/{raw.board_token}/jobs/{raw.external_id}"),
            posted_at=iso_datetime(item.get("publishedAt") or item.get("createdAt")),
            location_text=f"{city}, {country}" if city and country else (city or country),
            city=city or None,
            country_hint=country or None,
            workplace_type="remote" if remote else None,
            employment_type=item.get("employmentType"),
            departments=[item["department"]] if item.get("department") else [],
            description_html=item.get("description"),
        )


class WorkdayConnector(PagedJsonConnector):
    slug = "workday"
    hosts = frozenset({"*.myworkdayjobs.com"})
    limit = 20

    def list_url(self, board_token: str, page: int) -> str:
        # board_token: "tenant/site" e.g. "nvidia/NVIDIAExternalCareerSite"
        parts = board_token.strip("/").split("/", 1)
        tenant = parts[0]
        site = parts[1] if len(parts) > 1 else "External"
        offset = (page - 1) * self.limit
        return f"https://{tenant}.wd1.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs?offset={offset}&limit={self.limit}"

    def items(self, data: Any) -> list[dict[str, Any]]:
        return list(data.get("jobPostings", []))

    def has_more(self, data: Any, items: list[dict[str, Any]], page: int) -> bool:
        total = int(data.get("total", 0))
        return total > page * self.limit

    def parse(self, raw: RawPosting) -> PartialJob:
        item = raw.payload
        title = item.get("title", "")
        external_path = item.get("externalPath", "")
        parts = raw.board_token.strip("/").split("/", 1)
        tenant = parts[0]
        site = parts[1] if len(parts) > 1 else "External"
        apply_url = f"https://{tenant}.wd1.myworkdayjobs.com/{site}{external_path}" if external_path else f"https://{tenant}.wd1.myworkdayjobs.com"

        locations = item.get("locationsText", "")
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(title).strip(),
            apply_url=HttpUrl(apply_url),
            posted_at=iso_datetime(item.get("postedOn")),
            location_text=locations or None,
            workplace_type="remote" if "remote" in locations.lower() else None,
            employment_type=item.get("timeType"),
        )


class GenericJsonAtsConnector(Connector):
    """Generic JSON endpoint connector for simple ATS platforms."""

    def __init__(self, slug: str, hosts: frozenset[str], url_template: str, title_key: str = "title"):
        self.slug = slug
        self.hosts = hosts
        self.url_template = url_template
        self.title_key = title_key

    def board_url(self, board_token: str) -> str:
        if board_token.startswith("https://"):
            return board_token
        return self.url_template.format(token=board_token)

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        data = json.loads(body)
        items = data if isinstance(data, list) else data.get("jobs", data.get("data", []))
        return [
            RawPosting(
                source_slug=self.slug,
                board_token=board_token,
                external_id=str(item.get("id") or item.get("slug") or item.get("_id") or i),
                payload=item,
            )
            for i, item in enumerate(items)
            if isinstance(item, dict) and (item.get(self.title_key) or item.get("title") or item.get("name"))
        ]

    def parse(self, raw: RawPosting) -> PartialJob:
        item = raw.payload
        title = str(item.get(self.title_key) or item.get("title") or item.get("name")).strip()
        url = item.get("url") or item.get("apply_url") or item.get("hosted_url") or self.board_url(raw.board_token)
        loc = item.get("location")
        loc_text = loc if isinstance(loc, str) else (loc.get("name") if isinstance(loc, dict) else None)
        remote = bool(item.get("remote") or item.get("is_remote") or (loc_text and "remote" in loc_text.lower()))

        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=title,
            company_name=item.get("company_name") or item.get("company"),
            apply_url=HttpUrl(url),
            posted_at=iso_datetime(item.get("published_at") or item.get("created_at")),
            location_text=loc_text,
            workplace_type="remote" if remote else None,
            employment_type=item.get("employment_type") or item.get("type"),
            description_html=item.get("description"),
        )

