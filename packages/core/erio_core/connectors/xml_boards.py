"""Platforms that publish their jobs as XML feeds, each with its own fields:

- HiringThing  https://{company}.hiringthing.com/api/rss.xml
- JazzHR       https://app.jazz.co/feeds/export/jobs/{company}
- PageUp       https://careers.pageuppeople.com/{instance}/cw/{locale}/rss
- Madgex       https://{board}/jobsrss/?Page={n}           (20 jobs a page)
- SmartJobBoard https://{board}/rss/                        (the latest 50 jobs)
- JobBoard.io  https://{board}/jobs.rss

Job boards (Madgex, SmartJobBoard, JobBoard.io) are registered by their own
address: the board token is ``https://{board}``. The feeds that list only a
window of jobs report an incomplete fetch, so a job leaving the window is
never taken as the job closing.
"""

import html
import re
from typing import Any

from erio_core.connectors._paged import PagedJsonConnector, base_url
from erio_core.connectors._util import as_url
from erio_core.connectors.base import BoardFetch, Fetcher
from erio_core.connectors.feed import feed_date, xml_items
from erio_core.schemas import PartialJob, RawPosting

SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")


class _XmlConnector(PagedJsonConnector):
    """A feed read into {"items": [...], "total": n} so the paged base can walk it."""

    tags: tuple[str, ...] = ("item",)

    def decode(self, body: bytes) -> Any:
        return {"items": xml_items(body, self.tags), "total": _total(body)}

    def items(self, data: Any) -> list[dict[str, Any]]:
        return list(data["items"])


def _total(body: bytes) -> int:
    match = re.search(rb"<(?:\w+:)?totalResults>\s*(\d+)\s*<", body)
    return int(match.group(1)) if match else 0


def first(job: dict[str, Any], name: str) -> str | None:
    texts = job.get(name) or []
    return next((t for t in texts if t), None)


def longest(job: dict[str, Any], name: str) -> str | None:
    texts = job.get(name) or []
    return max(texts, key=len) if texts and max(texts, key=len) else None


class HiringThingConnector(_XmlConnector):
    slug = "hiringthing"
    hosts = frozenset({"*.hiringthing.com"})

    def list_url(self, board_token: str, page: int) -> str:
        if not SLUG.fullmatch(board_token):
            raise ValueError(f"not a HiringThing company subdomain: {board_token!r}")
        return f"https://{board_token}.hiringthing.com/api/rss.xml"

    def item_id(self, item: dict[str, Any]) -> str:
        match = re.search(r"/job/(\d+)", first(item, "link") or "")
        if not match:
            raise ValueError("a HiringThing item without a job link")
        return match.group(1)

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(first(job, "title")).strip(),
            apply_url=as_url(str(first(job, "link"))),
            location_text=first(job, "location"),
            departments=[c] if (c := first(job, "category")) else [],
            description_html=longest(job, "description"),
        )


class JazzHRConnector(_XmlConnector):
    slug = "jazzhr"
    hosts = frozenset({"app.jazz.co"})
    tags = ("job",)

    def list_url(self, board_token: str, page: int) -> str:
        if not SLUG.fullmatch(board_token):
            raise ValueError(f"not a JazzHR company name: {board_token!r}")
        return f"https://app.jazz.co/feeds/export/jobs/{board_token}"

    def item_id(self, item: dict[str, Any]) -> str:
        return str(first(item, "id"))

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        parts = [first(job, k) for k in ("city", "state", "country")]
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(first(job, "title")).strip(),
            apply_url=as_url(str(first(job, "url"))),
            location_text=", ".join(p for p in parts if p) or None,
            city=first(job, "city"),
            region=first(job, "state"),
            country_hint=first(job, "country"),
            employment_type=first(job, "type"),
            departments=[d] if (d := first(job, "department")) else [],
            description_html=first(job, "description"),
        )


