"""Platforms of connector wave 2/3, found by reading the reference index
(docs/reference-sources-jobindex.md). Each reads a public, unauthenticated surface that the
platform's own sites serve to every visitor; how each was found, and its limits, is in
docs/connectors.md.

- Crelate: the RSS feed behind every candidate portal (``/portal/{org}/rss``).
- GeekJob: server-rendered ``/vacancies/{n}`` lists; every vacancy page carries JobPosting data.
- Beehire: the JSON behind every career page (``/users/getPublicCampaigns/{name}``).
- Connectoor: the connectoor.jobs board search, then each job's page (JobPosting data).
- Talos360 ATS: each career site's sitemap, then the JobPosting on every job page.
- Talent Clue: the server-rendered job list and job pages of each customer career site.
- Jobspage: each careers page's sitemap, then the JobPosting on every job page.
- Flatchr: the page data of each career site (careers.flatchr.io/fr/company/{company}).
- MCi Direct Hire: the job cards of the Job Central board (jobs.mcidirecthire.com).
- Prevue APS: each career site's job sitemap, then the JobPosting on every job page.
- OpenCATS: the server-rendered careers module of self-hosted OpenCATS installations.
- ApplicantStack: server-rendered ``/x/openings`` lists and ``/x/detail/{id}`` pages.
- Recruitis: server-rendered career sites on jobs.recruitis.io (list pages, one page per job).
- Keka: the JSON behind every Keka Hire career site (``/careers/api/jobs/default/active``).
"""

import html
import json
import re
from typing import Any

from erio_core.connectors._htmlpages import (
    DATE_FORMATS,
    PageCrawler,
    element_with,
    listing,
    read_date,
    text_of,
)
from erio_core.connectors._service import service_host
from erio_core.connectors._util import as_url, iso_datetime, join_html, salary
from erio_core.connectors.base import BoardFetch, Connector, Fetcher, FetchError
from erio_core.connectors.feed import feed_date, stable_id, xml_items
from erio_core.connectors.jsonld import JsonLdConnector, page_links
from erio_core.schemas import PartialJob, RawPosting, RemoteStatus

TOKEN = re.compile(r"[a-z0-9][a-z0-9_-]{0,62}")


# ---------------------------------------------------------------- Crelate


class CrelateConnector(Connector):
    slug = "crelate"
    hosts = frozenset({"jobs.crelate.com"})

    def board_url(self, board_token: str) -> str:
        if not TOKEN.fullmatch(board_token):
            raise ValueError(f"not a Crelate portal name: {board_token!r}")
        return f"https://jobs.crelate.com/portal/{board_token}/rss"

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        items = xml_items(body)
        # The first <title> in the document is the channel's: "{Organisation} Jobs Feed".
        channel = re.search(rb"<title>([^<]*)</title>", body)
        company = channel.group(1).decode("utf-8", "replace") if channel else ""
        company = re.sub(r"\s+Jobs Feed$", "", company).strip()
        postings = []
        for item in items:
            link = (item.get("link") or [""])[0]
            title = (item.get("title") or [""])[0]
            if not link or not title:
                continue
            postings.append(
                RawPosting(
                    source_slug=self.slug,
                    board_token=board_token,
                    external_id=link.rstrip("/").rsplit("/", 1)[-1] or stable_id(link),
                    payload={
                        "url": link,
                        "title": title,
                        "description": (item.get("description") or [""])[0] or None,
                        "location": (item.get("location") or [""])[0] or None,
                        "published": (item.get("pubdate") or [""])[0] or None,
                        "company": company or None,
                    },
                )
            )
        return postings

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["title"]).strip(),
            company_name=job.get("company"),
            apply_url=as_url(str(job["url"])),
            posted_at=feed_date(job.get("published")),
            location_text=job.get("location"),
            description_html=job.get("description"),
        )


# ---------------------------------------------------------------- GeekJob


class PathPagedJsonLdConnector(JsonLdConnector):
    """A JobPosting platform whose list is paged by path: the first page is the board
    token and page n is ``{board token}/{n}`` (GeekJob's ``/vacancies/2``)."""

    def job_pages(self, fetcher: Fetcher, board_token: str) -> list[str]:
        base = self.board_url(board_token).rstrip("/")
        links: list[str] = []
        for number in range(1, self.listing_pages + 1):
            response = fetcher.get(base if number == 1 else f"{base}/{number}")
            if response.status != 200:
                if number == 1:
                    raise FetchError("http_error", f"HTTP {response.status}", response.status)
                break
            found = page_links(response.body.decode("utf-8", "replace"), base, self.job_path)
            fresh = [link for link in found if link not in links]
            if not fresh:
                break
            links += fresh
        return links


