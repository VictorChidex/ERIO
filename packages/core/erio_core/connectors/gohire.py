"""GoHire job widgets: GET https://api2.gohire.io/widget-jobs/{clientId} returns
{"jobs": [...]} with title, location, salary text, type, date and a link. The
list carries no description; the client ID is the 8-character suffix of the
board address, jobs.gohire.io/{company}-{clientid}/. (It answers with a JSON
body under a text/html content type.)"""

import re
from datetime import UTC, datetime
from typing import Any

from erio_core.connectors._paged import PagedJsonConnector
from erio_core.schemas import PartialJob, RawPosting

TOKEN = re.compile(r"[A-Za-z0-9]{6,12}")


def _date(value: Any) -> datetime | None:
    """ "20 November, 2025"."""
    try:
        return datetime.strptime(str(value), "%d %B, %Y").replace(tzinfo=UTC)
    except ValueError:
        return None


class GoHireConnector(PagedJsonConnector):
    slug = "gohire"
    hosts = frozenset({"api2.gohire.io"})

    def list_url(self, board_token: str, page: int) -> str:
        if not TOKEN.fullmatch(board_token):
            raise ValueError(f"not a GoHire client ID: {board_token!r}")
        return f"https://api2.gohire.io/widget-jobs/{board_token}"

    def items(self, data: Any) -> list[dict[str, Any]]:
        return list(data["jobs"])

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        pay = job.get("salary")
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["title"]).strip(),
            apply_url=job["link"],
            posted_at=_date(job.get("date")),
            location_text=job.get("location") or None,
            employment_type=job.get("type"),
            description_html=(job.get("description") or None)
            or (f"<p>Salary: {pay}</p>" if pay else None),
        )
