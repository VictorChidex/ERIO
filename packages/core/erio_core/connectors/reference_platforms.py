"""Platforms found by comparing ERIO with the reference index (docs/reference-study-jobindex.md).

Each reads a public, unauthenticated surface that the platform's own sites serve to every
visitor; how each was found, and its limits, is in docs/connectors.md.

- TRAFFIT: ``GET https://{tenant}.traffit.com/public/job_posts/published``, the JSON list
  behind every TRAFFIT career site, descriptions inline.
- Emply: the career site's own search call (``POST /api/integration/vacancy/get-page``). The
  page names its list section in its script; the call returns every published vacancy.
- HiringRoom: server-rendered ``/jobs`` list and ``/jobs/get_vacancy/{id}`` pages (no
  structured data, so the page's own markup is read).
- MyJobMag: the aggregate RSS feed the site publishes for job aggregators.
"""

import html
import json
import re
from typing import Any
from urllib.parse import urlsplit

from pydantic import HttpUrl

from erio_core.connectors._service import plain, service_host
from erio_core.connectors._util import as_url, iso_datetime, join_html
from erio_core.connectors.base import (
    BoardFetch,
    Connector,
    Fetcher,
    FetchError,
    poster,
)
from erio_core.connectors.feed import feed_date, stable_id, xml_items
from erio_core.schemas import PartialJob, RawPosting, RemoteStatus

TOKEN = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")


def _status(response_status: int) -> None:
    if response_status == 429:
        raise FetchError("rate_limited", "source rate limit", 429)
    if response_status != 200:
        raise FetchError("http_error", f"HTTP {response_status}", response_status)


# ---------------------------------------------------------------- TRAFFIT


class TraffitConnector(Connector):
    slug = "traffit"
    hosts = frozenset({"*.traffit.com"})

    def board_url(self, board_token: str) -> str:
        if not TOKEN.fullmatch(board_token):
            raise ValueError(f"not a TRAFFIT subdomain: {board_token!r}")
        return f"https://{board_token}.traffit.com/public/job_posts/published"

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        jobs = json.loads(body)
        if not isinstance(jobs, list):
            raise ValueError("TRAFFIT answers with a JSON array")
        return [
            RawPosting(
                source_slug=self.slug,
                board_token=board_token,
                external_id=str(job["id"]),
                payload=job,
            )
            for job in jobs
            if isinstance(job, dict) and job.get("id") is not None and job.get("advert")
        ]

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        advert = job["advert"]
        fields = {v.get("field_id"): v.get("value") for v in advert.get("values") or []}
        options = job.get("options") or {}
        place: dict[str, Any] = {}
        for text in (options.get("job_location"), fields.get("geolocation")):
            try:
                place = json.loads(text) if isinstance(text, str) else {}
            except ValueError:
                place = {}
            if place:
                break
        sections = [job.get(key) or fields.get(key) for key in ("requirements", "benefits")]
        locality = plain(place.get("locality"))
        remote = str(options.get("remote") or "0") == "1"
        workplace: RemoteStatus | None = "remote" if remote else None
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(advert["name"]).strip(),
            apply_url=as_url(str(job["url"])),
            posted_at=iso_datetime(job.get("valid_start")),
            location_text=", ".join(
                p for p in (locality, plain(place.get("region1")), plain(place.get("country"))) if p
            )
            or None,
            city=locality,
            region=plain(place.get("region1")),
            country_hint=(plain(place.get("iso")) or "").upper() or None,
            workplace_type=workplace,
            description_html=join_html(
                job.get("description") or fields.get("description"), *sections
            ),
        )


# ------------------------------------------------------------------ Emply

SECTION = re.compile(r"sectionId:\s*'([0-9a-f-]{36})'")
LANGUAGE = re.compile(r"var languageKey = '([A-Za-z-]{2,10})'")
EMPLY_PAGE = 50


def _emply_host(board_token: str) -> str:
    if board_token.startswith("https://"):
        host = urlsplit(board_token).hostname
        if not host:
            raise ValueError(f"not an Emply career site address: {board_token!r}")
        return host
    if not TOKEN.fullmatch(board_token):
        raise ValueError(f"not an Emply career site name: {board_token!r}")
    return f"{board_token}.career.emply.com"