# ---------------------------------------------------------------- Beehire

SPONTANEOUS = re.compile(r"spontan|open application|initiativ", re.IGNORECASE)
BEEHIRE_REMOTE: dict[str, RemoteStatus] = {
    "remoteWork_none": "onsite",
    "remoteWork_partial": "hybrid",
    "remoteWork_full": "remote",
}


def _translated(values: Any, language: Any) -> str | None:
    """A text kept per language index ({"0": "EN", "1": "FR"}): the posting's own language
    first, then any other that is filled in."""
    if not isinstance(values, dict):
        return None
    for key in (str(language), *values):
        text = values.get(key)
        if isinstance(text, str) and text.strip():
            return text.strip()
    return None


class BeehireConnector(Connector):
    """Beehire career pages (``app.beehire.com/career/{name}``). The page is an Angular app
    that loads its jobs from ``/users/getPublicCampaigns/{name}``, which any visitor may
    call; the token is the career page name."""

    slug = "beehire"
    hosts = frozenset({"app.beehire.com"})

    def board_url(self, board_token: str) -> str:
        if not TOKEN.fullmatch(board_token.lower()):
            raise ValueError(f"not a Beehire career page name: {board_token!r}")
        return f"https://app.beehire.com/users/getPublicCampaigns/{board_token}"

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        data = json.loads(body)
        campaigns = data["campaigns"]
        if not isinstance(campaigns, list):
            raise ValueError("Beehire answers with a list of campaigns")
        company = (data.get("user") or {}).get("company")
        postings = []
        for campaign in campaigns:
            title = _translated(campaign.get("title"), campaign.get("language"))
            if not (campaign.get("_id") and campaign.get("inviteLink") and title):
                continue
            if SPONTANEOUS.search(title):
                continue  # the standing "apply anyway" form, not a job
            postings.append(
                RawPosting(
                    source_slug=self.slug,
                    board_token=board_token,
                    external_id=str(campaign["_id"]),
                    payload={
                        "title": title,
                        "company": (
                            (campaign.get("customization") or {})
                            .get("employerBranding", {})
                            .get("name")
                            or company
                        ),
                        "description": _translated(
                            campaign.get("description"), campaign.get("language")
                        ),
                        "url": campaign["inviteLink"],
                        "location": campaign.get("location") or {},
                        "contract": (campaign.get("details") or {}).get("contract") or {},
                        "categories": [
                            c["label"]
                            for c in campaign.get("jobCategories") or []
                            if c.get("label")
                        ],
                    },
                )
            )
        return postings

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        place = job.get("location") or {}
        contract = job.get("contract") or {}
        kind = str(contract.get("type") or "")
        duration = str(contract.get("duration") or "")
        employment = (
            "Internship"
            if "internship" in kind
            else "Part-time"
            if "partTime" in duration
            else "Full-time"
            if "fullTime" in duration
            else None
        )
        city = place.get("city")
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["title"]),
            company_name=job.get("company"),
            apply_url=as_url(str(job["url"])),
            location_text=", ".join(str(p) for p in (city, place.get("country")) if p)
            or place.get("name"),
            city=city,
            workplace_type=BEEHIRE_REMOTE.get(str(contract.get("remote"))),
            employment_type=employment,
            departments=job.get("categories") or [],
            description_html=job.get("description"),
        )


# ---------------------------------------------------------------- Keka

KEKA_TOKEN = re.compile(r"([a-z0-9][a-z0-9-]{0,62})(?:/([A-Za-z0-9_-]{1,40}))?")