class PageUpConnector(_XmlConnector):
    """The token is "{instance}/{locale}", for example ``513/en`` or ``782/en-us``."""

    slug = "pageup"
    hosts = frozenset({"careers.pageuppeople.com"})

    def list_url(self, board_token: str, page: int) -> str:
        match = re.fullmatch(r"(\d{1,8})/([a-z]{2}(?:-[a-z]{2})?)", board_token)
        if not match:
            raise ValueError(f"not a PageUp token (instance/locale): {board_token!r}")
        return f"https://careers.pageuppeople.com/{match[1]}/cw/{match[2]}/rss"

    def item_id(self, item: dict[str, Any]) -> str:
        return str(first(item, "refNo") or first(item, "guid"))

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        place = (first(job, "location") or "").split("|")[-1].strip()
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(first(job, "title")).strip(),
            apply_url=as_url(str(first(job, "link"))),
            posted_at=feed_date(first(job, "updated") or first(job, "pubDate")),
            location_text=place or None,
            employment_type=first(job, "workType"),
            departments=[d] if (d := (first(job, "category") or "").split("|")[-1].strip()) else [],
            description_html=longest(job, "description"),
        )


class MadgexConnector(_XmlConnector):
    """Wiley Madgex boards. The feed's descriptions are short: a title line, and
    the place as the last line. Token: ``https://{board}``."""

    slug = "madgex"
    hosts = frozenset()
    page_size = 20

    def list_url(self, board_token: str, page: int) -> str:
        return f"{base_url(board_token)}/jobsrss/?Page={page}"

    def has_more(self, data: Any, items: list[dict[str, Any]], page: int) -> bool:
        return int(data.get("total") or 0) > page * self.page_size

    def item_id(self, item: dict[str, Any]) -> str:
        match = re.search(r"/job/(\d+)", first(item, "link") or "")
        if not match:
            raise ValueError("a Madgex item without a job link")
        return match.group(1)

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        text = first(job, "description") or ""
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(first(job, "title")).strip(),
            apply_url=as_url(str(first(job, "link"))),
            posted_at=feed_date(first(job, "pubDate")),
            location_text=lines[-1] if len(lines) > 1 else None,
            description_html="".join(f"<p>{html.escape(line)}</p>" for line in lines) or None,
        )


class SmartJobBoardConnector(_XmlConnector):
    """SmartJobBoard boards. Each description starts with the place and the
    employer, then the job as escaped HTML. Token: ``https://{board}``."""

    slug = "smartjobboard"
    hosts = frozenset()

    def list_url(self, board_token: str, page: int) -> str:
        return f"{base_url(board_token)}/rss/"

    def item_id(self, item: dict[str, Any]) -> str:
        match = re.search(r"/job/(\d+)", first(item, "link") or "")
        if not match:
            raise ValueError("a SmartJobBoard item without a job link")
        return match.group(1)

    def list_postings(
        self, fetcher: Fetcher, board_token: str, etag: str | None = None
    ) -> BoardFetch:
        fetched = super().list_postings(fetcher, board_token, etag)
        # The feed holds only the latest 50 jobs: older ones are not gone.
        return BoardFetch(fetched.postings, fetched.http_status, fetched.body, complete=False)

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        lines = (first(job, "description") or "").strip().splitlines()
        place = lines[0].strip() if lines else ""
        body = html.unescape("\n".join(lines[2:])) if len(lines) > 2 else ""
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(first(job, "title")).strip(),
            company_name=first(job, "creator") or (lines[1].strip() if len(lines) > 1 else None),
            apply_url=as_url(str(first(job, "link"))),
            posted_at=feed_date(first(job, "pubDate")),
            location_text=place or None,
            description_html=body or None,
        )


class JobBoardIoConnector(_XmlConnector):
    """JobBoard.io boards: the feed has the job's title ("Role at Company") and a
    short description. Token: ``https://{board}``."""

    slug = "jobboard_io"
    hosts = frozenset()

    def list_url(self, board_token: str, page: int) -> str:
        return f"{base_url(board_token)}/jobs.rss"

    def item_id(self, item: dict[str, Any]) -> str:
        match = re.search(r"/jobs/(\d+)", first(item, "link") or "")
        if not match:
            raise ValueError("a JobBoard.io item without a job link")
        return match.group(1)

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        title = str(first(job, "title")).strip()
        role, _, company = title.rpartition(" at ")
        text = first(job, "description")
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=role or title,
            company_name=company or None,
            apply_url=as_url(str(first(job, "link"))),
            posted_at=feed_date(first(job, "pubDate")),
            description_html=f"<p>{html.escape(text)}</p>" if text else None,
        )


__all__ = [
    "HiringThingConnector",
    "JazzHRConnector",
    "JobBoardIoConnector",
    "MadgexConnector",
    "PageUpConnector",
    "SmartJobBoardConnector",
]
