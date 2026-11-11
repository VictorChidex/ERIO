"""Platforms found by reading the reference site jobindex.space, second wave, batch 2.

Each reads a public, anonymous surface of the platform; how each was found, and its
limits, is in docs/connectors.md.

- AcademicTransfer: ``sitemap-vacancies.xml`` lists every vacancy page, and each page
  carries a schema.org JobPosting. robots.txt allows crawlers (crawl-delay 10 s, which
  the polite fetcher honours), so a crawl reads the newest 100 pages.
- HRMOS: the company's server-rendered ``/pages/{company}/jobs`` list (100 per page, paged
  with ``?page=n``) links each job page, and every job page carries a JobPosting.
- Loxo: the hosted careers page ``app.loxo.co/{agency}`` (server-rendered job list) and each
  job page on ``{agency}.app.loxo.co`` (description as JSON in the page). robots.txt allows all.
- Gestmax / Kioskemploi: the career site's server-rendered ``/search`` list (paged) and
  each job page's labelled fields and text (no structured data); no robots.txt is served.
- Taleez: ``sitemap-job.xml`` lists every public job page ``/apply/{id}`` (newest last), each
  with a JobPosting; robots.txt closes only /api/, /feeds/ and similar, so a crawl reads the
  newest 100 pages.
- speedrun talent network: the ``/jobs.rss`` feed of its 100 newest roles, and each role's
  page for the JobPosting (the sitemap holds decoy pages that robots.txt closes).
- Djinni: the job list ``/jobs/?page=n`` (JobPosting data with the description inline for
  every job); robots.txt only closes /jobs2, /q, /developers and /free-jobs.
"""

import html
import json
import re
from typing import Any
from urllib.parse import urljoin, urlsplit

from erio_core.connectors._service import plain
from erio_core.connectors._util import as_url, host_country
from erio_core.connectors.base import BoardFetch, Connector, Fetcher, FetchError
from erio_core.connectors.feed import stable_id
from erio_core.connectors.jsonld import JsonLdConnector, job_postings
from erio_core.schemas import PartialJob, RawPosting

SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")


# ------------------------------------------------------------------- Loxo

LOXO_DESCRIPTION = re.compile(
    r'id="public-job-description-json">\s*(\{.*?\})\s*</script>', re.DOTALL
)
LOXO_TITLE = re.compile(r"<title>(.*?)</title>", re.DOTALL)
TAGS = re.compile(r"<[^>]+>")


class LoxoConnector(Connector):
    """Loxo's hosted careers page ``app.loxo.co/{agency}`` lists the live jobs the agency
    publishes (server-rendered); each job page on ``{agency}.app.loxo.co`` carries the
    description as JSON and the agency's name in its title."""

    slug = "loxo"
    hosts = frozenset({"app.loxo.co", "*.app.loxo.co"})
    max_details = 60

    def board_url(self, board_token: str) -> str:
        if not SLUG.fullmatch(board_token):
            raise ValueError(f"not a Loxo careers page name: {board_token!r}")
        return f"https://app.loxo.co/{board_token}"

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        text = body.decode("utf-8", "replace")
        postings = []
        for card in text.split("<div class='jobs-listing-card'>")[1:]:
            link = re.search(r"class='job-title'.*?href=\"(/job/[^\"]+)\"\s*>(.*?)</a>", card, re.S)
            if not link:
                continue
            kind = re.search(r"class='job-type'[^>]*>(.*?)</div>", card, re.S)
            place = re.search(r"class='job-location'[^>]*>(.*?)</div>", card, re.S)
            ident = link.group(1).removeprefix("/job/")
            postings.append(
                RawPosting(
                    source_slug=self.slug,
                    board_token=board_token,
                    external_id=ident,
                    payload={
                        "title": plain(link.group(2)),
                        "type": plain(TAGS.sub(" ", kind.group(1))) if kind else None,
                        "location": plain(
                            re.sub(r"<i [^>]*>.*?</i>", "", place.group(1), flags=re.S)
                            if place
                            else None
                        ),
                    },
                )
            )
        if not postings and "jobs-listing" not in text:
            raise ValueError("not a Loxo careers page")
        return postings

    def list_postings(
        self, fetcher: Fetcher, board_token: str, etag: str | None = None
    ) -> BoardFetch:
        listed = super().list_postings(fetcher, board_token, etag)
        if listed.unchanged:
            return listed
        postings = []
        unread = 0
        for raw in listed.postings[: self.max_details]:
            url = f"https://{board_token}.app.loxo.co/job/{raw.external_id}"
            payload: dict[str, Any] = dict(raw.payload) | {"url": url}
            try:
                page = fetcher.get(url)
            except FetchError:
                page = None
            if page is not None and page.status == 200:
                text = page.body.decode("utf-8", "replace")
                found = LOXO_DESCRIPTION.search(text)
                title = LOXO_TITLE.search(text)
                if found:
                    try:
                        payload["description"] = json.loads(found.group(1)).get("description")
                    except ValueError:
                        unread += 1
                if title and " | " in title.group(1):
                    payload["company"] = plain(title.group(1).rsplit(" | ", 1)[1])
            elif page is None or page.status not in (404, 410):
                unread += 1
            postings.append(raw.model_copy(update={"payload": payload}))
        return BoardFetch(
            postings=postings,
            http_status=listed.http_status,
            body=listed.body,
            etag=listed.etag,
            complete=len(listed.postings) <= self.max_details and unread == 0,
        )

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        place = job.get("location")
        parts = [p.strip() for p in str(place).split(",")] if place else []
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["title"]).strip(),
            company_name=job.get("company"),
            apply_url=as_url(job.get("url") or f"https://app.loxo.co/{raw.board_token}"),
            location_text=place,
            city=parts[0] if len(parts) > 1 else None,
            country_hint=parts[-1] if len(parts) > 2 else None,
            employment_type=job.get("type"),
            description_html=job.get("description") or None,
        )