class KekaConnector(Connector):
    """Keka Hire career sites (``{tenant}.keka.com/careers``). Keka's own embed code and
    career page read ``/careers/api/jobs/{portal}/active``, a JSON list of every open job,
    and ``/careers/api/organization/{portal}/careerportalinfo`` for the company's name.
    robots.txt allows ``/careers``. The token is the tenant, or "tenant/portal" for a
    company with several career portals."""

    slug = "keka"
    hosts = frozenset({"*.keka.com"})

    def _parts(self, board_token: str) -> tuple[str, str]:
        match = KEKA_TOKEN.fullmatch(board_token)
        if not match:
            raise ValueError(f"not a Keka tenant (tenant or tenant/portal): {board_token!r}")
        return match[1], match[2] or "default"

    def board_url(self, board_token: str) -> str:
        tenant, portal = self._parts(board_token)
        return f"https://{tenant}.keka.com/careers/api/jobs/{portal}/active"

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        jobs = json.loads(body)
        if not isinstance(jobs, list):
            raise ValueError("Keka answers with a JSON array")
        tenant, _ = self._parts(board_token)
        return [
            RawPosting(
                source_slug=self.slug,
                board_token=board_token,
                external_id=str(job["id"]),
                payload={**job, "url": f"https://{tenant}.keka.com/careers/jobdetails/{job['id']}"},
            )
            for job in jobs
            if isinstance(job, dict) and job.get("id") is not None and job.get("title")
        ]

    def list_postings(
        self, fetcher: Fetcher, board_token: str, etag: str | None = None
    ) -> BoardFetch:
        fetched = super().list_postings(fetcher, board_token, etag)
        if not fetched.postings:
            return fetched
        tenant, portal = self._parts(board_token)
        company = None
        try:  # the company's display name; a failure here only leaves it unnamed
            info = fetcher.get(
                f"https://{tenant}.keka.com/careers/api/organization/{portal}/careerportalinfo"
            )
            if info.status == 200:
                company = json.loads(info.body).get("name")
        except (FetchError, ValueError, AttributeError):
            company = None
        if company:
            fetched = BoardFetch(
                postings=[
                    p.model_copy(update={"payload": {**p.payload, "company": company}})
                    for p in fetched.postings
                ],
                http_status=fetched.http_status,
                body=fetched.body,
                etag=fetched.etag,
                unchanged=fetched.unchanged,
                complete=fetched.complete,
            )
        return fetched

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        places = [p for p in job.get("jobLocations") or [] if isinstance(p, dict)]
        place = places[0] if places else {}
        names = [
            ", ".join(str(x) for x in (p.get("city"), p.get("state"), p.get("countryName")) if x)
            for p in places
        ]
        department = job.get("departmentName")
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["title"]).strip(),
            company_name=job.get("company"),
            apply_url=as_url(str(job["url"])),
            posted_at=iso_datetime(job.get("publishedOn")),
            location_text="; ".join(dict.fromkeys(n for n in names if n)) or None,
            city=place.get("city"),
            region=place.get("state"),
            country_hint=place.get("countryCode"),
            departments=[department] if department else [],
            description_html=job.get("description"),
        )


# ---------------------------------------------------------------- Connectoor

CONNECTOOR_BOARD = "https://www.connectoor.jobs"
#: The container id of the job board embedded on connectoor.jobs (printed in that page's
#: HTML for every visitor): it selects which jobs the widget search returns.
CONNECTOOR_CONTAINER = "595d038eddb233ab728b4568"
CONNECTOOR_PAGE_SIZE = 10


class ConnectoorConnector(JsonLdConnector):
    """Connectoor.jobs, the public job board of the German recruiting software Connectoor.
    Its embedded search (``api.connectoor.de/find``) lists the newest jobs ten at a time; each
    job's public page (``app.connectoor.de/jobview?jobid=``) carries a JobPosting. The board
    token is ``https://www.connectoor.jobs``."""

    def board_url(self, board_token: str) -> str:
        if board_token.rstrip("/") != CONNECTOOR_BOARD:
            raise ValueError(f"not the Connectoor board ({CONNECTOOR_BOARD}): {board_token!r}")
        return CONNECTOOR_BOARD

    def job_pages(self, fetcher: Fetcher, board_token: str) -> list[str]:
        self.board_url(board_token)
        urls: list[str] = []
        for number in range(self.listing_pages):
            response = fetcher.get(
                "https://api.connectoor.de/find"
                f"?s={CONNECTOOR_CONTAINER}&o={number * CONNECTOOR_PAGE_SIZE}&q="
            )
            if response.status != 200:
                if number == 0:
                    raise FetchError("http_error", f"HTTP {response.status}", response.status)
                break
            try:
                results = json.loads(response.body)["results"]
            except (ValueError, KeyError, TypeError) as error:
                raise FetchError("parse_error", f"malformed search: {error}", 200) from error
            ids = [r["id"] for r in results if isinstance(r, dict) and r.get("id")]
            if not all(re.fullmatch(r"[0-9a-f]{24}", str(i)) for i in ids):
                raise FetchError("parse_error", "unexpected job id in the search", 200)
            fresh = [f"https://app.connectoor.de/jobview?jobid={i}" for i in ids]
            fresh = [u for u in fresh if u not in urls]
            if not fresh:
                break
            urls += fresh
        return urls

    def parse(self, raw: RawPosting) -> PartialJob:
        job = super().parse(raw)
        # The pages write names with HTML entities ("Th&uuml;mmel &amp; Partner").
        return job.model_copy(
            update={
                "company_name": html.unescape(job.company_name) if job.company_name else None,
                "title": html.unescape(job.title),
            }
        )


