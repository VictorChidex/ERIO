"""Personio job pages: GET https://{company}.jobs.personio.de/xml?language=en
is an XML feed (<workzag-jobs><position>...) of every published position,
with its description sections. Each job's page is .../job/{id}."""

import re
from typing import Any
from xml.etree.ElementTree import Element

from defusedxml import ElementTree
from pydantic import HttpUrl

from erio_core.connectors._util import iso_datetime
from erio_core.connectors.base import Connector
from erio_core.schemas import PartialJob, RawPosting

TOKEN = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")


def _position(element: Element) -> dict[str, Any]:
    sections = [
        {"name": d.findtext("name") or "", "value": (d.findtext("value") or "").strip()}
        for d in element.findall("./jobDescriptions/jobDescription")
    ]
    offices = [element.findtext("office") or ""] + [
        o.text or "" for o in element.findall("./additionalOffices/office")
    ]
    fields = {child.tag: (child.text or "").strip() for child in element if not len(child)}
    return fields | {"offices": [o for o in offices if o], "sections": sections}


class PersonioConnector(Connector):
    slug = "personio"
    hosts = frozenset({"*.jobs.personio.de", "*.jobs.personio.com"})

    def board_url(self, board_token: str) -> str:
        if not TOKEN.fullmatch(board_token):
            raise ValueError(f"not a Personio company name: {board_token!r}")
        return f"https://{board_token}.jobs.personio.de/xml?language=en"

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        root = ElementTree.fromstring(body)
        if root.tag != "workzag-jobs":
            raise ValueError(f"not a Personio feed: <{root.tag}>")
        return [
            RawPosting(
                source_slug=self.slug,
                board_token=board_token,
                external_id=str(position["id"]),
                payload=position,
            )
            for position in map(_position, root.findall("position"))
            if position.get("id") and position.get("name")
        ]

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        offices = job.get("offices") or []
        description = "".join(
            f"<h3>{s['name']}</h3>{s['value']}" if s["name"] else s["value"]
            for s in job.get("sections") or []
        )
        remote = any("remote" in office.lower() for office in offices)
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["name"]).strip(),
            company_name=job.get("subcompany") or None,
            apply_url=HttpUrl(f"https://{raw.board_token}.jobs.personio.de/job/{raw.external_id}"),
            posted_at=iso_datetime(job.get("createdAt")),
            location_text="; ".join(offices) or None,
            workplace_type="remote" if remote and len(offices) == 1 else None,
            employment_type=", ".join(
                p for p in (job.get("schedule"), job.get("employmentType")) if p
            ) or None,
            departments=[d] if (d := job.get("department")) else [],
            description_html=description or None,
        )  # fmt: skip
