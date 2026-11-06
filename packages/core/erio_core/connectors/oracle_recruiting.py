"""Oracle Recruiting (Fusion HCM Candidate Experience): the public REST the career site calls.

- list:   GET https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions
          ?finder=findReqs;siteNumber={site},limit=50,offset=n (expand the requisition list)
- detail: GET .../recruitingCEJobRequisitionDetails?expand=all
          &finder=ById;Id="{id}",siteNumber={site}

The board token is "{host}/{siteNumber}" from a career-site address such as
https://eeho.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_45001/.
The list carries a short description only: a crawl reads the first ``max_details``
jobs' details, and a larger board is reported as an incomplete fetch.
"""

import re
from typing import Any

from erio_core.connectors._paged import PagedJsonConnector
from erio_core.connectors._util import as_url, iso_datetime
from erio_core.schemas import PartialJob, RawPosting, RemoteStatus

TOKEN = re.compile(
    r"([a-z0-9][a-z0-9-]{0,62}\.fa\.(?:[a-z0-9]{2,6}\.)?oraclecloud\.com)/([A-Za-z0-9_-]{1,40})"
)
PAGE = 50
DATACENTERS = (
    "us2", "us6", "us1", "em1", "em2", "em3", "em4", "em5", "em6", "em8", "ap1", "ap2", "ap3",
    "ap4", "ap5", "ca1", "ca2", "ca3", "uk1", "sa1", "me1", "ocs",
)  # fmt: skip
WORKPLACE: dict[str, RemoteStatus] = {
    "ORA_ON_SITE": "onsite", "ORA_REMOTE": "remote", "ORA_HYBRID": "hybrid"
}  # fmt: skip


def _parts(board_token: str) -> tuple[str, str]:
    match = TOKEN.fullmatch(board_token)
    if not match:
        raise ValueError(f"not an Oracle Recruiting token (host/siteNumber): {board_token!r}")
    return match[1], match[2]


class OracleRecruitingConnector(PagedJsonConnector):
    slug = "oracle_recruiting"
    hosts = frozenset(
        {"*.fa.oraclecloud.com", *(f"*.fa.{dc}.oraclecloud.com" for dc in DATACENTERS)}
    )
    max_pages = 40
    max_details = 150

    def _api(self, board_token: str) -> str:
        host, _ = _parts(board_token)
        return f"https://{host}/hcmRestApi/resources/latest"

    def list_url(self, board_token: str, page: int) -> str:
        _, site = _parts(board_token)
        finder = f"findReqs;siteNumber={site},limit={PAGE},offset={(page - 1) * PAGE}"
        return (
            f"{self._api(board_token)}/recruitingCEJobRequisitions?onlyData=true"
            f"&expand=requisitionList.secondaryLocations&finder={finder},sortBy=POSTING_DATES_DESC"
        )

    def items(self, data: Any) -> list[dict[str, Any]]:
        return list(data["items"][0].get("requisitionList") or [])

    def item_id(self, item: dict[str, Any]) -> str:
        return str(item["Id"])

    def has_more(self, data: Any, items: list[dict[str, Any]], page: int) -> bool:
        return page * PAGE < int(data["items"][0].get("TotalJobsCount") or 0)

    def detail_url(self, board_token: str, item: dict[str, Any]) -> str | None:
        _, site = _parts(board_token)
        return (
            f"{self._api(board_token)}/recruitingCEJobRequisitionDetails?expand=all&onlyData=true"
            f'&finder=ById;Id="{item["Id"]}",siteNumber={site}'
        )

    def parse(self, raw: RawPosting) -> PartialJob:
        item = raw.payload
        host, site = _parts(raw.board_token)
        detail = ((item.get("detail") or {}).get("items") or [{}])[0]
        places = [item.get("PrimaryLocation")]
        places += [p.get("Name") for p in item.get("secondaryLocations") or []]
        description = "".join(
            str(detail[key])
            for key in ("ExternalDescriptionStr", "ExternalResponsibilitiesStr")
            if detail.get(key)
        )
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(item["Title"]).strip(),
            apply_url=as_url(
                f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{item['Id']}"
            ),
            posted_at=iso_datetime(detail.get("ExternalPostedStartDate") or item.get("PostedDate")),
            location_text="; ".join(dict.fromkeys(p for p in places if p)) or None,
            country_hint=item.get("PrimaryLocationCountry") or None,
            workplace_type=WORKPLACE.get(str(item.get("WorkplaceTypeCode"))),
            employment_type=detail.get("ContractType") or item.get("ContractType"),
            departments=[d] if (d := detail.get("Category")) else [],
            description_html=description or item.get("ShortDescriptionStr"),
        )