class EmplyConnector(Connector):
    slug = "emply"
    hosts = frozenset({"*.career.emply.com"})
    max_pages = 10

    def board_url(self, board_token: str) -> str:
        return f"https://{_emply_host(board_token)}/"

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        data = json.loads(body)
        return [self._raw(board_token, v) for v in data["vacancies"] if not v.get("talentPool")]

    def _raw(self, board_token: str, vacancy: dict[str, Any]) -> RawPosting:
        return RawPosting(
            source_slug=self.slug,
            board_token=board_token,
            external_id=str(vacancy["shortId"]),
            payload=vacancy,
        )

    def list_postings(
        self, fetcher: Fetcher, board_token: str, etag: str | None = None
    ) -> BoardFetch:
        host = _emply_host(board_token)
        home = fetcher.get(self.board_url(board_token))
        _status(home.status)
        text = home.body.decode("utf-8", "replace")
        sections = list(dict.fromkeys(SECTION.findall(text)))[:3]
        language = (LANGUAGE.findall(text) or ["en-GB"])[0]
        postings: dict[str, RawPosting] = {}
        first = b""
        complete = True
        for section in sections:
            offset = 0
            for page in range(self.max_pages):
                body = {
                    "count": EMPLY_PAGE, "filters": [], "langCode": language, "offset": offset,
                    "searchText": "", "sectionId": section, "sortByProjectDataId": "",
                    "sortAscending": False, "light": False, "isJobAgent": False, "siteId": None,
                }  # fmt: skip
                response = poster(fetcher).post_json(
                    f"https://{host}/api/integration/vacancy/get-page", body
                )
                _status(response.status)
                first = first or response.body
                try:
                    found = self.extract(response.body, board_token)
                    listed = len(json.loads(response.body)["vacancies"])
                except (ValueError, KeyError, TypeError) as error:
                    raise FetchError("parse_error", f"malformed payload: {error}", 200) from error
                for raw in found:
                    postings[raw.external_id] = raw
                offset += listed
                if listed < EMPLY_PAGE:
                    break
                if page == self.max_pages - 1:
                    complete = False
        if sections and not postings and not first:
            raise FetchError("parse_error", "no vacancies answer", 200)
        return BoardFetch(
            postings=list(postings.values()), http_status=200, body=first, complete=complete
        )

    def parse(self, raw: RawPosting) -> PartialJob:
        vacancy = raw.payload
        translations = vacancy.get("translations") or [{}]
        text = translations[0]
        host = _emply_host(raw.board_token)
        place = plain(vacancy.get("location"))
        if place and " / " in place:
            place = place.split(" / ", 1)[1]  # "Site name / street, postcode, city, country"
        link = vacancy.get("directLink") or vacancy.get("applyLink")
        url = (
            link
            if isinstance(link, str) and link.startswith("https://")
            else f"https://{host}/ad/{vacancy['titleAsUrl']}/{vacancy['shortId']}"
        )
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(vacancy.get("title") or text.get("title")).strip(),
            apply_url=HttpUrl(url),
            posted_at=iso_datetime(vacancy.get("published")),
            location_text=place,
            departments=[d] if (d := plain(vacancy.get("department"))) else [],
            description_html=(text.get("content") or "").strip() or None,
        )


# ------------------------------------------------------------- HiringRoom

VACANCY = re.compile(r'href="/jobs/get_vacancy/([0-9a-f]{24})"')
H2 = re.compile(r'class="hero__title">\s*<h2[^>]*>\s*(.*?)\s*</h2>', re.S)
PIN = re.compile(r'hr-Location-pin"></span>\s*([^<]*?)\s*</p>')
AREA = re.compile(r'hr-Work-area"></span>\s*([^<]*?)\s*</p>')
TAG = re.compile(
    r'<div class="commonstxt hero__tag">\s*<span[^>]*></span>\s*([^<]*?)\s*(?:<!--|</div>)'
)
BODY = re.compile(r'job-description-content">(.*?)</div>', re.S)
WORKPLACE: dict[str, RemoteStatus] = {
    "remoto": "remote", "remote": "remote", "híbrido": "hybrid", "hibrido": "hybrid",
    "hybrid": "hybrid", "presencial": "onsite", "on-site": "onsite",
}  # fmt: skip


