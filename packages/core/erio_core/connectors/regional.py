"""Platforms found through the jobindex.space reference list (batch: InHire, Solides,
Senior Portal de Talentos, The Hub, Recrutei, Cegid DigitalRecruiters, Intervieweb
Inrecruiting, AppliTrack, CHECK-IN by perbility).

Each is read the way an anonymous visitor's browser reads it: the public JSON the
career site itself calls, or the schema.org JobPosting on its job pages. How each
was found, and what limits it has, is in the platform's entry of
``erio_core/data/platforms.json``.

- InHire: ``GET https://api.inhire.app/job-posts/public/pages`` with the header
  ``X-Tenant: {tenant}``, documented at docs.inhire.com.br for public career pages.
- Solides Vagas: ``GET https://vagas.solides.com.br/api/vacancies`` (the portal's own list).
- Senior Portal de Talentos: the portal's anonymous ``searchVacancies`` query.
- The Hub, Recrutei Empregos, Cegid DigitalRecruiters, Intervieweb Inrecruiting:
  JobPosting data on job pages, found from a sitemap or a listing page.
- AppliTrack (Frontline): the embeddable posting list of one district.
- CHECK-IN (perbility): job pages marked up with schema.org microdata.
"""

import json
import re
import unicodedata
from typing import Any
from urllib.parse import unquote

from erio_core.connectors._htmlpages import (
    PageCrawler,
    element_at,
    element_with,
    listing,
    read_date,
    text_of,
)
from erio_core.connectors._paged import PagedJsonConnector
from erio_core.connectors._service import plain, service_host
from erio_core.connectors._util import as_url, iso_datetime, salary
from erio_core.connectors.base import (
    BoardFetch,
    Connector,
    Fetcher,
    FetchError,
    FetchResponse,
    header_getter,
    poster,
)
from erio_core.connectors.jsonld import JsonLdConnector
from erio_core.schemas import PartialJob, RawPosting, RemoteStatus

TENANT = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")

# InHire ---------------------------------------------------------------------------------

INHIRE_WORKPLACE: dict[str, RemoteStatus] = {
    "remote": "remote", "hybrid": "hybrid", "on-site": "onsite",
}  # fmt: skip


def _slug(title: str) -> str:
    """A title as InHire writes it in a job address: "Analista de TI (Pleno)" is
    ``analista-de-ti-pleno``."""
    folded = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")


class InHireConnector(PagedJsonConnector):
    """The board token is the tenant: the start of ``{tenant}.inhire.app``. The list has
    title, workplace and place per job; a job's description is a second request per job,
    which this connector leaves out."""

    slug = "inhire"
    hosts = frozenset({"api.inhire.app"})

    def list_url(self, board_token: str, page: int) -> str:
        if not TENANT.fullmatch(board_token):
            raise ValueError(f"not an InHire tenant: {board_token!r}")
        return "https://api.inhire.app/job-posts/public/pages"

    def fetch_page(self, fetcher: Fetcher, board_token: str, page: int) -> FetchResponse:
        url = self.list_url(board_token, page)
        return header_getter(fetcher).get_with(url, {"X-Tenant": board_token})

    def items(self, data: Any) -> list[dict[str, Any]]:
        company = data.get("tenantName")
        return [
            {**job, "tenantName": company}
            for job in data["jobsPage"]
            if job.get("status", "published") == "published"
        ]

    def item_id(self, item: dict[str, Any]) -> str:
        return str(item["jobId"])

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        place = job.get("location")
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["displayName"]).strip(),
            company_name=job.get("tenantName"),
            apply_url=as_url(
                f"https://{raw.board_token}.inhire.app/vagas/{raw.external_id}/"
                f"{_slug(str(job['displayName']))}"
            ),
            location_text=place or None,
            country_hint=str(place).rsplit(",", 1)[-1].strip() if place else None,
            workplace_type=INHIRE_WORKPLACE.get(str(job.get("workplaceType") or "").lower()),
        )


