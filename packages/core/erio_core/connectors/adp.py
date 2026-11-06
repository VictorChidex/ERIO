"""ADP Workforce Now career centers: the public JSON their career page calls.

- list:   GET https://workforcenow.adp.com/mascsr/default/careercenter/public/events/staffing/v1/job-requisitions
          ?cid={cid}&lang=en_US&locale=en_US&$top=20&$skip=n  (meta.totalNumber is the total)
- detail: the same path plus /{itemID}, which adds the HTML description

The board token is the ``cid`` (a UUID) of a career-center address such as
https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html?cid={cid}.
MyJobs / Recruiting Manager sites (myjobs.adp.com) need a session token and are not read.
"""

import re
from typing import Any

from erio_core.connectors._paged import PagedJsonConnector
from erio_core.connectors._util import as_url, iso_datetime, salary
from erio_core.schemas import PartialJob, RawPosting

TOKEN = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
PAGE = 20
ROOT = "https://workforcenow.adp.com/mascsr/default"
API = f"{ROOT}/careercenter/public/events/staffing/v1/job-requisitions"


def _cid(board_token: str) -> str:
    token = board_token.lower()
    if not TOKEN.fullmatch(token):
        raise ValueError(f"not an ADP Workforce Now cid (a UUID): {board_token!r}")
    return token


def _field(item: dict[str, Any], group: str, name: str) -> dict[str, Any]:
    fields = (item.get("customFieldGroup") or {}).get(group) or []
    return next((f for f in fields if (f.get("nameCode") or {}).get("codeValue") == name), {})


class ADPConnector(PagedJsonConnector):
    slug = "adp"
    hosts = frozenset({"workforcenow.adp.com"})
    max_details = 200

    def list_url(self, board_token: str, page: int) -> str:
        return (
            f"{API}?cid={_cid(board_token)}&lang=en_US&locale=en_US"
            f"&$top={PAGE}&$skip={(page - 1) * PAGE}"
        )

    def items(self, data: Any) -> list[dict[str, Any]]:
        return list(data["jobRequisitions"])

    def has_more(self, data: Any, items: list[dict[str, Any]], page: int) -> bool:
        return int((data.get("meta") or {}).get("totalNumber") or 0) > page * PAGE

    def item_id(self, item: dict[str, Any]) -> str:
        return str(item["itemID"])

    def detail_url(self, board_token: str, item: dict[str, Any]) -> str | None:
        return f"{API}/{item['itemID']}?cid={_cid(board_token)}&lang=en_US&locale=en_US"

    def parse(self, raw: RawPosting) -> PartialJob:
        item = raw.payload
        detail = item.get("detail") or {}
        place = (item.get("requisitionLocations") or [{}])[0]
        address = place.get("address") or {}
        region = (address.get("countrySubdivisionLevel1") or {}).get("codeValue")
        name = ((place.get("nameCode") or {}).get("shortName") or "").strip()
        reference = item.get("clientRequisitionID")
        apply_url = (
            f"{ROOT}/mdf/recruitment/recruitment.html?cid={_cid(raw.board_token)}"
            f"&lang=en_US&type=MP"
        )
        pay = item.get("payGradeRange") or {}
        low = (pay.get("minimumRate") or {}).get("amountValue")
        high = (pay.get("maximumRate") or {}).get("amountValue")
        currency = (pay.get("minimumRate") or {}).get("currencyCode")
        period = _field(item, "codeFields", "SalaryType").get("shortName")
        # ADP labels hourly wages "Annually" when the employer leaves the type unset.
        hint = salary(low, high, currency, period) if (high or low or 0) >= 1000 else None
        department = _field(item, "stringFields", "HomeDepartment").get("stringValue")
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(item["requisitionTitle"]).strip(),
            apply_url=as_url(f"{apply_url}&jobId={reference}" if reference else apply_url),
            posted_at=iso_datetime(item.get("postDate")),
            location_text=name or None,
            city=address.get("cityName") or None,
            region=region or None,
            workplace_type="remote" if "telecommut" in name.lower() else None,
            employment_type=(item.get("workLevelCode") or {}).get("shortName"),
            departments=[department] if department else [],
            salary=hint,
            description_html=detail.get("requisitionDescription"),
        )
