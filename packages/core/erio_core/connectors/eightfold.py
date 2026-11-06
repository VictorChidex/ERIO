"""Eightfold AI career sites (PCS): the public JSON their career pages call.

- list:   GET https://{tenant}.eightfold.ai/api/pcsx/search?domain={domain}&start=n&num=10
          ten jobs a page; data.count is the total
- detail: GET https://{tenant}.eightfold.ai/api/pcsx/position_details?position_id={id}&domain={domain}
          adds the HTML description

The board token is "{tenant}/{domain}", for example "paypal/paypal.com". The list has
no descriptions: a crawl reads at most ``max_pages`` list pages and ``max_details``
detail pages, and a larger board is an incomplete fetch.
"""

import re
from typing import Any

from erio_core.connectors._paged import PagedJsonConnector
from erio_core.connectors._util import as_url, epoch_seconds
from erio_core.schemas import PartialJob, RawPosting, RemoteStatus

TOKEN = re.compile(r"([a-z0-9][a-z0-9-]{0,62})/([a-z0-9][a-z0-9.-]{0,120}\.[a-z]{2,24})")
PAGE = 10
WORKPLACE: dict[str, RemoteStatus] = {"remote": "remote", "hybrid": "hybrid", "onsite": "onsite"}


def _parts(board_token: str) -> tuple[str, str]:
    match = TOKEN.fullmatch(board_token)
    if not match:
        raise ValueError(f"not an Eightfold token (tenant/domain): {board_token!r}")
    return match[1], match[2]


class EightfoldConnector(PagedJsonConnector):
    slug = "eightfold"
    hosts = frozenset({"*.eightfold.ai"})

    def _api(self, board_token: str) -> str:
        return f"https://{_parts(board_token)[0]}.eightfold.ai/api/pcsx"

    def list_url(self, board_token: str, page: int) -> str:
        domain = _parts(board_token)[1]
        return (
            f"{self._api(board_token)}/search?domain={domain}&start={(page - 1) * PAGE}&num={PAGE}"
        )

    def items(self, data: Any) -> list[dict[str, Any]]:
        return list(data["data"]["positions"])

    def has_more(self, data: Any, items: list[dict[str, Any]], page: int) -> bool:
        return int(data["data"].get("count") or 0) > page * PAGE

    def detail_url(self, board_token: str, item: dict[str, Any]) -> str | None:
        domain = _parts(board_token)[1]
        return f"{self._api(board_token)}/position_details?position_id={item['id']}&domain={domain}"

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        tenant, _ = _parts(raw.board_token)
        detail = (job.get("detail") or {}).get("data") or {}
        places = job.get("standardizedLocations") or job.get("locations") or []
        kinds: Any = next(
            (
                v
                for key in ("efcustomTextTimeTypeEvg", "efcustomTextTimeType")
                if (v := detail.get(key))
            ),
            [],
        )
        path = job.get("positionUrl") or f"/careers/job/{job['id']}"
        department = job.get("department")
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["name"]).strip(),
            apply_url=as_url(detail.get("publicUrl") or f"https://{tenant}.eightfold.ai{path}"),
            posted_at=epoch_seconds(job.get("postedTs")),
            location_text="; ".join(places) or None,
            workplace_type=WORKPLACE.get(str(job.get("workLocationOption") or "").lower()),
            employment_type=", ".join(kinds) if isinstance(kinds, list) else str(kinds),
            departments=[department] if department else [],
            description_html=detail.get("jobDescription"),
        )