# Solides Vagas ----------------------------------------------------------------------------

SOLIDES_HOST = "vagas.solides.com.br"
SOLIDES_PAGE = 20  # the list answers HTTP 500 above about 20 a page
SOLIDES_WORKPLACE: dict[str, RemoteStatus] = {
    "presencial": "onsite", "hibrido": "hybrid", "remoto": "remote",
}  # fmt: skip


class SolidesConnector(PagedJsonConnector):
    """Solides Vagas lists the jobs of many Brazilian employers; the board token is
    ``https://vagas.solides.com.br``. A crawl reads the newest ``max_pages * 20`` jobs
    (the portal holds tens of thousands) and reports the rest as a partial read."""

    slug = "solides"
    hosts = frozenset({SOLIDES_HOST})
    multi_employer = True
    max_pages = 25

    def list_url(self, board_token: str, page: int) -> str:
        host = service_host(board_token, self.hosts, "Solides")
        return f"https://{host}/api/vacancies?page={page}&take={SOLIDES_PAGE}&locations="

    def items(self, data: Any) -> list[dict[str, Any]]:
        return [
            job for job in data["data"] if job.get("currentState", "em_andamento") == "em_andamento"
        ]

    def has_more(self, data: Any, items: list[dict[str, Any]], page: int) -> bool:
        return page < int(data.get("totalPages") or 0)

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        city = (job.get("city") or {}).get("name")
        state = (job.get("state") or {}).get("code")
        country = ((job.get("address") or {}).get("country") or {}).get("name") or "Brasil"
        pay = job.get("salary") or {}
        workplace: RemoteStatus | None = "remote" if job.get("homeOffice") else None
        kinds = [k["name"] for k in job.get("recruitmentContractType") or [] if k.get("name")]
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=plain(job["title"]) or "",
            company_name=plain(job.get("companyName")),
            apply_url=as_url(f"https://{SOLIDES_HOST}/vaga/{raw.external_id}"),
            posted_at=iso_datetime(job.get("createdAt")),
            location_text=", ".join(p for p in (city, state, country) if p) or None,
            city=city or None,
            region=state or None,
            country_hint="BR" if country == "Brasil" else country,
            workplace_type=workplace or SOLIDES_WORKPLACE.get(str(job.get("jobType") or "")),
            employment_type=", ".join(kinds) or None,
            departments=[a["name"] for a in job.get("occupationAreas") or [] if a.get("name")],
            salary=salary(pay.get("initialRange"), pay.get("finalRange"), "BRL", "month"),
            description_html=job.get("description") or None,
        )


# Senior Portal de Talentos -----------------------------------------------------------------

SENIOR_HOST = "platform.senior.com.br"
SENIOR_SEARCH = (
    f"https://{SENIOR_HOST}/t/senior.com.br/bridge/1.0/anonymous/rest/hcm/"
    "careersmanagercandidate/queries/searchVacancies"
)
SENIOR_PAGE = 100
SENIOR_WORKPLACE: dict[str, RemoteStatus] = {
    "IN_PERSON": "onsite", "HYBRID": "hybrid", "REMOTE": "remote",
}  # fmt: skip


