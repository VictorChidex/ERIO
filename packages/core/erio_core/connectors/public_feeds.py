"""Open job feeds: remote-work boards that publish their listings for reuse.

Each one lists the jobs of many employers (``multi_employer``), takes the
employer from the posting, and sends candidates to the listing's own page, so
the feed's terms are met: credit the source and link back. The credit each
service asks for is repeated in its entry of ``erio_core/data/platforms.json``
and on the coverage page.

- Arbeitnow (https://www.arbeitnow.com, also https://www.arbeitnow.co.uk):
  free public API, no key; terms ask for a link back to Arbeitnow.com.
- Remote OK (https://remoteok.com): public JSON feed; its terms ask for a
  followed link back to the job on Remote OK and a mention of Remote OK as the
  source.
- We Work Remotely (https://weworkremotely.com): public RSS feed; asks that
  links are attributed back to We Work Remotely.
- Jobicy (https://jobicy.com): public Jobs API, no key; asks that Jobicy is
  clearly credited as the original source. Its listing URL is the apply URL.
- Working Nomads (https://www.workingnomads.com): the public JSON feed its
  site links as "API"; states no attribution rule, ERIO credits it anyway.
- Python.org Jobs (https://www.python.org/jobs/): the Python Software
  Foundation's job board, public RSS feed; credit the Python Job Board.

The board token of each is ``https://{host}``; see ``_service.service_host``.
"""

import html
import json
import re
from typing import Any
from urllib.parse import quote

from erio_core.connectors._paged import PagedJsonConnector
from erio_core.connectors._service import plain, service_host
from erio_core.connectors._util import as_url, epoch_seconds, iso_datetime, salary
from erio_core.connectors.base import BoardFetch, Connector, Fetcher, FetchError
from erio_core.connectors.feed import feed_date, stable_id, xml_items
from erio_core.schemas import PartialJob, RawPosting

#: Salaries below this are hourly or placeholder values in feeds that give no period.
MIN_YEARLY = 1000


def _joined(value: Any) -> str | None:
    """A list of words (or one word) as "a, b"."""
    items = value if isinstance(value, list) else [value]
    return ", ".join(str(i).strip() for i in items if i and str(i).strip()) or None


class ArbeitnowConnector(PagedJsonConnector):
    slug = "arbeitnow"
    hosts = frozenset({"www.arbeitnow.com", "www.arbeitnow.co.uk"})
    multi_employer = True
    # 300 jobs a page; ten pages is the newest 3,000, the rest is reported as partial.
    max_pages = 10

    def list_url(self, board_token: str, page: int) -> str:
        host = service_host(board_token, self.hosts, "Arbeitnow")
        return f"https://{host}/api/job-board-api?page={page}"

    def items(self, data: Any) -> list[dict[str, Any]]:
        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            raise ValueError("Arbeitnow answers with {data: [...], links, meta}")
        return list(data["data"])

    def has_more(self, data: Any, items: list[dict[str, Any]], page: int) -> bool:
        links = data.get("links")
        return bool(isinstance(links, dict) and links.get("next"))

    def item_id(self, item: dict[str, Any]) -> str:
        return str(item["slug"])

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=plain(job["title"]) or "",
            company_name=plain(job.get("company_name")),
            apply_url=as_url(str(job["url"])),
            posted_at=epoch_seconds(job.get("created_at")),
            location_text=plain(job.get("location")),
            workplace_type="remote" if job.get("remote") else None,
            employment_type=_joined(job.get("job_types")),
            departments=[str(t) for t in job.get("tags") or [] if t][:3],
            # The feed sends its HTML as entities.
            description_html=html.unescape(str(job.get("description") or "")) or None,
        )