class HiringRoomConnector(Connector):
    slug = "hiringroom"
    hosts = frozenset({"*.hiringroom.com"})
    max_details = 100

    def board_url(self, board_token: str) -> str:
        if not TOKEN.fullmatch(board_token):
            raise ValueError(f"not a HiringRoom subdomain: {board_token!r}")
        return f"https://{board_token}.hiringroom.com/jobs"

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        """The vacancy page the board token names (one posting), for the shared tests."""
        return [self._read(board_token, body.decode("utf-8", "replace"), "")]

    def _read(self, board_token: str, page: str, vacancy: str) -> RawPosting:
        title = H2.search(page)
        if not title:
            raise ValueError("no vacancy title on the page")
        pin, area, body = PIN.search(page), AREA.search(page), BODY.search(page)
        return RawPosting(
            source_slug=self.slug,
            board_token=board_token,
            external_id=vacancy,
            payload={
                "title": html.unescape(re.sub(r"<[^>]+>", "", title[1])).strip(),
                "location": html.unescape(pin[1]) if pin else None,
                "area": html.unescape(area[1]) if area else None,
                "tags": list(dict.fromkeys(html.unescape(t) for t in TAG.findall(page) if t)),
                "description": body[1].strip() if body else None,
            },
        )

    def list_postings(
        self, fetcher: Fetcher, board_token: str, etag: str | None = None
    ) -> BoardFetch:
        listing = fetcher.get(self.board_url(board_token))
        _status(listing.status)
        ids = list(dict.fromkeys(VACANCY.findall(listing.body.decode("utf-8", "replace"))))
        postings: list[RawPosting] = []
        unread = 0
        for vacancy in ids[: self.max_details]:
            page = fetcher.get(f"https://{board_token}.hiringroom.com/jobs/get_vacancy/{vacancy}")
            if page.status != 200:
                unread += page.status not in (404, 410)
                continue
            try:
                postings.append(
                    self._read(board_token, page.body.decode("utf-8", "replace"), vacancy)
                )
            except ValueError:
                unread += 1
        if ids and not postings:
            raise FetchError("parse_error", "vacancy pages carry no readable job", 200)
        return BoardFetch(
            postings=postings,
            http_status=200,
            body=listing.body,
            complete=len(ids) <= self.max_details and unread == 0,
        )

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        tags = [str(t) for t in job.get("tags") or []]
        workplace = next((WORKPLACE[t.lower()] for t in tags if t.lower() in WORKPLACE), None)
        kind = next((t for t in tags if t.lower() not in WORKPLACE), None)
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["title"]),
            apply_url=HttpUrl(
                f"https://{raw.board_token}.hiringroom.com/jobs/get_vacancy/{raw.external_id}"
            ),
            location_text=plain(job.get("location")),
            workplace_type=workplace,
            employment_type=kind,
            departments=[a] if (a := plain(job.get("area"))) else [],
            description_html=job.get("description") or None,
        )


# --------------------------------------------------------------- MyJobMag


class MyJobMagConnector(Connector):
    """MyJobMag's aggregate feed: every current job with employer, place and full text.

    Each job links to the site's own redirect page, so candidates apply on MyJobMag.
    Sites: Nigeria (www.myjobmag.com), Kenya and South Africa (www.myjobmag.co.ke / .co.za).
    """

    slug = "myjobmag"
    hosts = frozenset({"www.myjobmag.com", "www.myjobmag.co.ke", "www.myjobmag.co.za"})
    multi_employer = True

    def board_url(self, board_token: str) -> str:
        return f"https://{service_host(board_token, self.hosts, 'MyJobMag')}/aggregate_feed.xml"

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        postings = []
        for fields in xml_items(body):
            first = {name: (values[0] if values else "") for name, values in fields.items()}
            if not first.get("title") or not first.get("id"):
                continue
            postings.append(
                RawPosting(
                    source_slug=self.slug,
                    board_token=board_token,
                    external_id=stable_id(first["id"]),
                    payload=first,
                )
            )
        if not postings:
            raise ValueError("no jobs in the MyJobMag feed")
        return postings

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        host = urlsplit(raw.board_token).hostname or ""
        country = {"ke": "KE", "za": "ZA"}.get(host.rsplit(".", 1)[-1], "NG")
        place = ", ".join(
            dict.fromkeys(p for p in (plain(job.get("location")), plain(job.get("region"))) if p)
        )
        kinds = [plain(job.get("working_hours")), plain(job.get("contract"))]
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=plain(job.get("position")) or plain(job["title"]) or "",
            company_name=plain(job.get("company")),
            apply_url=as_url(str(job["link"])),
            posted_at=feed_date(job.get("pubdate")),
            location_text=place or None,
            country_hint=country,
            employment_type=", ".join(k for k in kinds if k) or None,
            departments=[d] if (d := plain(job.get("industry"))) else [],
            description_html=job.get("description") or None,
        )


REFERENCE_CONNECTORS: list[Connector] = [
    TraffitConnector(),
    EmplyConnector(),
    HiringRoomConnector(),
    MyJobMagConnector(),
]