class SeniorTalentosConnector(Connector):
    """Senior's Portal de Talentos holds the jobs of many employers, each on
    ``{tenant}.portaldetalentos.senior.com.br``. The portal's own anonymous search answers
    with every employer's jobs (no filter), 100 a page, without descriptions. The board
    token is ``https://platform.senior.com.br``."""

    slug = "senior_talentos"
    hosts = frozenset({SENIOR_HOST})
    multi_employer = True
    max_pages = 10

    def board_url(self, board_token: str) -> str:
        service_host(board_token, self.hosts, "Senior Portal de Talentos")
        return SENIOR_SEARCH

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        return [self._raw(board_token, item) for item in self._items(json.loads(body))]

    @staticmethod
    def _items(data: Any) -> list[dict[str, Any]]:
        if not isinstance(data, dict) or not isinstance(data.get("contents"), list):
            raise ValueError("expected {totalPages, contents: [...]}")
        return list(data["contents"])

    def _raw(self, board_token: str, item: dict[str, Any]) -> RawPosting:
        return RawPosting(
            source_slug=self.slug,
            board_token=board_token,
            external_id=str(item["vacancy"]["id"]),
            payload=item,
        )

    def list_postings(
        self, fetcher: Fetcher, board_token: str, etag: str | None = None
    ) -> BoardFetch:
        url = self.board_url(board_token)
        found: dict[str, RawPosting] = {}
        first = b""
        complete = True
        for page in range(self.max_pages):
            body = {"page": page, "size": SENIOR_PAGE, "filter": "", "match": {}}
            response = poster(fetcher).post_json(url, body)
            if response.status == 429:
                raise FetchError("rate_limited", "source rate limit", 429)
            if response.status != 200:
                raise FetchError("http_error", f"HTTP {response.status}", response.status)
            first = first or response.body
            try:
                data = json.loads(response.body)
                items = self._items(data)
                raws = [self._raw(board_token, item) for item in items]
                pages = int(data["totalPages"])
            except (ValueError, KeyError, TypeError) as error:
                raise FetchError("parse_error", f"malformed payload: {error}", 200) from error
            for raw in raws:
                found.setdefault(raw.external_id, raw)
            if not items or page + 1 >= pages:
                break
            if page + 1 == self.max_pages:
                complete = False
        return BoardFetch(
            postings=list(found.values()), http_status=200, body=first, complete=complete
        )

    def parse(self, raw: RawPosting) -> PartialJob:
        vacancy = raw.payload["vacancy"]
        company = raw.payload.get("company") or {}
        place = vacancy.get("localization") or {}
        modes = vacancy.get("jobModel") or []
        tenant = str(company.get("tenant") or "")
        host = (
            f"{tenant}.portaldetalentos.senior.com.br"
            if TENANT.fullmatch(tenant)
            else ("www.portaldetalentos.senior.com.br")
        )
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=plain(vacancy["title"]) or "",
            company_name=plain(company.get("name")),
            apply_url=as_url(f"https://{host}/vacancy/{raw.external_id}"),
            posted_at=iso_datetime((vacancy.get("publication") or {}).get("startDate")),
            location_text=", ".join(
                str(p)
                for p in (place.get("city"), place.get("province"), place.get("country"))
                if p
            )
            or None,
            city=place.get("city") or None,
            region=place.get("province") or None,
            country_hint="BR" if place.get("country") == "Brasil" else place.get("country"),
            workplace_type=SENIOR_WORKPLACE.get(str(modes[0])) if modes else None,
        )


# JobPosting data on job pages ----------------------------------------------------------------


class IntervieWebConnector(JsonLdConnector):
    """Inrecruiting career pages (``inrecruiting.intervieweb.it/{company}/it/career``) list
    15 jobs a page and fetch the next pages with a script. Only the first page is read: a
    board whose page says it has more pages is reported as a partial read, so the jobs it
    did not list are never closed for being absent."""

    PAGES = re.compile(r"Pagina\s+\d+\s+di\s+(\d+)")

    def list_postings(
        self, fetcher: Fetcher, board_token: str, etag: str | None = None
    ) -> BoardFetch:
        response = fetcher.get(self.board_url(board_token))
        if response.status != 200:
            raise FetchError("http_error", f"HTTP {response.status}", response.status)
        page = response.body.decode("utf-8", "replace")
        more = self.PAGES.search(page)
        fetched = super().list_postings(fetcher, board_token, etag)
        if more and int(more.group(1)) > 1:
            return BoardFetch(fetched.postings, fetched.http_status, fetched.body, complete=False)
        return fetched


# AppliTrack (Frontline Education) ----------------------------------------------------------

