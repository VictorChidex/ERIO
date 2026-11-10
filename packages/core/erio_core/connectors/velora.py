"""Velora HR career sites ({company}.career.velorahr.com/{slug}-{id}).

The career site is a Next.js app that reads ``api.velorahr.com/api/public/career-site/{id}/offers``
anonymously: one JSON list with every open offer and its description and requirements. The
board token is "{company}/{id}" from the career-site address, for example "axactor/109" for
``axactor.career.velorahr.com/axactor-109``. Pages are read with ``range=[from,to]``.
"""

import json
import re
from typing import Any
from urllib.parse import quote

from erio_core.connectors._util import as_url, iso_datetime, join_html
from erio_core.connectors.base import BoardFetch, Connector, Fetcher, FetchError
from erio_core.schemas import PartialJob, RawPosting, RemoteStatus

TOKEN = re.compile(r"([a-z0-9][a-z0-9-]{0,62})/(\d{1,6})")
API = "https://api.velorahr.com/api/public/career-site"
PAGE = 50
WORKPLACE: dict[str, RemoteStatus] = {
    "presencial": "onsite", "remoto": "remote", "teletrabajo": "remote", "hibrido": "hybrid",
    "híbrido": "hybrid", "onsite": "onsite", "remote": "remote", "hybrid": "hybrid",
}  # fmt: skip


def _parts(board_token: str) -> tuple[str, str]:
    match = TOKEN.fullmatch(board_token)
    if not match:
        raise ValueError(f"not a Velora token (company/id): {board_token!r}")
    return match[1], match[2]


class VeloraConnector(Connector):
    slug = "velora"
    hosts = frozenset({"api.velorahr.com", "*.career.velorahr.com"})
    max_pages = 10

    def board_url(self, board_token: str) -> str:
        return self._page_url(board_token, 0)

    def _page_url(self, board_token: str, page: int) -> str:
        _, site = _parts(board_token)
        rng = quote(f"[{page * PAGE},{page * PAGE + PAGE - 1}]")
        sort = quote('["created_at","DESC"]')
        return f"{API}/{site}/offers?filter={quote('{}')}&range={rng}&sort={sort}"

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        offers = json.loads(body)["data"]
        if not isinstance(offers, list):
            raise ValueError("'data' is not a list")
        return [
            RawPosting(
                source_slug=self.slug,
                board_token=board_token,
                external_id=str(offer["id"]),
                payload=offer,
            )
            for offer in offers
            if offer.get("title") or offer.get("clean_title")
        ]

    def list_postings(
        self, fetcher: Fetcher, board_token: str, etag: str | None = None
    ) -> BoardFetch:
        postings: dict[str, RawPosting] = {}
        first = b""
        complete = True
        for page in range(self.max_pages):
            response = fetcher.get(self._page_url(board_token, page))
            if response.status == 429:
                raise FetchError("rate_limited", "source rate limit", 429)
            if response.status != 200:
                raise FetchError("http_error", f"HTTP {response.status}", response.status)
            try:
                found = self.extract(response.body, board_token)
            except (ValueError, KeyError, TypeError) as error:
                raise FetchError("parse_error", f"malformed payload: {error}", 200) from error
            first = first or response.body
            fresh = [p for p in found if p.external_id not in postings]
            postings.update((p.external_id, p) for p in fresh)
            if not fresh or len(found) < PAGE:
                break
        else:
            complete = False
        return BoardFetch(
            postings=list(postings.values()), http_status=200, body=first, complete=complete
        )

    def parse(self, raw: RawPosting) -> PartialJob:
        offer: dict[str, Any] = raw.payload
        company, site = _parts(raw.board_token)
        places = [offer.get("city"), offer.get("province"), offer.get("country")]
        title = offer.get("clean_title") or offer["title"]
        # Salary is shown only when the employer allows it, and comes without a period:
        # the normalizer reads it from the description instead.
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(title).strip(),
            company_name=company.replace("-", " ").title(),
            apply_url=as_url(
                offer.get("offer_url")
                or f"https://{company}.career.velorahr.com/{company}-{site}/offers/{raw.external_id}"
            ),
            posted_at=iso_datetime(offer.get("created_at")),
            location_text=", ".join(dict.fromkeys(str(p) for p in places if p)) or None,
            city=offer.get("city") or None,
            region=offer.get("province") or offer.get("state") or None,
            country_hint=offer.get("country") or None,
            workplace_type=WORKPLACE.get(str(offer.get("work_mode") or "").lower()),
            employment_type=offer.get("contract_type") or offer.get("work_schedule") or None,
            description_html=join_html(
                offer.get("description_html"), offer.get("requirements_html")
            ),
        )
