"""Public career-page readers for five more platforms.

- Jibe (iCIMS Jibe career sites): ``GET https://{host}/api/jobs?page=N&limit=100`` is the JSON
  the career site's own search calls, no authentication. Sites sit on the employer's domain,
  so the board token is ``https://{host}`` and the host is admitted because the board is
  registered. The host's robots.txt crawl-delay applies (the fetcher honours it).
- JobScore: ``https://careers.jobscore.com/careers/{company}/feed.xml`` is the company's
  public job feed (XML, descriptions included). Its robots.txt only disallows /apply_flow/.
- softgarden: ``https://{company}.career.softgarden.de/jobs.feed.json`` is a schema.org
  DataFeed of JobPosting objects that the career page advertises in its llms.txt.
- Get on Board (https://www.getonbrd.com): the documented public API v0, read per category;
  a job board of many employers, so each job names its own company. Its robots.txt allows
  search indexing (Content-Signal: search=yes) and asks that content is not used to train AI.
- SOLID.Jobs (https://solid.jobs): its sitemap lists every offer page and each page carries
  JobPosting JSON-LD, so it is a ``JsonLdConnector`` (see jsonld_platforms.py).
"""

import json
import re
from typing import Any

from erio_core.connectors._paged import PagedJsonConnector, base_url
from erio_core.connectors._service import plain, service_host
from erio_core.connectors._util import as_url, epoch_seconds, iso_datetime, join_html, salary
from erio_core.connectors.base import BoardFetch, Connector, Fetcher, FetchError
from erio_core.connectors.feed import feed_date, xml_items
from erio_core.connectors.jsonld import parse_job_posting
from erio_core.schemas import PartialJob, RawPosting, RemoteStatus

TOKEN = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")


class JibeConnector(PagedJsonConnector):
    slug = "jibe"
    hosts: frozenset[str] = frozenset()
    page_size = 100
    max_pages = 30

    def list_url(self, board_token: str, page: int) -> str:
        return f"{base_url(board_token)}/api/jobs?page={page}&limit={self.page_size}"

    def items(self, data: Any) -> list[dict[str, Any]]:
        if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
            raise ValueError("a Jibe job list is {jobs: [...], totalCount}")
        return [job["data"] for job in data["jobs"] if isinstance(job.get("data"), dict)]

    def has_more(self, data: Any, items: list[dict[str, Any]], page: int) -> bool:
        return bool(page * self.page_size < int(data.get("totalCount") or 0))

    def item_id(self, item: dict[str, Any]) -> str:
        return str(item.get("slug") or item["req_id"])

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        host = base_url(raw.board_token)
        tags = [str(t) for key in ("tags1", "tags2", "tags3") for t in job.get(key) or []]
        workplace: RemoteStatus | None = None
        for tag in tags:
            low = tag.lower()
            if "hybrid" in low:
                workplace = "hybrid"
            elif "remote" in low and workplace is None:
                workplace = "remote"
            elif low in ("on-site", "onsite") and workplace is None:
                workplace = "onsite"
        categories = [c.get("name") for c in job.get("categories") or [] if isinstance(c, dict)]
        departments = [str(d).strip() for d in [job.get("department"), *categories] if d]
        lang = job.get("language") or "en-us"
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["title"]).strip(),
            company_name=plain(job.get("hiring_organization")),
            apply_url=as_url(f"{host}/jobs/{raw.external_id}?lang={lang}"),
            posted_at=iso_datetime(job.get("posted_date") or job.get("create_date")),
            location_text=plain(job.get("full_location") or job.get("short_location")),
            city=plain(job.get("city")),
            region=plain(job.get("state")),
            country_hint=plain(job.get("country_code") or job.get("country")),
            workplace_type=workplace,
            employment_type=plain(job.get("employment_type")),
            departments=list(dict.fromkeys(departments)),
            salary=salary(
                job.get("salary_min_value") or job.get("salary_value"),
                job.get("salary_max_value"),
                job.get("currency"),
                job.get("salary_frequency") or job.get("salary_period"),
            ),
            description_html=join_html(
                job.get("description"), job.get("responsibilities"), job.get("qualifications")
            ),
        )


class JobScoreConnector(Connector):
    slug = "jobscore"
    hosts = frozenset({"careers.jobscore.com"})

    def board_url(self, board_token: str) -> str:
        if not TOKEN.fullmatch(board_token.lower()):
            raise ValueError(f"not a JobScore company code: {board_token!r}")
        return f"https://careers.jobscore.com/careers/{board_token.lower()}/feed.xml"

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        postings = []
        for fields in xml_items(body, ("job",)):
            one = {name: values[0] for name, values in fields.items()}
            if one.get("id") and one.get("title"):
                postings.append(
                    RawPosting(
                        source_slug=self.slug,
                        board_token=board_token,
                        external_id=one["id"],
                        payload=one,
                    )
                )
        return postings

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        # The feed's detail link carries tracking parameters (ref, sid): drop them.
        detail = str(job.get("detail_url") or "").split("?")[0]
        remote = str(job.get("remote") or "").lower()
        workplace: RemoteStatus | None = "remote" if remote.startswith("yes") else None
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(job["title"]).strip(),
            company_name=job.get("company_name") or None,
            apply_url=as_url(detail or str(job["apply_url"])),
            posted_at=feed_date(job.get("opened_date") or job.get("created_on")),
            location_text=job.get("location") or None,
            city=job.get("city") or None,
            region=job.get("state") or None,
            country_hint=job.get("country") or None,
            workplace_type=workplace,
            employment_type=job.get("job_type") or None,
            departments=[job["department"]] if job.get("department") else [],
            description_html=job.get("description") or None,
        )


