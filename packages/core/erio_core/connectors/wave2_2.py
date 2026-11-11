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
"""

import json
import re
from typing import Any

from erio_core.connectors._service import plain
from erio_core.connectors._util import as_url
from erio_core.connectors.base import BoardFetch, Connector, Fetcher, FetchError
from erio_core.connectors.jsonld import JsonLdConnector
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
    description as JSON and the agency's name in its title. """

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
    LoxoConnector(),
]