class RemoteOKConnector(Connector):
    slug = "remoteok"
    hosts = frozenset({"remoteok.com"})
    multi_employer = True

    def board_url(self, board_token: str) -> str:
        return f"https://{service_host(board_token, self.hosts, 'Remote OK')}/api"

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        data = json.loads(body)
        if not isinstance(data, list):
            raise ValueError("Remote OK answers with a JSON array")
        # The first element is the API's legal notice, not a job.
        return [
            RawPosting(
                source_slug=self.slug,
                board_token=board_token,
                external_id=str(job["id"]),
                payload=job,
            )
            for job in data
            if isinstance(job, dict) and job.get("id") and job.get("position")
        ]

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        low, high = job.get("salary_min") or 0, job.get("salary_max") or 0
        # Remote OK states salaries in US dollars a year; tiny values are placeholders.
        pay = (
            salary(low or None, high or None, "USD", "year")
            if max(low, high) >= MIN_YEARLY
            else None
        )
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=plain(job["position"]) or "",
            company_name=plain(job.get("company")),
            apply_url=as_url(str(job.get("url") or job["apply_url"])),
            posted_at=iso_datetime(job.get("date")) or epoch_seconds(job.get("epoch")),
            location_text=plain(job.get("location")),
            workplace_type="remote",
            departments=[str(t) for t in job.get("tags") or [] if t][:3],
            salary=pay,
            description_html=job.get("description") or None,
        )


class WeWorkRemotelyConnector(Connector):
    slug = "weworkremotely"
    hosts = frozenset({"weworkremotely.com"})
    multi_employer = True

    def board_url(self, board_token: str) -> str:
        return (
            f"https://{service_host(board_token, self.hosts, 'We Work Remotely')}/remote-jobs.rss"
        )

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        postings = []
        for fields in xml_items(body):
            first = {name: (values[0] if values else "") for name, values in fields.items()}
            if not first.get("title") or not first.get("guid"):
                continue
            postings.append(
                RawPosting(
                    source_slug=self.slug,
                    board_token=board_token,
                    external_id=stable_id(first["guid"]),
                    payload=first,
                )
            )
        if not postings:
            raise ValueError("no jobs in the We Work Remotely feed")
        return postings

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        # Titles read "Employer: Job title".
        company, _, title = str(job["title"]).partition(": ")
        if not title:
            company, title = "", company
        place = plain(job.get("region") or job.get("country"))
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=plain(title) or "",
            company_name=plain(company),
            apply_url=as_url(str(job["guid"])),
            posted_at=feed_date(job.get("pubdate")),
            location_text=place,
            workplace_type="remote",
            employment_type=plain(job.get("type")),
            departments=[c for c in [plain(job.get("category"))] if c],
            description_html=job.get("description") or None,
        )


class JobicyConnector(Connector):
    slug = "jobicy"
    hosts = frozenset({"jobicy.com"})
    multi_employer = True
    page_size = 100
    # The API lists the last 7 days, newest first; ten pages of 100 is a full week's worth
    # on a normal day, and anything beyond is reported as partial.
    max_pages = 10

    def board_url(self, board_token: str) -> str:
        host = service_host(board_token, self.hosts, "Jobicy")
        return f"https://{host}/api/jobs?count={self.page_size}"

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        return [self._raw(board_token, job) for job in self._jobs(json.loads(body))]

    @staticmethod
    def _jobs(data: Any) -> list[dict[str, Any]]:
        if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
            raise ValueError("Jobicy answers with {jobs: [...], nextCursor}")
        return list(data["jobs"])

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
        url = self.board_url(board_token)
        jobs: dict[str, dict[str, Any]] = {}
        first: bytes = b""
        complete = True
        cursor: str | None = None
        for page in range(1, self.max_pages + 1):
            response = fetcher.get(url if cursor is None else f"{url}&cursor={quote(cursor)}")
            if response.status == 429:
                raise FetchError("rate_limited", "source rate limit", 429)
            if response.status != 200:
                raise FetchError("http_error", f"HTTP {response.status}", response.status)
            try:
                data = json.loads(response.body)
                found = self._jobs(data)
            except (ValueError, KeyError, TypeError) as error:
                raise FetchError("parse_error", f"malformed payload: {error}", 200) from error
            first = first or response.body
            for job in found:
                jobs.setdefault(str(job["id"]), job)
            cursor = data.get("nextCursor") if isinstance(data, dict) else None
            if not found or not cursor or not data.get("hasMore"):
                break
            if page == self.max_pages:
                complete = False
        postings = [self._raw(board_token, job) for job in jobs.values()]
        return BoardFetch(postings=postings, http_status=200, body=first, complete=complete)

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        pay = salary(
            job.get("salaryMin"), job.get("salaryMax"), job.get("salaryCurrency"),
            job.get("salaryPeriod"),
        )  # fmt: skip
        place = plain(job.get("jobGeo"))
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=plain(job["jobTitle"]) or "",
            company_name=plain(job.get("companyName")),
            apply_url=as_url(str(job["url"])),
            posted_at=iso_datetime(job.get("pubDate")),
            location_text=place,
            workplace_type="remote",
            employment_type=_joined(job.get("jobType")),
            departments=[str(i) for i in job.get("jobIndustry") or [] if i][:3],
            salary=pay,
            description_html=job.get("jobDescription") or None,
        )