# ------------------------------------------------- Gestmax / Kioskemploi

GESTMAX_LINK = re.compile(r'href="((?:https://[a-z0-9.-]+)?/\d+/\d+/[a-z0-9-]+)"')
GESTMAX_ITEM = re.compile(
    r'class="item-value item-value-([a-z0-9_]+)">\s*(.*?)\s*</span>', re.DOTALL | re.IGNORECASE
)
GESTMAX_TITLE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.DOTALL)
GESTMAX_TEXT = re.compile(r'class="vacancy-text">(.*?)<div class="apply">', re.DOTALL)
GESTMAX_LOCATION = ("loc", "lieu", "ville", "site", "region", "dept", "departement")
GESTMAX_KIND = ("contrat", "nature", "type")


def _gestmax_origin(board_token: str) -> str:
    if board_token.startswith("https://"):
        parts = urlsplit(board_token)
        if not parts.hostname or parts.path not in ("", "/") or parts.query:
            raise ValueError(f"not a Gestmax career site address: {board_token!r}")
        return f"https://{parts.hostname}"
    if not SLUG.fullmatch(board_token):
        raise ValueError(f"not a Gestmax career site name: {board_token!r}")
    return f"https://{board_token}.gestmax.fr"


class GestmaxConnector(Connector):
    """Gestmax (Kioskemploi) career sites: the server-rendered ``/search`` list (paged at
    ``/search/index/page/n``) links every job page ``/{id}/{n}/{slug}``, and each job page
    prints its fields as labelled items (whose set differs by customer) and its text.
    The token is the site's name (``{name}.gestmax.fr``) or its https address."""

    slug = "gestmax"
    hosts = frozenset({"*.gestmax.fr"})
    max_list_pages = 10
    max_details = 100

    def board_url(self, board_token: str) -> str:
        return f"{_gestmax_origin(board_token)}/search"

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        """The posting on one job page (the board token is that page's address)."""
        text = body.decode("utf-8", "replace")
        canonical = re.search(r'rel="canonical" href="([^"]+)"', text)
        raw = self._job_page(text, canonical.group(1) if canonical else board_token, board_token)
        return [raw] if raw else []

    def _job_page(self, text: str, url: str, board_token: str) -> RawPosting | None:
        title = GESTMAX_TITLE.search(text)
        if not title or not plain(TAGS.sub(" ", title.group(1))):
            return None
        items = {k: plain(TAGS.sub(" ", v)) for k, v in GESTMAX_ITEM.findall(text)}
        body = GESTMAX_TEXT.search(text)
        parts = urlsplit(url).path.strip("/").split("/")
        return RawPosting(
            source_slug=self.slug,
            board_token=board_token,
            external_id=f"{parts[0]}-{parts[1]}",
            payload={
                "url": url,
                "title": plain(TAGS.sub(" ", title.group(1))),
                "items": items,
                "description": body.group(1).strip() if body else None,
            },
        )

    def list_postings(
        self, fetcher: Fetcher, board_token: str, etag: str | None = None
    ) -> BoardFetch:
        origin = _gestmax_origin(board_token)
        links: list[str] = []
        for number in range(1, self.max_list_pages + 1):
            url = f"{origin}/search" if number == 1 else f"{origin}/search/index/page/{number}"
            response = fetcher.get(url)
            if response.status == 429:
                raise FetchError("rate_limited", "source rate limit", 429)
            if response.status != 200:
                if number == 1:
                    raise FetchError("http_error", f"HTTP {response.status}", response.status)
                break
            found = [
                urljoin(origin, href)
                for href in GESTMAX_LINK.findall(response.body.decode("utf-8", "replace"))
            ]
            fresh = [u for u in dict.fromkeys(found) if u not in links]
            if not fresh:
                break
            links += fresh
        postings: list[RawPosting] = []
        unread = 0
        for url in links[: self.max_details]:
            try:
                page = fetcher.get(url)
            except FetchError:
                unread += 1
                continue
            if page.status == 200:
                raw = self._job_page(page.body.decode("utf-8", "replace"), url, board_token)
                if raw:
                    postings.append(raw)
            elif page.status not in (404, 410):
                unread += 1
        if links and not postings:
            raise FetchError("parse_error", "job pages carry no title", 200)
        return BoardFetch(
            postings=postings,
            http_status=200,
            body=b"",
            complete=len(links) <= self.max_details and unread == 0,
        )

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        items: dict[str, str | None] = job.get("items") or {}

        def pick(words: tuple[str, ...]) -> str | None:
            # Words in order of preference: "localisation" before "site d'affectation".
            return next((v for w in words for k, v in items.items() if v and w in k), None)

        place = pick(GESTMAX_LOCATION)
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["title"]),
            apply_url=as_url(str(job["url"])),
            location_text=place,
            country_hint=host_country(str(job["url"])) if place else None,
            employment_type=pick(GESTMAX_KIND),
            description_html=job.get("description") or None,
        )


