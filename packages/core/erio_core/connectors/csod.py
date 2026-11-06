"""Cornerstone OnDemand (CSOD) career sites: the public JSON the career page calls.

The career page sends every anonymous visitor (user -115, no login) a short-lived read
token and the regional API address in its ``csod.context`` script; the page's own
scripts then search jobs with it.

- session: GET https://{tenant}.csod.com/ux/ats/careersite/{n}/home?c={tenant}
- list:    POST {cloud}rec-job-search/external/jobs with header Authorization (the token),
           {"careerSiteId": n, "pageNumber": p, "pageSize": 100, ...}; descriptions inline

The board token is "{tenant}/{careerSiteNumber}" from a career-site address. The token
is only ever sent to a ``*.api.csod.com`` address. robots.txt asks for a 10 second
crawl delay on the tenant host, which the fetcher honours. A crawl reads at most
``max_pages`` pages of 100, and a larger board is reported as an incomplete fetch.
"""

import html
import json
import re
from datetime import UTC, datetime
from typing import Any

from erio_core.connectors._post import header_poster
from erio_core.connectors._util import as_url
from erio_core.connectors.base import BoardFetch, Connector, Fetcher, FetchError
from erio_core.schemas import PartialJob, RawPosting

TOKEN = re.compile(r"([a-z0-9][a-z0-9-]{0,62})/(\d{1,6})")
CLOUD = re.compile(r"https://[a-z0-9-]{1,30}\.api\.csod\.com/")
CONTEXT = re.compile(r"csod\.context\s*=\s*(\{.*?\});?\s*</script>", re.S)
PAGE = 100


def _parts(board_token: str) -> tuple[str, str]:
    match = TOKEN.fullmatch(board_token)
    if not match:
        raise ValueError(f"not a CSOD token (tenant/careerSiteNumber): {board_token!r}")
    return match[1], match[2]


def _apply_url(tenant: str, site: str, requisition: str) -> str:
    return (
        f"https://{tenant}.csod.com/ux/ats/careersite/{site}/home/requisition/{requisition}"
        f"?c={tenant}"
    )


class CsodConnector(Connector):
    slug = "csod"
    hosts = frozenset({"*.csod.com", "*.api.csod.com"})
    max_pages = 20

    def board_url(self, board_token: str) -> str:
        tenant, site = _parts(board_token)
        return f"https://{tenant}.csod.com/ux/ats/careersite/{site}/home?c={tenant}"

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        data = json.loads(body)["data"]
        return [self._raw(board_token, item) for item in data["requisitions"]]

    def _raw(self, board_token: str, item: dict[str, Any]) -> RawPosting:
        return RawPosting(
            source_slug=self.slug,
            board_token=board_token,
            external_id=str(item["requisitionId"]),
            payload=item,
        )

    def list_postings(
        self, fetcher: Fetcher, board_token: str, etag: str | None = None
    ) -> BoardFetch:
        _, site = _parts(board_token)
        home = fetcher.get(self.board_url(board_token))
        if home.status == 429:
            raise FetchError("rate_limited", "source rate limit", 429)
        if home.status != 200:
            raise FetchError("http_error", f"HTTP {home.status}", home.status)
        found = CONTEXT.search(home.body.decode("utf-8", "replace"))
        try:
            context = json.loads(found[1]) if found else {}
            cloud = str(context["endpoints"]["cloud"])
            token = str(context["token"])
        except (ValueError, KeyError, TypeError) as error:
            raise FetchError("parse_error", "no public search token on the page", 200) from error
        if not CLOUD.fullmatch(cloud):
            raise FetchError("parse_error", f"unexpected API address {cloud!r}", 200)
        postings: dict[str, RawPosting] = {}
        first = b""
        complete = True
        for number in range(1, self.max_pages + 1):
            body: dict[str, Any] = {
                "careerSiteId": int(site), "careerSitePageId": int(site), "pageNumber": number,
                "pageSize": PAGE, "cultureId": context.get("cultureID") or 1, "searchText": "",
                "cultureName": context.get("cultureName") or "en-US", "states": [],
                "countryCodes": [], "cities": [], "placeID": "", "radius": None,
                "postingsWithinDays": None, "customFieldCheckboxKeys": [],
                "customFieldDropdowns": [], "customFieldRadios": [],
            }  # fmt: skip
            response = header_poster(fetcher).post_json_with(
                f"{cloud}rec-job-search/external/jobs", body, {"Authorization": f"Bearer {token}"}
            )
            if response.status == 429:
                raise FetchError("rate_limited", "source rate limit", 429)
            if response.status != 200:
                raise FetchError("http_error", f"HTTP {response.status}", response.status)
            first = first or response.body
            try:
                data = json.loads(response.body)["data"]
                items = data["requisitions"]
                total = int(data["totalCount"])
            except (ValueError, KeyError, TypeError) as error:
                raise FetchError("parse_error", f"malformed payload: {error}", 200) from error
            for item in items:
                postings[str(item["requisitionId"])] = self._raw(board_token, item)
            if not items or number * PAGE >= total:
                break
            if number == self.max_pages:
                complete = False
        return BoardFetch(
            postings=list(postings.values()), http_status=200, body=first, complete=complete
        )

    def parse(self, raw: RawPosting) -> PartialJob:
        item = raw.payload
        tenant, site = _parts(raw.board_token)
        places = [
            ", ".join(str(p) for p in (loc.get("city"), loc.get("state"), loc.get("country")) if p)
            for loc in item.get("locations") or []
        ]
        first = (item.get("locations") or [{}])[0]
        text = str(item.get("externalDescription") or "").strip()
        try:
            posted = datetime.strptime(str(item.get("postingEffectiveDate")), "%m/%d/%Y")
        except ValueError:
            posted = None
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(item["displayJobTitle"]).strip(),
            apply_url=as_url(_apply_url(tenant, site, raw.external_id)),
            posted_at=posted.replace(tzinfo=UTC) if posted else None,
            location_text="; ".join(dict.fromkeys(p for p in places if p)) or None,
            city=(first.get("city") or "").title() or None,
            region=first.get("state") or None,
            country_hint=first.get("country") or None,
            description_html=(text if "<" in text else f"<p>{html.escape(text)}</p>")
            if text
            else None,
        )