# ---------------------------------------------------------------- Recruitis

SPAN_ITEM = re.compile(r'<span class="job-item[^"]*"[^>]*>(.*?)</span>', re.DOTALL)
LIST_PAGES = 6
LIST_PAGE_SIZE = 20


class RecruitisConnector(PageCrawler):
    """Recruitis career sites (``jobs.recruitis.io/{company}``): server-rendered lists, paged
    with ``?jobs_list_form[page]=n``, and one page per job with its title, place, contract
    and description (no structured data). The token is the company's name in the address."""

    slug = "recruitis"
    hosts = frozenset({"jobs.recruitis.io"})
    listing_pages = LIST_PAGES
    max_pages = 100

    def board_url(self, board_token: str) -> str:
        if not TOKEN.fullmatch(board_token):
            raise ValueError(f"not a Recruitis career site name: {board_token!r}")
        return f"https://jobs.recruitis.io/{board_token}"

    def job_urls(self, fetcher: Fetcher, board_token: str) -> list[str]:
        base = self.board_url(board_token)
        found: list[str] = []
        pages = 1
        for number in range(1, self.listing_pages + 1):
            url = base if number == 1 else f"{base}?jobs_list_form%5Bpage%5D={number}"
            html_text = listing(fetcher, url).decode("utf-8", "replace")
            fresh = [
                f"https://jobs.recruitis.io{path}"
                for path in dict.fromkeys(
                    re.findall(rf'href="(/{re.escape(board_token)}/\d+-[^"#?]*)"', html_text)
                )
            ]
            fresh = [u for u in fresh if u not in found]
            if not fresh:
                break
            found += fresh
            if number == 1:
                total = re.search(r"z\s+(\d+)</div>", html_text)
                pages = -(-int(total[1]) // LIST_PAGE_SIZE) if total else 1
            if number >= pages:
                break
        return found

    def item_id(self, url: str, page: dict[str, Any]) -> str:
        match = re.search(r"/(\d+)-", url)
        return match[1] if match else super().item_id(url, page)

    def read_page(self, url: str, body: bytes) -> dict[str, Any] | None:
        html_text = body.decode("utf-8", "replace")
        title = re.search(r"<h1[^>]*>(.*?)</h1>", html_text, re.DOTALL)
        if not title or not text_of(title.group(1)):
            return None
        logo = re.search(r'<img class="u-header__logo-img[^>]*\balt="([^"]*)"', html_text)
        return {
            "title": text_of(title.group(1)),
            "tags": [text_of(t) for t in SPAN_ITEM.findall(html_text)],
            "company": html.unescape(logo[1]).strip() if logo else None,
            "description": element_with(html_text, r'id="job-description"'),
        }

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        tags = [t for t in job["tags"] if t]
        # Tags in page order: place, field of work, contract, education (some may be absent).
        place = tags[0] if tags else None
        contract = next(
            (t for t in tags if re.search(r"úvazek|brigád|HPP|DPP|smlouv", t, re.I)), None
        )
        city = place.split(",")[0].strip() if place else None
        country = place.rsplit(",", 1)[-1].strip() if place and "," in place else None
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["title"]),
            company_name=job.get("company") or None,
            apply_url=as_url(str(job["url"])),
            location_text=place,
            city=city,
            country_hint=country if country and len(country) == 2 else None,
            employment_type=contract,
            description_html=job.get("description"),
        )


# ---------------------------------------------------------------- ApplicantStack

SUMMARY_ROW = re.compile(r"<th[^>]*>(.*?)</th>\s*<td[^>]*>(.*?)</td>", re.DOTALL)