class SoftgardenConnector(Connector):
    slug = "softgarden"
    hosts = frozenset({"*.career.softgarden.de"})

    def board_url(self, board_token: str) -> str:
        if not TOKEN.fullmatch(board_token):
            raise ValueError(f"not a softgarden career-page name: {board_token!r}")
        return f"https://{board_token}.career.softgarden.de/jobs.feed.json"

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        feed = json.loads(body)
        elements = feed["dataFeedElement"]
        if not isinstance(elements, list):
            raise ValueError("'dataFeedElement' is not a list")
        postings = []
        for element in elements:
            item = element.get("item") if isinstance(element, dict) else None
            if not isinstance(item, dict) or not item.get("title") or not item.get("url"):
                continue
            identifier = item.get("identifier")
            ident = identifier.get("value") if isinstance(identifier, dict) else None
            postings.append(
                RawPosting(
                    source_slug=self.slug,
                    board_token=board_token,
                    external_id=str(ident or item["url"]),
                    payload=item,
                )
            )
        return postings

    def parse(self, raw: RawPosting) -> PartialJob:
        return parse_job_posting(self.slug, raw.external_id, str(raw.payload["url"]), raw.payload)


class GetOnBoardConnector(Connector):
    slug = "getonbrd"
    hosts = frozenset({"www.getonbrd.com"})
    multi_employer = True
    per_page = 100
    max_pages = 6  # per category

    def _api(self, board_token: str, path: str) -> str:
        host = service_host(board_token, self.hosts, "Get on Board")
        return f"https://{host}/api/v0/{path}"

    def board_url(self, board_token: str) -> str:
        return self._api(board_token, "categories")

    def _json(self, fetcher: Fetcher, url: str) -> Any:
        response = fetcher.get(url)
        if response.status == 429:
            raise FetchError("rate_limited", "source rate limit", 429)
        if response.status != 200:
            raise FetchError("http_error", f"HTTP {response.status}", response.status)
        try:
            return json.loads(response.body)
        except ValueError as error:
            raise FetchError("parse_error", f"malformed payload: {error}", 200) from error

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        data = json.loads(body)["data"]
        return [self._raw(board_token, job) for job in data]

    def _raw(self, board_token: str, job: dict[str, Any]) -> RawPosting:
        return RawPosting(
            source_slug=self.slug,
            board_token=board_token,
            external_id=str(job["id"]),
            payload=job,
        )

    def list_postings(
        self, fetcher: Fetcher, board_token: str, etag: str | None = None
    ) -> BoardFetch:
        categories = self._json(fetcher, self.board_url(board_token))
        try:
            names = [str(c["id"]) for c in categories["data"]]
        except (KeyError, TypeError) as error:
            raise FetchError("parse_error", f"malformed categories: {error}", 200) from error
        jobs: dict[str, dict[str, Any]] = {}
        complete = True
        for name in names:
            for page in range(1, self.max_pages + 1):
                query = f"per_page={self.per_page}&page={page}&expand=%5B%22company%22%5D"
                data = self._json(
                    fetcher, self._api(board_token, f"categories/{name}/jobs?{query}")
                )
                try:
                    found = data["data"]
                    pages = int(data["meta"]["total_pages"])
                except (KeyError, TypeError, ValueError) as error:
                    raise FetchError("parse_error", f"malformed job list: {error}", 200) from error
                for job in found:
                    jobs.setdefault(str(job["id"]), job)
                if page >= pages:
                    break
                if page == self.max_pages:
                    complete = False
        postings = [self._raw(board_token, job) for job in jobs.values()]
        return BoardFetch(postings=postings, http_status=200, body=b"", complete=complete)

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        attrs = job["attributes"]
        company = (attrs.get("company") or {}).get("data") or {}
        modality = str(attrs.get("remote_modality") or "")
        workplace: RemoteStatus | None = (
            "remote" if modality == "fully_remote" or attrs.get("remote") is True else
            "hybrid" if modality == "hybrid" else
            "onsite" if modality == "no_remote" else None
        )  # fmt: skip
        countries = [str(c) for c in attrs.get("countries") or []]
        zone = plain(attrs.get("remote_zone"))
        location = ", ".join(countries) or None
        if workplace == "remote" and not location:
            location = zone
        sections = [
            (attrs.get("description_headline"), attrs.get("description")),
            (attrs.get("functions_headline"), attrs.get("functions")),
            (attrs.get("desirable_headline"), attrs.get("desirable")),
            (attrs.get("benefits_headline"), attrs.get("benefits")),
        ]
        description = join_html(
            *(f"<h3>{head}</h3>{body}" if head else body for head, body in sections if body)
        )
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=str(attrs["title"]).strip(),
            company_name=plain((company.get("attributes") or {}).get("name")),
            apply_url=as_url(str(job["links"]["public_url"])),
            posted_at=epoch_seconds(attrs.get("published_at")),
            location_text=location,
            workplace_type=workplace,
            departments=[d] if (d := plain(attrs.get("category_name"))) else [],
            description_html=description,
        )


ATS_EXTRA_CONNECTORS: list[Connector] = [
    JibeConnector(),
    JobScoreConnector(),
    SoftgardenConnector(),
    GetOnBoardConnector(),
]
