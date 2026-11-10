"""Recruitify career portals (``{company}.recruitify.ai`` or a customer's own domain).

A portal is an Angular app that reads ``api.recruitify.ai`` and tells the API which
company it is for by the address of the page it runs on (the ``Origin`` header, which
the browser sends). ``/apply/config`` names the company, ``/apply/project`` lists the
published jobs and ``/apply/project/{guid}`` returns one job with its description. No
login is involved. The board token is the career portal's host name, for example
``jobs.recruitify.ai``; each job's page is ``https://{host}/job/{guid}``.
"""

import json
import re
from typing import Any

from erio_core.connectors._util import as_url, iso_datetime
from erio_core.connectors.base import (
    BoardFetch,
    Connector,
    Fetcher,
    FetchError,
    header_getter,
)
from erio_core.schemas import PartialJob, RawPosting

HOST = re.compile(r"[a-z0-9][a-z0-9.-]{2,120}\.[a-z]{2,}")
API = "https://api.recruitify.ai/apply"


def _check(board_token: str) -> str:
    if not HOST.fullmatch(board_token):
        raise ValueError(f"not a Recruitify portal host name: {board_token!r}")
    return board_token


def _names(items: Any) -> list[str]:
    out = []
    for item in items or []:
        name = item if isinstance(item, str) else (item or {}).get("name")
        if name:
            out.append(str(name))
    return out


class RecruitifyConnector(Connector):
    slug = "recruitify"
    hosts = frozenset({"api.recruitify.ai"})
    max_details = 60

    def board_url(self, board_token: str) -> str:
        _check(board_token)
        return f"{API}/project"

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        projects = json.loads(body)
        if not isinstance(projects, list):
            raise ValueError("the project list is not a list")
        return [
            RawPosting(
                source_slug=self.slug,
                board_token=board_token,
                external_id=str(project["guid"]),
                payload={"listed": project},
            )
            for project in projects
            if project.get("name") and project.get("allowApply", True)
        ]

    def list_postings(
        self, fetcher: Fetcher, board_token: str, etag: str | None = None
    ) -> BoardFetch:
        getter = header_getter(fetcher)
        portal = _check(board_token)
        headers = {"Origin": f"https://{portal}", "Referer": f"https://{portal}/"}

        def get(path: str) -> bytes | None:
            response = getter.get_with(f"{API}/{path}", headers)
            if response.status == 429:
                raise FetchError("rate_limited", "source rate limit", 429)
            if response.status == 404:
                return None
            if response.status != 200:
                raise FetchError("http_error", f"HTTP {response.status}", response.status)
            return response.body

        listing = get("project")
        if listing is None:
            raise FetchError("http_error", "no such portal", 404)
        try:
            listed = self.extract(listing, board_token)
            company = json.loads(get("config") or b"{}").get("companyName")
        except (ValueError, KeyError, TypeError) as error:
            raise FetchError("parse_error", f"malformed payload: {error}", 200) from error
        postings: list[RawPosting] = []
        unread = 0
        for raw in listed[: self.max_details]:
            try:
                body = get(f"project/{raw.external_id}")
                detail = json.loads(body) if body else None
            except (FetchError, ValueError):
                detail = None
            if not isinstance(detail, dict):
                unread += 1
                continue
            payload = {**raw.payload, "detail": detail, "company": company}
            postings.append(raw.model_copy(update={"payload": payload}))
        if listed and not postings:
            raise FetchError("parse_error", "no job detail could be read", 200)
        return BoardFetch(
            postings=postings,
            http_status=200,
            body=listing,
            complete=len(listed) <= self.max_details and unread == 0,
        )

    def parse(self, raw: RawPosting) -> PartialJob:
        listed: dict[str, Any] = raw.payload["listed"]
        detail: dict[str, Any] = raw.payload.get("detail") or {}
        places = _names(detail.get("location") or listed.get("location"))
        countries = _names(detail.get("country") or listed.get("country"))
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(detail.get("name") or listed["name"]).strip(),
            company_name=raw.payload.get("company") or None,
            apply_url=as_url(f"https://{raw.board_token}/job/{raw.external_id}"),
            posted_at=iso_datetime(detail.get("published") or listed.get("published")),
            location_text=", ".join(dict.fromkeys([*places, *countries])) or None,
            country_hint=countries[0] if countries else None,
            description_html=detail.get("description") or listed.get("description") or None,
        )