class ApplicantStackConnector(PageCrawler):
    """ApplicantStack career pages (``{tenant}.applicantstack.com/x/openings``): a server-rendered
    list of the open jobs and one ``/x/detail/{id}`` page per job with a summary table (title,
    place, department) and the description. robots.txt allows both; there is no public API
    (the vendor's needs a key) and no structured data. The token is the tenant."""

    slug = "applicantstack"
    hosts = frozenset({"*.applicantstack.com"})

    def board_url(self, board_token: str) -> str:
        if not TOKEN.fullmatch(board_token):
            raise ValueError(f"not an ApplicantStack tenant: {board_token!r}")
        return f"https://{board_token}.applicantstack.com/x/openings"

    def job_urls(self, fetcher: Fetcher, board_token: str) -> list[str]:
        html_text = listing(fetcher, self.board_url(board_token)).decode("utf-8", "replace")
        found = re.findall(
            rf'href="(https://{re.escape(board_token)}\.applicantstack\.com/x/detail/[a-z0-9]+)"',
            html_text,
        )
        return list(dict.fromkeys(found))

    def item_id(self, url: str, page: dict[str, Any]) -> str:
        return url.rsplit("/", 1)[-1]

    def read_page(self, url: str, body: bytes) -> dict[str, Any] | None:
        html_text = body.decode("utf-8", "replace")
        title = re.search(r'<div id="contenttitle"[^>]*>(.*?)</div>', html_text, re.DOTALL)
        if not title or not text_of(title.group(1)):
            return None
        summary = {
            text_of(k).rstrip(":").lower(): text_of(v) for k, v in SUMMARY_ROW.findall(html_text)
        }
        logo = re.search(r'<img id="logo"[^>]*\balt="([^"]*)"', html_text)
        return {
            "title": text_of(title.group(1)),
            "summary": summary,
            "company": html.unescape(logo[1]).strip() if logo else None,
            "description": element_with(html_text, r'class="listing_description"'),
        }

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        summary: dict[str, str] = job.get("summary") or {}
        place = summary.get("location")
        department = summary.get("department")
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["title"]),
            company_name=job.get("company") or None,
            apply_url=as_url(str(job["url"])),
            posted_at=read_date(summary.get("date posted") or summary.get("posted")),
            location_text=place if place and place.upper() != "N/A" else None,
            departments=[department] if department and department.upper() != "N/A" else [],
            description_html=job.get("description"),
        )


# ---------------------------------------------------------------- OpenCATS

OPENCATS_TOKEN = re.compile(
    r"https://(?P<host>[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?)(?P<path>(?:/[A-Za-z0-9._~-]+)*)/careers/?"
    r"(?:index\.php)?(?:\?.*)?",
    re.IGNORECASE,
)
GENERAL_APPLICATION = re.compile(r"general consideration|general application", re.IGNORECASE)


class OpenCATSConnector(PageCrawler):
    """OpenCATS (the open-source applicant tracking system) installations publish a careers
    module at ``{site}/careers/``: a server-rendered list (``index.php?m=careers&p=showAll``) and
    a page per job (``p=showJob&ID=n``). Every installation runs on its owner's own domain, so
    the board token is the address of its ``careers`` folder, for example
    ``https://vectaur.com/ats/careers/``; the board is admitted because it is registered."""

    slug = "opencats"
    hosts: frozenset[str] = frozenset()
    max_pages = 100

    def _base(self, board_token: str) -> str:
        match = OPENCATS_TOKEN.fullmatch(board_token.strip())
        if not match:
            raise ValueError(
                f"not an OpenCATS careers address (https://host/.../careers/): {board_token!r}"
            )
        return f"https://{match['host'].lower()}{match['path']}/careers/"

    def board_url(self, board_token: str) -> str:
        return f"{self._base(board_token)}index.php?m=careers&p=showAll"

    def job_urls(self, fetcher: Fetcher, board_token: str) -> list[str]:
        base = self._base(board_token)
        html_text = listing(fetcher, self.board_url(board_token)).decode("utf-8", "replace")
        rows = re.findall(
            r'<a href="index\.php\?m=careers&amp;p=showJob&amp;ID=(\d+)"[^>]*>(.*?)</a>',
            html_text,
            re.DOTALL,
        )
        ids = [i for i, title in rows if not GENERAL_APPLICATION.search(text_of(title))]
        return [f"{base}index.php?m=careers&p=showJob&ID={i}" for i in dict.fromkeys(ids)]

    def item_id(self, url: str, page: dict[str, Any]) -> str:
        match = re.search(r"[?&]ID=(\d+)", url)
        return match[1] if match else super().item_id(url, page)

    def read_page(self, url: str, body: bytes) -> dict[str, Any] | None:
        html_text = body.decode("utf-8", "replace")
        # The standard template titles the page "Position Details: {title}"; some sites
        # restyle it and keep just the title in the one <h1>.
        title = re.search(r"<h1[^>]*>(.*?)</h1>", html_text, re.DOTALL)
        if not title or not text_of(title.group(1)) or "descriptive" not in html_text:
            return None
        heading = re.sub(r"^Position Details:\s*", "", text_of(title.group(1)))
        details: dict[str, str] = {}
        for key, value in re.findall(
            r'<td class="detailsHeader">(.*?)</td>\s*<td[^>]*>(.*?)</td>', html_text, re.DOTALL
        ):
            details[text_of(key).rstrip(":").lower()] = text_of(value)
        name = re.search(r"<title>\s*(.*?)\s*-\s*Careers\s*</title>", html_text, re.DOTALL)
        return {
            "title": heading,
            "details": details,
            "company": text_of(name.group(1)) if name else None,
            "description": element_with(html_text, r'id="descriptive"'),
        }

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        details: dict[str, str] = job.get("details") or {}
        place = details.get("location")
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["title"]),
            company_name=job.get("company") or None,
            apply_url=as_url(str(job["url"])),
            location_text=place or None,
            city=place.split(",")[0].strip() if place else None,
            description_html=job.get("description"),
        )


