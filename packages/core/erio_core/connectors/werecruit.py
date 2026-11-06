"""WeRecruit career sites on careers.werecruit.io.

A company's page, ``https://careers.werecruit.io/{lang}/{company}``, embeds
every open offer as JSON (``window.allOffers``): title, place, contract, dates
and the offer's address. The offer page adds the description and salary and is
fetched for up to ``max_details`` offers a crawl. The board token is the
company slug, optionally with a language prefix: ``happy-job`` or ``fr/happy-job``.
Open applications ("candidature spontanée") are not jobs and are left out.
"""

import json
import re
from typing import Any

from erio_core.connectors._htmlpages import element_with, read_date, text_of
from erio_core.connectors._util import as_url
from erio_core.connectors.base import BoardFetch, Connector, Fetcher, FetchError
from erio_core.schemas import PartialJob, RawPosting

TOKEN = re.compile(r"(?:([a-z]{2})/)?([a-z0-9][a-z0-9-]{0,80})")
OFFERS = "window.allOffers = "
SALARY = re.compile(r"Salaire\s*</span>(.*?)</p>", re.DOTALL)
CONTRACTS = (
    ("CDD", "Fixed-term (CDD)"),
    ("Alternance", "Apprenticeship"),
    ("Apprentissage", "Apprenticeship"),
    ("Intérim", "Temporary"),
)
TIMES = {"Temps partiel": "Part-time", "Temps plein": "Full-time"}
MAX_DETAILS = 150


def employment(offer: dict[str, Any]) -> str | None:
    contract = str(offer.get("TypeTranslated") or "")
    named = next((english for french, english in CONTRACTS if french in contract), contract)
    time = TIMES.get(str(offer.get("TimeTranslated") or ""))
    return ", ".join(p for p in (named, time) if p) or None


class WeRecruitConnector(Connector):
    slug = "werecruit"
    hosts = frozenset({"careers.werecruit.io"})
    max_details = MAX_DETAILS

    def board_url(self, board_token: str) -> str:
        found = TOKEN.fullmatch(board_token)
        if not found:
            raise ValueError(f"not a WeRecruit company slug: {board_token!r}")
        return f"https://careers.werecruit.io/{found.group(1) or 'fr'}/{found.group(2)}"

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        html = body.decode("utf-8", "replace")
        start = html.find(OFFERS)
        if start < 0:
            raise ValueError("the page lists no offers")
        offers, _ = json.JSONDecoder().raw_decode(html[start + len(OFFERS) :])
        return [
            RawPosting(
                source_slug=self.slug,
                board_token=board_token,
                external_id=str(offer["Id"]),
                payload={"offer": offer},
            )
            for offer in offers
            if offer.get("Url") and "candidature-spontanee" not in offer["Url"]
        ]

    def list_postings(
        self, fetcher: Fetcher, board_token: str, etag: str | None = None
    ) -> BoardFetch:
        listed = super().list_postings(fetcher, board_token, etag)
        if listed.unchanged:
            return listed
        postings = []
        for index, raw in enumerate(listed.postings):
            payload = dict(raw.payload)
            if index < self.max_details:
                try:
                    response = fetcher.get(payload["offer"]["Url"])
                except FetchError:
                    response = None
                if response is not None and response.status == 200:
                    html = response.body.decode("utf-8", "replace")
                    payload["description"] = element_with(html, r'class="description rich-text')
                    found = SALARY.search(html)
                    payload["salary"] = text_of(found.group(1)) if found else None
            postings.append(raw.model_copy(update={"payload": payload}))
        return BoardFetch(postings, 200, listed.body, etag=listed.etag)

    def parse(self, raw: RawPosting) -> PartialJob:
        offer: dict[str, Any] = raw.payload["offer"]
        city, region = offer.get("Address_City"), offer.get("Address_Region")
        title = str(offer.get("TitleTranslated") or next(iter(offer["Title"].values()))).strip()
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=title,
            company_name=offer.get("Company_Name"),
            apply_url=as_url(str(offer["Url"])),
            posted_at=read_date(offer.get("PublicationStartDate")),
            location_text=", ".join(p for p in (city, region) if p) or None,
            city=city,
            region=region,
            country_hint=offer.get("Address_State"),
            employment_type=employment(offer),
            description_html=raw.payload.get("description"),
        )
