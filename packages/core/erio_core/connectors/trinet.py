"""TriNet Hire career sites (app.trinethire.com): server-rendered pages, no feed.

- list:   GET https://app.trinethire.com/companies/{token}/jobs lists every open job
          (title, type, location) on one page
- detail: GET https://app.trinethire.com/companies/{token}/jobs/{id}-{slug} adds the
          description, category and pay

The board token is "{companyId}-{slug}" from a career-site address such as
https://app.trinethire.com/companies/31905-adaptation/jobs. The job pages carry no
posting date. A crawl reads at most ``max_details`` job pages.
"""

import html
import re
from typing import Any

from erio_core.connectors._util import as_url, numbers_in, salary, salary_period
from erio_core.connectors.base import BoardFetch, Connector, Fetcher, FetchError
from erio_core.schemas import PartialJob, RawPosting, SalaryHint

TOKEN = re.compile(r"\d{1,9}-[a-z0-9][a-z0-9-]{0,100}")
HOST = "https://app.trinethire.com"
ROW = re.compile(
    r'<tr class="job"[^>]*>\s*<td><a [^>]*'
    r'href="(?P<path>/companies/[^"/]+/jobs/(?P<id>\d+)[^"]*)"[^>]*>'
    r'(?P<title>.*?)</a></td>\s*<td class="type">(?P<type>.*?)</td>\s*'
    r'<td class="location">(?P<location>.*?)</td>',
    re.S,
)
NAME = re.compile(r'<h3 class="job-name">(.*?)</h3>', re.S)
META = re.compile(r"<li><strong>([^<:]+):</strong>(.*?)</li>", re.S)
PIN = re.compile(r'<span class="map-pin-icon"></span>(.*?)</li>', re.S)
DESCRIPTION = re.compile(r'<div class="job-descr content">(.*?)</div>\s*</article>', re.S)
CURRENCY = {"$": "USD", "£": "GBP", "€": "EUR"}


def _text(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def _check(board_token: str) -> None:
    if not TOKEN.fullmatch(board_token):
        raise ValueError(f"not a TriNet Hire company token ({{id}}-{{slug}}): {board_token!r}")


def _pay(text: str) -> SalaryHint | None:
    amounts = numbers_in(text)
    currency = next((code for sign, code in CURRENCY.items() if sign in text), None)
    if not amounts or currency is None:
        return None
    return salary(amounts[0], amounts[-1], currency, salary_period(text))


class TriNetConnector(Connector):
    slug = "trinet"
    hosts = frozenset({"app.trinethire.com"})
    max_details = 200

    def board_url(self, board_token: str) -> str:
        _check(board_token)
        return f"{HOST}/companies/{board_token}/jobs"

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        page = body.decode("utf-8", "replace")
        if "career_site" not in page:
            raise ValueError("not a TriNet Hire career page")
        return [
            RawPosting(
                source_slug=self.slug,
                board_token=board_token,
                external_id=row["id"],
                payload={
                    "path": row["path"],
                    "title": _text(row["title"]),
                    "type": _text(row["type"]),
                    "location": _text(row["location"]),
                },
            )
            for row in ROW.finditer(page)
        ]

    def list_postings(
        self, fetcher: Fetcher, board_token: str, etag: str | None = None
    ) -> BoardFetch:
        result = super().list_postings(fetcher, board_token, etag)
        for posting in result.postings[: self.max_details]:
            try:
                response = fetcher.get(f"{HOST}{posting.payload['path']}")
            except FetchError:
                continue
            if response.status == 200:
                posting.payload["detail"] = self._detail(response.body.decode("utf-8", "replace"))
        return result

    def _detail(self, page: str) -> dict[str, Any]:
        meta = {_text(k).lower(): _text(v) for k, v in META.findall(page)}
        place = PIN.search(page)
        body = DESCRIPTION.search(page)
        return {
            "place": _text(place[1]) if place else None,
            "category": meta.get("category"),
            "salary": meta.get("salary"),
            "description": body[1].strip() if body else None,
        }

    def parse(self, raw: RawPosting) -> PartialJob:
        item = raw.payload
        detail = item.get("detail") or {}
        pay = detail.get("salary")
        description = detail.get("description")
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(item["title"]),
            apply_url=as_url(f"{HOST}{item['path']}"),
            location_text=detail.get("place") or item.get("location") or None,
            employment_type=item.get("type") or None,
            departments=[d] if (d := detail.get("category")) else [],
            salary=_pay(pay) if pay else None,
            description_html=(
                f"<p>Salary: {html.escape(pay)}</p>{description}"
                if pay and description
                else description
            ),
        )
