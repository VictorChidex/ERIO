"""BrassRing (Infinite) TalentGateway career sites on sjobs.brassring.com.

The search page issues its own anti-forgery values to every anonymous visitor, and the
page's script calls a public JSON search with them; there is no login.

- session: GET https://sjobs.brassring.com/TGnewUI/Search/Home/Home?partnerid=..&siteid=..
           (sets cookies; holds a request-verification field and an encrypted session value)
- page 1:  POST /TgNewUI/Search/Ajax/MatchedJobs with header RFT
- page n:  POST /TgNewUI/Search/Ajax/ProcessSortAndShowMoreJobs with ``pageNumber``

The board token is "{partnerid}/{siteid}" from a career-site address. A job is a list of
named questions, descriptions included; which question holds the location is set per
site (``JobFieldsToDisplay`` on the search page). Pages hold 50 jobs, and a crawl reads at
most ``max_pages``, so a larger board is reported as an incomplete fetch. The session
cookies need a fetcher whose client keeps them between requests.
"""

import html
import json
import re
from datetime import UTC, datetime
from typing import Any

from erio_core.connectors._post import header_poster
from erio_core.connectors._util import as_url
from erio_core.connectors.base import BoardFetch, Connector, Fetcher, FetchError, FetchResponse
from erio_core.schemas import PartialJob, RawPosting

TOKEN = re.compile(r"(\d{1,8})/(\d{1,8})")
HOST = "https://sjobs.brassring.com"
PAGE = 50
RFT = re.compile(r'name="__RequestVerificationToken"[^>]*?value="([^"]*)"')
SESSION = re.compile(r'id="CookieValue"[^>]*?value="([^"]*)"')
LAYOUT = re.compile(r'"JobFieldsToDisplay":(\{[^{}]*\})')
KEYWORD_FIELDS = re.compile(r'"KeywordCustomSolrFields":"([^"]*)"')


def _parts(board_token: str) -> tuple[str, str]:
    match = TOKEN.fullmatch(board_token)
    if not match:
        raise ValueError(f"not a BrassRing token (partnerid/siteid): {board_token!r}")
    return match[1], match[2]


