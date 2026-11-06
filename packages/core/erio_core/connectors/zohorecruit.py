"""Zoho Recruit career sites: ``/jobs/Careers`` embeds every published job.

The page carries all of a board's jobs, descriptions included, as JSON in a
hidden ``<input id="jobs">``, so one request reads a board (a page of one to
two megabytes). The board token is the subdomain on zohorecruit.com
(``unrl``) or the https address of a board on another Zoho domain or on the
employer's own (``https://careers.zohocorp.com``). General applications
("submit your resume") are not jobs and are left out.
"""

import html
import json
import re

from erio_core.connectors._htmlpages import read_date
from erio_core.connectors._paged import base_url
from erio_core.connectors._util import as_url
from erio_core.connectors.base import Connector, FetchError
from erio_core.schemas import PartialJob, RawPosting

SUBDOMAIN = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
JOBS_INPUT = re.compile(r'<input\b[^>]*\bid="jobs"[^>]*>', re.IGNORECASE)
VALUE = re.compile(r'\bvalue="([^"]*)"')
GENERAL = re.compile(
    r"^(general|open|spontaneous) application|^submit your (resume|cv)|^talent (pool|network)",
    re.IGNORECASE,
)


def board_base(board_token: str) -> str:
    if SUBDOMAIN.fullmatch(board_token):
        return f"https://{board_token}.zohorecruit.com"
    return base_url(board_token)


class ZohoRecruitConnector(Connector):
    slug = "zohorecruit"
    hosts = frozenset(
        {"*.zohorecruit.com", "*.zohorecruit.eu", "*.zohorecruit.in", "*.zohorecruit.com.au"}
    )

    def board_url(self, board_token: str) -> str:
        return f"{board_base(board_token)}/jobs/Careers"

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        page = body.decode("utf-8", "replace")
        tag = JOBS_INPUT.search(page)
        value = VALUE.search(tag.group(0)) if tag else None
        if not value:
            raise ValueError("the page has no embedded jobs")
        try:
            jobs = json.loads(html.unescape(value.group(1)))
        except json.JSONDecodeError as error:
            raise FetchError("parse_error", f"malformed jobs: {error}", 200) from error
        base = board_base(board_token)
        return [
            RawPosting(
                source_slug=self.slug,
                board_token=board_token,
                external_id=str(job["id"]),
                payload={**job, "base": base},
            )
            for job in jobs
            if job.get("Posting_Title")
            and job.get("Publish", True)
            and not job.get("Is_Locked")
            and not GENERAL.search(str(job["Posting_Title"]).strip())
        ]

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        title = str(job.get("Posting_Title") or job["Job_Opening_Name"]).strip()
        slug = re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-")
        city, state = job.get("City"), job.get("State")
        country = job.get("Country") or job.get("Country1")
        remote = bool(job.get("Remote_Job"))
        place = ", ".join(dict.fromkeys(str(p) for p in (city, state, country) if p))
        industry = job.get("Industry")
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=title,
            apply_url=as_url(f"{job['base']}/jobs/Careers/{raw.external_id}/{slug}"),
            posted_at=read_date(job.get("Date_Opened")),
            location_text=place or ("Remote" if remote else None),
            city=city,
            region=state,
            country_hint=country,
            workplace_type="remote" if remote else None,
            employment_type=job.get("Job_Type"),
            departments=[industry] if industry else [],
            description_html=job.get("Job_Description"),
        )