class WorkingNomadsConnector(Connector):
    slug = "workingnomads"
    hosts = frozenset({"www.workingnomads.com"})
    multi_employer = True

    def board_url(self, board_token: str) -> str:
        host = service_host(board_token, self.hosts, "Working Nomads")
        return f"https://{host}/api/exposed_jobs/"

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        data = json.loads(body)
        if not isinstance(data, list):
            raise ValueError("Working Nomads answers with a JSON array")
        postings = []
        for job in data:
            found = re.search(r"/job/go/(\d+)", str(job.get("url", "")))
            if not found or not job.get("title"):
                continue
            postings.append(
                RawPosting(
                    source_slug=self.slug,
                    board_token=board_token,
                    external_id=found[1],
                    payload=job,
                )
            )
        return postings

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=plain(job["title"]) or "",
            company_name=plain(job.get("company_name")),
            apply_url=as_url(str(job["url"])),
            posted_at=iso_datetime(job.get("pub_date")),
            location_text=plain(job.get("location")),
            workplace_type="remote",
            departments=[c for c in [plain(job.get("category_name"))] if c],
            description_html=job.get("description") or None,
        )


COMPANY_SUFFIX = re.compile(
    r"^(inc\.?|llc\.?|ltd\.?|limited|gmbh|co\.?|corp\.?|s\.?a\.?|b\.?v\.?|ag|plc|pty|l\.?l\.?c\.?)$",
    re.IGNORECASE,
)


def split_python_title(title: str) -> tuple[str, str | None]:
    """ "Senior Python Developer, Eliassen Group" is (title, employer). The employer is the
    last comma part, with a legal suffix ("ActivePrime, Inc.") kept with its name."""
    parts = [p.strip() for p in title.split(", ")]
    if len(parts) < 2:
        return title.strip(), None
    take = 2 if COMPANY_SUFFIX.match(parts[-1]) and len(parts) > 2 else 1
    employer = ", ".join(parts[-take:])
    return ", ".join(parts[:-take]).strip(), employer or None


class PythonJobsConnector(Connector):
    slug = "pythonjobs"
    hosts = frozenset({"www.python.org"})
    multi_employer = True

    def board_url(self, board_token: str) -> str:
        return f"https://{service_host(board_token, self.hosts, 'Python.org')}/jobs/feed/rss/"

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        postings = []
        for fields in xml_items(body):
            first = {name: (values[0] if values else "") for name, values in fields.items()}
            found = re.search(r"/jobs/(\d+)/?$", first.get("link", ""))
            if not first.get("title") or not found:
                continue
            postings.append(
                RawPosting(
                    source_slug=self.slug,
                    board_token=board_token,
                    external_id=found[1],
                    payload=first,
                )
            )
        if not postings:
            raise ValueError("no jobs in the Python.org feed")
        return postings

    def parse(self, raw: RawPosting) -> PartialJob:
        job = raw.payload
        title, employer = split_python_title(str(job["title"]))
        # The description opens with the place on a line of its own.
        place, _, body = str(job.get("description", "")).partition("\n")
        text = plain(place)
        remote = bool(text and text.lower().startswith("remote"))
        return PartialJob(
            source_slug=self.slug,
            external_id=raw.external_id,
            title=plain(title) or "",
            company_name=plain(employer),
            apply_url=as_url(str(job["link"])),
            location_text=text,
            workplace_type="remote" if remote else None,
            description_html=body.strip() or None,
        )


PUBLIC_FEED_CONNECTORS: list[Connector] = [
    ArbeitnowConnector(),
    RemoteOKConnector(),
    WeWorkRemotelyConnector(),
    JobicyConnector(),
    WorkingNomadsConnector(),
    PythonJobsConnector(),
]