APPLITRACK_ENTRY = re.compile(r"<ul class='postingsList' id='p(\d+)_'>(.*?)</ul>", re.DOTALL)
APPLITRACK_TITLE = re.compile(r"<td id='wrapword'[^>]*>(.*?)</td>", re.DOTALL)
APPLITRACK_FIELD = re.compile(
    r"<li><span class=['\"]label['\"]\s*>([^<]*?):?</span>(.*?)</li>", re.DOTALL
)
APPLITRACK_ORG = re.compile(r"found at (.+?)\. The position is", re.DOTALL)


def _applitrack_description(block: str) -> str | None:
    """The text after the last field of a posting and before its spacer image."""
    spacer = block.find("clear.gif")
    if spacer < 0:
        return None
    head = block[:spacer].rsplit("<img", 1)[0]
    body = head[head.rfind("</li>") + len("</li>") :]
    body = re.sub(r"^\s*<span>(?:&nbsp;?)+</span>", "", body).strip()
    return body if text_of(body) else None


class AppliTrackConnector(Connector):
    """School-district postings on www.applitrack.com. ``view.asp?embed=1&all=1`` is the page
    districts embed in their own sites; it lists every posting with its details. The
    board token is the district's name in the address (``keyport``)."""

    slug = "applitrack"
    hosts = frozenset({"www.applitrack.com"})

    def board_url(self, board_token: str) -> str:
        if not TENANT.fullmatch(board_token):
            raise ValueError(f"not an AppliTrack district: {board_token!r}")
        return (
            f"https://www.applitrack.com/{board_token}/onlineapp/JobPostings/view.asp?embed=1&all=1"
        )

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        page = body.decode("utf-8", "replace")
        organisation = APPLITRACK_ORG.search(unquote(page))
        postings = []
        for ident, block in APPLITRACK_ENTRY.findall(page):
            title = APPLITRACK_TITLE.search(block)
            if not title or not text_of(title.group(1)):
                continue
            fields = {
                text_of(label): [
                    text_of(v) for v in re.findall(r"<span class=.normal.>(.*?)</span>", value)
                ]
                for label, value in APPLITRACK_FIELD.findall(block)
            }
            description = _applitrack_description(block)
            postings.append(
                RawPosting(
                    source_slug=self.slug,
                    board_token=board_token,
                    external_id=ident,
                    payload={
                        "title": text_of(title.group(1)),
                        "organisation": organisation.group(1).strip() if organisation else None,
                        "fields": fields,
                        "description": description,
                    },
                )
            )
        if not postings and "postingsList" in page:
            raise ValueError("postings could not be read")
        return postings

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        fields: dict[str, list[str]] = job["fields"]
        kinds = fields.get("Position Type") or []
        place = next(iter(fields.get("Location") or []), None)
        posted = next(iter(fields.get("Date Posted") or []), None)
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["title"]),
            company_name=job.get("organisation") or place,
            apply_url=as_url(
                f"https://www.applitrack.com/{raw.board_token}/onlineapp/default.aspx"
                f"?all=1&AppliTrackJobId={raw.external_id}&AppliTrackLayoutMode=detail"
                "&AppliTrackViewPosting=1"
            ),
            posted_at=read_date(posted, ("%m/%d/%Y",)),
            location_text=place,
            country_hint="US",
            departments=["/".join(kinds).replace("//", "/")] if kinds else [],
            description_html=job.get("description"),
        )


# CHECK-IN by perbility ---------------------------------------------------------------------

CHECKIN_PAGES = 5
CHECKIN_PAGE_SIZE = 10


def _itemprop(page: str, name: str) -> str | None:
    found = re.search(rf'<[a-z0-9]+\s[^>]*itemprop="{name}"[^>]*>', page)
    if not found:
        return None
    inner = element_at(page, found.start())
    return text_of(inner) if inner else None