# ---------------------------------------------------------------- MCi Direct Hire

MCI_HOST = "jobs.mcidirecthire.com"
MCI_PAGES = 5


class MciDirectHireConnector(Connector):
    """Job Central (jobs.mcidirecthire.com), the public job board of MCi Direct Hire's
    recruitment software: many South African and international employers. Its job list
    is loaded page by page from ``/AvailableVacancies/JobSearch?PageNum=n``: ten cards a page,
    newest first, each with the job's title, employer, date, place, industry and the opening
    of its description, and a link to its public vacancy page. A crawl reads a few pages, so
    it is reported incomplete. The board token is ``https://jobs.mcidirecthire.com``."""

    slug = "mcidirecthire"
    hosts = frozenset({MCI_HOST})
    multi_employer = True
    max_pages = MCI_PAGES

    def board_url(self, board_token: str) -> str:
        service_host(board_token, self.hosts, "MCi Direct Hire")
        return f"https://{MCI_HOST}/AvailableVacancies/JobSearch?PageNum=1"

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        text = body.decode("utf-8", "replace")
        postings = []
        for card in text.split('<div class="card job-card">')[1:]:
            link = re.search(r"data-url=\"(https://[^\"]*CompanyPublishingId=(\d+))\"", card)
            title = re.search(r'<strong class="job-title">(.*?)</strong>', card, re.DOTALL)
            if not (link and title and text_of(title.group(1))):
                continue
            employer = re.search(
                r'<small class="font-small job-location">(.*?)</small>', card, re.DOTALL
            )
            meta = re.search(
                r'<small class="text-muted">\s*<i class="fa fa-calendar"></i>\s*([\d/]+)'
                r'(?:.*?<i class="fa fa-map-marker"></i>(.*?))?</small>',
                card,
                re.DOTALL,
            )
            industry = re.search(r"Industry:</b>(.*?)<br", card, re.DOTALL)
            teaser = re.search(
                r"Positions Available:</b>[^<]*<br />\s*<br />(.*?)</p>", card, re.DOTALL
            )
            postings.append(
                RawPosting(
                    source_slug=self.slug,
                    board_token=board_token,
                    external_id=link.group(2),
                    payload={
                        "url": link.group(1),
                        "title": text_of(title.group(1)),
                        "company": text_of(employer.group(1)) if employer else None,
                        "date": meta.group(1) if meta else None,
                        "place": text_of(meta.group(2) or "") if meta else None,
                        "industry": text_of(industry.group(1)) if industry else None,
                        "description": text_of(teaser.group(1)) if teaser else None,
                    },
                )
            )
        return postings

    def list_postings(
        self, fetcher: Fetcher, board_token: str, etag: str | None = None
    ) -> BoardFetch:
        first = self.board_url(board_token)
        postings: list[RawPosting] = []
        pages = 1
        for number in range(1, self.max_pages + 1):
            response = fetcher.get(first.replace("PageNum=1", f"PageNum={number}"))
            if response.status == 429:
                raise FetchError("rate_limited", "source rate limit", 429)
            if response.status != 200:
                if number == 1:
                    raise FetchError("http_error", f"HTTP {response.status}", response.status)
                break
            try:
                found = self.extract(response.body, board_token)
            except (ValueError, KeyError, TypeError) as error:
                raise FetchError("parse_error", f"malformed page: {error}", 200) from error
            if number == 1:
                total = re.search(r"totalPages:\s*(\d+)", response.body.decode("utf-8", "replace"))
                pages = int(total[1]) if total else 1
            fresh = [p for p in found if p.external_id not in {q.external_id for q in postings}]
            if not fresh:
                break
            postings += fresh
            if number >= pages:
                break
        if not postings:
            raise FetchError("parse_error", "the board lists no jobs", 200)
        return BoardFetch(
            postings=postings, http_status=200, body=b"", complete=pages <= self.max_pages
        )

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        description = job.get("description")
        place = job.get("place") or None
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["title"]),
            company_name=job.get("company") or None,
            apply_url=as_url(str(job["url"])),
            posted_at=read_date(job.get("date"), (*DATE_FORMATS, "%Y/%m/%d")),
            location_text=place,
            departments=[job["industry"]] if job.get("industry") else [],
            description_html=f"<p>{html.escape(description)}</p>" if description else None,
        )