def _updated(text: str | None) -> datetime | None:
    for form in ("%d-%b-%Y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text or "", form).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


class BrassRingConnector(Connector):
    slug = "brassring"
    hosts = frozenset({"sjobs.brassring.com"})
    max_pages = 20

    def board_url(self, board_token: str) -> str:
        partner, site = _parts(board_token)
        return f"{HOST}/TGnewUI/Search/Home/Home?partnerid={partner}&siteid={site}"

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        jobs = (json.loads(body).get("Jobs") or {}).get("Job") or []
        return [self._raw(board_token, job, {}) for job in jobs]

    def _raw(self, board_token: str, job: dict[str, Any], layout: dict[str, Any]) -> RawPosting:
        fields = {q["QuestionName"].lower(): q.get("Value") for q in job["Questions"]}
        return RawPosting(
            source_slug=self.slug,
            board_token=board_token,
            external_id=str(fields["reqid"]),
            payload={"fields": fields, "link": job.get("Link"), "layout": layout},
        )

    def _post(
        self, fetcher: Fetcher, path: str, payload: dict[str, Any], rft: str
    ) -> dict[str, Any]:
        response: FetchResponse = header_poster(fetcher).post_json_with(
            f"{HOST}{path}", payload, {"RFT": rft, "X-Requested-With": "XMLHttpRequest"}
        )
        if response.status == 429:
            raise FetchError("rate_limited", "source rate limit", 429)
        if response.status != 200:
            raise FetchError("http_error", f"HTTP {response.status}", response.status)
        try:
            data = json.loads(response.body)
        except ValueError as error:
            raise FetchError("parse_error", f"malformed payload: {error}", 200) from error
        if not isinstance(data, dict):
            raise FetchError("parse_error", "malformed payload", 200)
        return data

    def list_postings(
        self, fetcher: Fetcher, board_token: str, etag: str | None = None
    ) -> BoardFetch:
        partner, site = _parts(board_token)
        home = fetcher.get(self.board_url(board_token))
        if home.status == 429:
            raise FetchError("rate_limited", "source rate limit", 429)
        if home.status != 200:
            raise FetchError("http_error", f"HTTP {home.status}", home.status)
        page = home.body.decode("utf-8", "replace")
        rft, session = RFT.search(page), SESSION.search(page)
        if not rft or not session:
            raise FetchError("parse_error", "no search session on the career site", 200)
        token, cookie = html.unescape(rft[1]), html.unescape(session[1])
        settings = html.unescape(page)
        found = LAYOUT.search(settings)
        layout = json.loads(found[1]) if found else {}
        keyword = KEYWORD_FIELDS.search(settings)
        postings: list[RawPosting] = []
        first = b""
        complete = True
        total = 0
        for number in range(1, self.max_pages + 1):
            if number == 1:
                path = "/TgNewUI/Search/Ajax/MatchedJobs"
                body = self._first(partner, site, cookie)
            else:
                path = "/TgNewUI/Search/Ajax/ProcessSortAndShowMoreJobs"
                body = self._more(partner, site, cookie, number, keyword[1] if keyword else "")
            try:
                data = self._post(fetcher, path, body, token)
            except FetchError:
                if number == 1:
                    raise
                complete = False  # a later page failed: what was read is partial
                break
            first = first or json.dumps(data).encode()
            jobs = (data.get("Jobs") or {}).get("Job") or []
            total = int(data.get("JobsCount") or total or 0)
            postings += [self._raw(board_token, job, layout) for job in jobs]
            if not jobs or number * PAGE >= total:
                break
            if number == self.max_pages:
                complete = False
        unique = list({p.external_id: p for p in postings}.values())
        return BoardFetch(postings=unique, http_status=200, body=first, complete=complete)

    def _first(self, partner: str, site: str, cookie: str) -> dict[str, Any]:
        return {
            "PartnerId": partner, "SiteId": site, "Keyword": "", "Location": "",
            "LocationCustomSolrFields": "Location", "FacetFilterFields": None,
            "TurnOffHttps": False, "Latitude": 0, "Longitude": 0,
            "PowerSearchOptions": {"PowerSearchOption": []}, "encryptedsessionvalue": cookie,
        }  # fmt: skip

    def _more(
        self, partner: str, site: str, cookie: str, number: int, keyword_fields: str
    ) -> dict[str, Any]:
        return {
            "partnerId": partner, "siteId": site, "keyword": "", "location": "",
            "keywordCustomSolrFields": keyword_fields, "locationCustomSolrFields": "Location",
            "linkId": "", "Latitude": 0, "Longitude": 0, "facetfilterfields": {"Facet": []},
            "powersearchoptions": {"PowerSearchOption": []}, "SortType": "LastUpdated",
            "pageNumber": number, "encryptedSessionValue": cookie,
        }  # fmt: skip

    def parse(self, raw: RawPosting) -> PartialJob:
        fields = raw.payload["fields"]
        layout = raw.payload.get("layout") or {}
        partner, site = _parts(raw.board_token)
        places = [
            str(fields[name.lower()]).strip(" ,")
            for name in layout.get("Position3") or []
            if name.lower() not in ("autoreq", "reqid") and fields.get(name.lower())
        ]
        link = str(raw.payload.get("link") or "")
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(fields["jobtitle"]).strip(),
            apply_url=as_url(
                link
                if link.startswith("https://")
                else f"{HOST}/TGnewUI/Search/home/HomeWithPreLoad?partnerid={partner}"
                f"&siteid={site}&PageType=JobDetails&jobid={raw.external_id}"
            ),
            posted_at=_updated(fields.get("lastupdated")),
            location_text="; ".join(places) or None,
            description_html=fields.get("jobdescription") or None,
        )
