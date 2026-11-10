"""Feishu Hire (Lark) career sites on ``{tenant}.jobs.feishu.cn``.

The career site is a single-page app that asks for an anonymous CSRF token, then searches
jobs with it; there is no login. The token is only ever sent back to the host that issued it.

- session: POST /api/v1/csrf/token  ({"data": {"token": ...}}, also sets the token cookie)
- list:    POST /api/v1/search/job/posts?portal_type=6&portal_entrance=1 with header
           ``x-csrf-token`` and ``website-path: {path}``, body {"limit", "offset", ...}

The board token is "{tenant}/{path}": the host's first label and the first path segment of
the career site ("bytedance/society" for ``bytedance.jobs.feishu.cn/society``). Each job
comes with its description and requirements. Pages hold 50 jobs and a crawl reads at most
``max_pages``, so a larger board (ByteDance has thousands) is reported as incomplete.
The session cookie needs a fetcher whose client keeps cookies between requests.
"""

import json
import re
from html import escape
from typing import Any

from erio_core.connectors._post import header_poster
from erio_core.connectors._util import as_url, epoch_ms, join_html
from erio_core.connectors.base import BoardFetch, Connector, Fetcher, FetchError
from erio_core.schemas import PartialJob, RawPosting

TOKEN = re.compile(r"([a-z0-9][a-z0-9-]{0,62})/([A-Za-z0-9_-]{1,40})")
PAGE = 50


def _parts(board_token: str) -> tuple[str, str]:
    match = TOKEN.fullmatch(board_token)
    if not match:
        raise ValueError(f"not a Feishu Hire token (tenant/path): {board_token!r}")
    return match[1], match[2]


def _name(node: Any) -> str | None:
    """A name from a Feishu object, English first."""
    if not isinstance(node, dict):
        return None
    return node.get("en_name") or node.get("name") or node.get("i18n_name") or None


def _paragraphs(text: Any) -> str | None:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    return "".join(f"<p>{escape(line)}</p>" for line in lines) or None


class FeishuConnector(Connector):
    slug = "feishu"
    hosts = frozenset({"*.jobs.feishu.cn"})
    max_pages = 10

    def board_url(self, board_token: str) -> str:
        tenant, path = _parts(board_token)
        return f"https://{tenant}.jobs.feishu.cn/{path}"

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        data = json.loads(body)
        if data.get("code") != 0:
            raise ValueError(f"the site answered: {data.get('message')}")
        return [
            RawPosting(
                source_slug=self.slug,
                board_token=board_token,
                external_id=str(job["id"]),
                payload=job,
            )
            for job in data["data"]["job_post_list"]
            if job.get("title")
        ]

    def list_postings(
        self, fetcher: Fetcher, board_token: str, etag: str | None = None
    ) -> BoardFetch:
        tenant, path = _parts(board_token)
        post = header_poster(fetcher)
        base = f"https://{tenant}.jobs.feishu.cn"
        session = post.post_json_with(f"{base}/api/v1/csrf/token", {}, {})
        if session.status == 429:
            raise FetchError("rate_limited", "source rate limit", 429)
        if session.status != 200:
            raise FetchError("http_error", f"HTTP {session.status}", session.status)
        try:
            csrf = str(json.loads(session.body)["data"]["token"])
        except (ValueError, KeyError, TypeError) as error:
            raise FetchError("parse_error", "no public session token", 200) from error
        headers = {"x-csrf-token": csrf, "website-path": path, "Referer": f"{base}/{path}"}
        postings: dict[str, RawPosting] = {}
        first = b""
        total = 0
        for index in range(self.max_pages):
            body = {
                "keyword": "", "limit": PAGE, "offset": index * PAGE, "portal_type": 6,
                "portal_entrance": 1, "job_category_id_list": [], "location_code_list": [],
                "subject_id_list": [], "recruitment_id_list": [], "job_function_id_list": [],
            }  # fmt: skip
            url = f"{base}/api/v1/search/job/posts?portal_type=6&portal_entrance=1"
            response = post.post_json_with(url, body, headers)
            if response.status == 429:
                raise FetchError("rate_limited", "source rate limit", 429)
            if response.status != 200:
                raise FetchError("http_error", f"HTTP {response.status}", response.status)
            try:
                found = self.extract(response.body, board_token)
                total = int(json.loads(response.body)["data"].get("count") or 0)
            except (ValueError, KeyError, TypeError) as error:
                raise FetchError("parse_error", f"malformed payload: {error}", 200) from error
            first = first or response.body
            fresh = [p for p in found if p.external_id not in postings]
            postings.update((p.external_id, p) for p in fresh)
            if not fresh or len(postings) >= total:
                break
        return BoardFetch(
            postings=list(postings.values()),
            http_status=200,
            body=first,
            complete=len(postings) >= total,
        )

    def parse(self, raw: RawPosting) -> PartialJob:
        job: dict[str, Any] = raw.payload
        tenant, path = _parts(raw.board_token)
        cities = [n for c in job.get("city_list") or [] if (n := _name(c))]
        city = _name(job.get("city_info"))
        if city and city not in cities:
            cities.insert(0, city)
        info = job.get("job_post_info") or {}
        addresses = info.get("address_list") or []
        country = _name((addresses[0] if addresses else {}).get("country"))
        category = _name(job.get("job_category"))
        kind = _name(job.get("recruit_type"))
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["title"]).strip(),
            company_name=tenant.replace("-", " ").title(),
            apply_url=as_url(
                f"https://{tenant}.jobs.feishu.cn/{path}/position/{raw.external_id}/detail"
            ),
            posted_at=epoch_ms(job.get("publish_time")),
            location_text=", ".join(dict.fromkeys([*cities, *([country] if country else [])]))
            or None,
            city=cities[0] if cities else None,
            country_hint=country,
            employment_type=kind,
            departments=[category] if category else [],
            description_html=join_html(
                _paragraphs(job.get("description")), _paragraphs(job.get("requirement"))
            ),
        )