# ---------------------------------------------------------------- Flatchr

NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)
FLATCHR_REMOTE: dict[str, RemoteStatus] = {"full": "remote", "partial": "hybrid", "none": "onsite"}
FLATCHR_PERIODS = {"y": "year", "m": "month", "h": "hour"}


class FlatchrConnector(Connector):
    """Flatchr career sites (``careers.flatchr.io/fr/company/{company}``): a Next.js page whose
    embedded page data (``__NEXT_DATA__``) holds every published vacancy with its full
    description, place and contract, so one request reads a whole company. robots.txt turns
    away only a few named bots. The token is the company's name in the address."""

    slug = "flatchr"
    hosts = frozenset({"careers.flatchr.io"})

    def board_url(self, board_token: str) -> str:
        if not TOKEN.fullmatch(board_token):
            raise ValueError(f"not a Flatchr company name: {board_token!r}")
        return f"https://careers.flatchr.io/fr/company/{board_token}"

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        found = NEXT_DATA.search(body.decode("utf-8", "replace"))
        if not found:
            raise ValueError("the page carries no embedded job data")
        items = json.loads(found.group(1))["props"]["data"]["items"]
        if not isinstance(items, list):
            raise ValueError("Flatchr's job list is not a list")
        postings = []
        for item in items:
            vacancy = item.get("vacancy") if isinstance(item, dict) else None
            if not (vacancy and vacancy.get("slug") and vacancy.get("title")):
                continue
            if item.get("status") not in (None, "published"):
                continue
            address = vacancy.get("address") or {}
            postings.append(
                RawPosting(
                    source_slug=self.slug,
                    board_token=board_token,
                    external_id=str(vacancy["slug"]),
                    payload={
                        "title": vacancy["title"],
                        "url": (
                            f"https://careers.flatchr.io/fr/company/{board_token}"
                            f"/vacancy/{vacancy['slug']}/"
                        ),
                        "company": (vacancy.get("company") or {}).get("name"),
                        "description": join_html(
                            vacancy.get("description"),
                            vacancy.get("mission"),
                            vacancy.get("profile"),
                        ),
                        "contract": vacancy.get("contract_type"),
                        "created": vacancy.get("created_at"),
                        "remote": vacancy.get("remote"),
                        "salary": [vacancy.get("salary"), vacancy.get("salary_max")],
                        "currency": vacancy.get("currency"),
                        "period": vacancy.get("mensuality"),
                        "city": address.get("locality"),
                        "region": address.get("administrative_area_level_1"),
                        "country": address.get("country"),
                    },
                )
            )
        return postings

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        low, high = job.get("salary") or [None, None]
        place = ", ".join(str(job[k]) for k in ("city", "region", "country") if job.get(k))
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["title"]).strip(),
            company_name=job.get("company"),
            apply_url=as_url(str(job["url"])),
            posted_at=iso_datetime(job.get("created")),
            location_text=place or None,
            city=job.get("city"),
            region=job.get("region"),
            workplace_type=FLATCHR_REMOTE.get(str(job.get("remote"))),
            employment_type=job.get("contract"),
            salary=salary(
                low, high, job.get("currency"), FLATCHR_PERIODS.get(str(job.get("period")))
            ),
            description_html=job.get("description"),
        )


# ---------------------------------------------------------------- Talent Clue

TALENTCLUE_TOKEN = re.compile(r"([a-z0-9][a-z0-9-]{0,62})/(\d{4,12})")
SUMMARY_ITEM = re.compile(
    r'<strong class="job-summary__text--bold">(.*?)</strong>\s*([^<]*)', re.DOTALL
)
STANDING_FORM = re.compile(
    r"sense que hi hagi cap oferta|sin oferta|sin que haya|candidatura espont|general application",
    re.IGNORECASE,
)