# ------------------------------------------------------------------ Djinni


class DjinniConnector(JsonLdConnector):
    """Djinni's job list ``/jobs/?page=n`` carries a full JobPosting (description included)
    for each of its 15 jobs per page, so a crawl reads list pages, not job pages."""

    def __init__(self) -> None:
        super().__init__(
            "djinni",
            r"^/jobs/\d+-",
            frozenset({"djinni.co"}),
            multi_employer=True,
            listing_pages=20,
        )

    def board_url(self, board_token: str) -> str:
        if urlsplit(board_token).hostname != "djinni.co" or not board_token.startswith("https://"):
            raise ValueError(f"not a Djinni job list address: {board_token!r}")
        return board_token

    def list_postings(
        self, fetcher: Fetcher, board_token: str, etag: str | None = None
    ) -> BoardFetch:
        postings: list[RawPosting] = []
        seen: set[str] = set()
        exhausted = False
        base = self.board_url(board_token)
        for number in range(1, self.listing_pages + 1):
            response = fetcher.get(base if number == 1 else f"{base}?page={number}")
            if response.status == 429:
                raise FetchError("rate_limited", "source rate limit", 429)
            if response.status != 200:
                if number == 1:
                    raise FetchError("http_error", f"HTTP {response.status}", response.status)
                exhausted = True
                break
            found = [
                p
                for p in job_postings(response.body.decode("utf-8", "replace"))
                if p.get("title") and p.get("url")
            ]
            fresh = [p for p in found if str(p["url"]) not in seen]
            if not fresh:
                exhausted = True
                break
            for posting in fresh:
                url = str(posting["url"])
                seen.add(url)
                postings.append(
                    RawPosting(
                        source_slug=self.slug,
                        board_token=board_token,
                        external_id=stable_id(url),
                        payload={"page_url": url, "posting": posting},
                    )
                )
        return BoardFetch(postings=postings, http_status=200, body=b"", complete=exhausted)

    def parse(self, raw: RawPosting) -> PartialJob:
        job = super().parse(raw)
        text = job.description_html
        if text and "<" not in text:  # plain text with line breaks
            paragraphs = [html.escape(p.strip()) for p in text.split("\n\n") if p.strip()]
            text = "".join(f"<p>{p.replace(chr(10), '<br>')}</p>" for p in paragraphs)
            job = job.model_copy(update={"description_html": text})
        return job


# ----------------------------------------------------- speedrun talent network


class SpeedrunConnector(JsonLdConnector):
    """The speedrun talent network publishes ``/jobs.rss``, its 100 newest open roles, and
    each role's page carries a JobPosting. (Its sitemap also lists decoy pages that robots.txt
    marks off limits; the feed has none.)"""

    LINK = re.compile(r"<link>(https://speedrun-talent-network\.com/jobs/[^<]+)</link>")

    def __init__(self) -> None:
        super().__init__(
            "speedrun",
            r"^/jobs/[a-z0-9-]+$",
            frozenset({"speedrun-talent-network.com"}),
            max_pages=100,
            multi_employer=True,
        )

    def job_pages(self, fetcher: Fetcher, board_token: str) -> list[str]:
        response = fetcher.get(self.board_url(board_token))
        if response.status != 200:
            raise FetchError("http_error", f"HTTP {response.status}", response.status)
        found = self.LINK.findall(response.body.decode("utf-8", "replace"))
        return list(dict.fromkeys(u for u in found if "-ad00000" not in u))


WAVE2_2_CONNECTORS: list[Connector] = [
    JsonLdConnector(
        "academictransfer",
        r"^/(en|nl)/jobs/\d+/",
        frozenset({"www.academictransfer.com"}),
        max_pages=100,
        multi_employer=True,
        newest_first=True,
    ),
    JsonLdConnector(
        "hrmos",
        r"^/pages/[^/]+/jobs/[^/]+$",
        frozenset({"hrmos.co"}),
        page_param="page",
        listing_pages=5,
    ),
    JsonLdConnector(
        "taleez",
        r"^/apply/[a-z0-9-]+$",
        frozenset({"taleez.com"}),
        max_pages=100,
        multi_employer=True,
        newest_first=True,
    ),
    SpeedrunConnector(),
    LoxoConnector(),
    GestmaxConnector(),
    DjinniConnector(),
]