class CheckInConnector(PageCrawler):
    """Career portals of CHECK-IN by perbility at ``{portal}.mein-check-in.de``. The list at
    ``/list`` is paged (``?page=n``, 10 jobs a page) and every job page carries schema.org
    microdata (title, employer, place, description). The board token is the portal's
    subdomain (``provinzial-karriereportal``)."""

    slug = "checkin"
    hosts = frozenset({"*.mein-check-in.de"})
    max_pages = 60

    def board_url(self, board_token: str) -> str:
        if not TENANT.fullmatch(board_token):
            raise ValueError(f"not a CHECK-IN portal: {board_token!r}")
        return f"https://{board_token}.mein-check-in.de/list"

    def job_urls(self, fetcher: Fetcher, board_token: str) -> list[str]:
        base = self.board_url(board_token)
        urls: list[str] = []
        for number in range(1, CHECKIN_PAGES + 1):
            html_page = listing(fetcher, f"{base}?keywords=&page={number}").decode(
                "utf-8", "replace"
            )
            found = re.findall(r'href="(/detail/[0-9a-f-]{36})"', html_page)
            fresh = [u for u in dict.fromkeys(found) if u not in urls]
            if not fresh:
                break
            urls += fresh
        origin = f"https://{board_token}.mein-check-in.de"
        return [origin + path for path in urls]

    def item_id(self, url: str, page: dict[str, Any]) -> str:
        return url.rstrip("/").rsplit("/", 1)[-1]

    def read_page(self, url: str, body: bytes) -> dict[str, Any] | None:
        page = body.decode("utf-8", "replace")
        title = _itemprop(page, "title")
        if not title:
            return None
        description = element_with(page, r'itemprop="description"')
        working = re.search(r'class="percentage">([^<]*)<', page)
        employer = re.search(r'itemprop="hiringOrganization"', page)
        place = re.search(r'itemprop="jobLocation"', page)
        return {
            "title": title,
            "posted": _itemprop(page, "datePosted"),
            "description": description,
            "employer": _itemprop(page[employer.start() :], "name") if employer else None,
            "place": _itemprop(page[place.start() :], "addressLocality") if place else None,
            "region": _itemprop(page[place.start() :], "addressRegion") if place else None,
            "working_time": working.group(1).strip() if working else None,
        }

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["title"]),
            company_name=job.get("employer"),
            apply_url=as_url(str(job["url"])),
            posted_at=read_date(job.get("posted")),
            location_text=", ".join(p for p in (job.get("place"), job.get("region")) if p) or None,
            city=job.get("place"),
            region=job.get("region"),
            country_hint="DE",
            employment_type=job.get("working_time") or None,
            description_html=job.get("description"),
        )


def _without_query(url: str) -> str:
    """A job link without the tracking parameters a listing page adds to it."""
    return url.split("?", 1)[0]


REGIONAL_CONNECTORS: list[Connector] = [
    InHireConnector(),
    SolidesConnector(),
    SeniorTalentosConnector(),
    # The Hub: a sitemap of job pages, each with JobPosting data.
    JsonLdConnector(
        "thehub", r"^/jobs/[0-9a-f]{24}$", frozenset({"thehub.io"}), multi_employer=True
    ),
    # Recrutei Empregos: the jobs of every Recrutei customer who publishes to the board.
    JsonLdConnector(
        "recrutei",
        r"^/vaga/[^/]+/\d+-",
        frozenset({"empregos.recrutei.com.br"}),
        multi_employer=True,
    ),
    # Apploi: a company's page (apply-jobs.apploi.com/jobs/{company}) lists its jobs 15 a page.
    JsonLdConnector(
        "apploi",
        r"^/job/\d+/",
        frozenset({"apply-jobs.apploi.com"}),
        page_param="page",
        listing_pages=10,
        rewrite=_without_query,
    ),
    # Cegid DigitalRecruiters career sites sit on the employer's own domain.
    JsonLdConnector("cegid", r"/annonce/\d+"),
    IntervieWebConnector(
        "intervieweb", r"^/[^/]+/jobs/[^/]+/[a-z]{2}/?$", frozenset({"inrecruiting.intervieweb.it"})
    ),
    AppliTrackConnector(),
    CheckInConnector(),
]