class TalentClueConnector(PageCrawler):
    """Talent Clue career sites (``{tenant}.talentclue.com``): the company's job list at
    ``/es/company/{id}/offers/menu/modal`` is a server-rendered table, and each job has a
    page (``/es/node/{n}/{template}``) with a summary (place, contract, hours, sector) and its
    description. robots.txt allows both (Crawl-delay 10, which the fetcher honours). The board
    token is "tenant/companyId", read from the career site's own list address."""

    slug = "talentclue"
    hosts = frozenset({"*.talentclue.com"})
    max_pages = 60

    def _parts(self, board_token: str) -> tuple[str, str]:
        match = TALENTCLUE_TOKEN.fullmatch(board_token)
        if not match:
            raise ValueError(f"not a Talent Clue token (tenant/companyId): {board_token!r}")
        return match[1], match[2]

    def board_url(self, board_token: str) -> str:
        tenant, company = self._parts(board_token)
        return f"https://{tenant}.talentclue.com/es/company/{company}/offers/menu/modal"

    def job_urls(self, fetcher: Fetcher, board_token: str) -> list[str]:
        tenant, _ = self._parts(board_token)
        html_text = listing(fetcher, self.board_url(board_token)).decode("utf-8", "replace")
        rows = re.findall(
            rf'<a href="https://{re.escape(tenant)}\.talentclue\.com/[a-z]{{2}}/node/(\d+)/(\d+)'
            r'/modal(?:browser)?[^"]*"[^>]*>(.*?)</a>',
            html_text,
            re.DOTALL,
        )
        wanted = [(n, t) for n, t, title in rows if not STANDING_FORM.search(text_of(title))]
        return [
            f"https://{tenant}.talentclue.com/es/node/{n}/{t}" for n, t in dict.fromkeys(wanted)
        ]

    def item_id(self, url: str, page: dict[str, Any]) -> str:
        match = re.search(r"/node/(\d+)/", url)
        return match[1] if match else super().item_id(url, page)

    def read_page(self, url: str, body: bytes) -> dict[str, Any] | None:
        html_text = body.decode("utf-8", "replace")
        title = re.search(
            r'<h1 class="job-page__header-title[^"]*"[^>]*>(.*?)</h1>', html_text, re.DOTALL
        )
        if not title or not text_of(title.group(1)):
            return None
        summary = [(text_of(k).rstrip(":"), text_of(v)) for k, v in SUMMARY_ITEM.findall(html_text)]
        company = re.search(r'<h2 class="job-description__title">(.*?)</h2>', html_text, re.DOTALL)
        return {
            "title": text_of(title.group(1)),
            "summary": summary,
            "company": text_of(company.group(1)) if company else None,
            "description": element_with(html_text, r'class="job-description"'),
        }

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        # The labels are in the career site's language; the order (place, contract, hours, ...)
        # and the "City (Country)" shape of the place are the same in all of them.
        values = [v for _, v in job.get("summary") or []]
        place = next((v for k, v in job.get("summary") or [] if re.match(r"Ubica", k)), None)
        city = re.sub(r"\s*\(.*\)$", "", place) if place else None
        country = re.search(r"\((.*)\)$", place) if place else None
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["title"]),
            company_name=job.get("company") or None,
            apply_url=as_url(str(job["url"])),
            location_text=place or None,
            city=city or None,
            country_hint=country[1] if country else None,
            employment_type=next(
                (
                    v
                    for k, v in job.get("summary") or []
                    if re.match(r"Tipo de Contrato|Tipus de Contracte|Contract", k)
                ),
                None,
            ),
            departments=[],
            description_html=job.get("description") if values or job.get("description") else None,
        )


WAVE2_3_CONNECTORS: list[Connector] = [
    CrelateConnector(),
    TalentClueConnector(),
    # Jobspage: each customer's careers page ({company}.jobspage.co) serves a sitemap
    # (token) of its job pages (an 8-character code and a slug, or a UUID), and every job
    # page carries a JobPosting.
    JsonLdConnector(
        "jobspage",
        r"^/(?:[A-Za-z0-9_-]{8}-[^/]+|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$",
        frozenset({"*.jobspage.co"}),
    ),
    FlatchrConnector(),
    MciDirectHireConnector(),
    # Prevue APS: each customer's career site ({tenant}.prevueaps.com) serves a sitemap
    # (token) of its job pages, and every job page carries a JobPosting.
    JsonLdConnector("prevueaps", r"^/jobs/\d+\.html$", frozenset({"*.prevueaps.com"})),
    OpenCATSConnector(),
    ApplicantStackConnector(),
    RecruitisConnector(),
    # Talos360 ATS: each customer's career site ({tenant}.talosats-careers.com) serves a
    # sitemap of its job pages (token), and every job page carries a JobPosting.
    JsonLdConnector("talos360", r"^/job/\d+$", frozenset({"*.talosats-careers.com"})),
    ConnectoorConnector(
        "connectoor",
        r"^/jobview$",
        frozenset({"www.connectoor.jobs", "api.connectoor.de", "app.connectoor.de"}),
        multi_employer=True,
        listing_pages=12,
        max_pages=120,
    ),
    BeehireConnector(),
    KekaConnector(),
    PathPagedJsonLdConnector(
        "geekjob",
        r"^/vacancy/[0-9a-f]{24}$",
        frozenset({"geekjob.ru"}),
        multi_employer=True,
        listing_pages=6,
        max_pages=120,
    ),
]
