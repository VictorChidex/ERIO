"""Board discovery from the Internet Archive: find employers' boards nobody told us about.

Applicant tracking systems publish each employer's jobs at a predictable address
(``boards.greenhouse.io/acme``, ``acme.recruitee.com``). The Internet Archive's CDX index lists
every such address it has ever saved, so reading it page by page, for each platform's address
shape, yields the employers that use the platform: tens of thousands of candidates instead of
the few hundred a seed list gives. A candidate is only a token until the platform confirms it:
each one is probed with its connector, and only a board that lists postings becomes a
company board. A token the platform rejects is remembered, so the next run moves on.

The CDX API is public and documented for programmatic use. It is read through the polite
fetcher (identified, rate limited, robots.txt obeyed). Common Crawl's index is not used: its
robots.txt closes it to crawlers.

    python -m erio_ingest.archive_discovery greenhouse --pages 2 --validate 50
"""

import json
import re
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol
from urllib.parse import urlencode

from sqlalchemy import Engine, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from erio_core.connectors import CONNECTORS, Connector, Fetcher, FetchError
from erio_core.db.models import Company, CompanyBoard, Source

CDX = "https://web.archive.org/cdx/search/cdx"
#: Archived addresses read per CDX page.
PAGE_ROWS = 2000
#: A platform's archive is read again from the start after this many seconds (30 days).
RESTART_AFTER_S = 30 * 24 * 3600
#: Subdomains and paths that belong to the platform itself, never to an employer.
PLATFORM_WORDS = frozenset(
    "www app api apps admin auth blog careers career cdn dashboard developer developers docs embed "
    "help jobs login marketplace mail static status support sitemap.xml robots.txt assets v1 "
    "j oops".split()
)
SLUG = r"[A-Za-z0-9][A-Za-z0-9_-]{1,60}"


@dataclass(frozen=True)
class Pattern:
    """One address shape of one platform, as the archive's index is asked for it."""

    source: str
    query: str  # the CDX ``url`` value
    token: re.Pattern[str]  # matches an archived address; the group "token" is the board token
    board_regex: str  # Java regex (the CDX server's) for an employer's board address alone
    by_domain: bool = False  # employers are subdomains: ask for the whole domain

    @property
    def key(self) -> str:
        return f"{self.source}:{self.query}"

    @property
    def root_filter(self) -> str:
        """CDX filter keeping only an employer's board address, one row per employer.

        A page of every saved address is dominated by a few employers' many job pages (14
        employers in 2,000 rows); the board's own address names each employer once, so the
        server filters before it counts the page (300 employers in one second).
        """
        return f"original:{self.board_regex}"


def path_pattern(host: str, source: str) -> Pattern:
    token = re.compile(rf"^https?://{re.escape(host)}/(?P<token>{SLUG})(?:[/?#]|$)", re.IGNORECASE)
    return Pattern(source, f"{host}/*", token, rf"https?://{re.escape(host)}/{SLUG}/?$")


def subdomain_pattern(domain: str, source: str) -> Pattern:
    token = re.compile(
        rf"^https?://(?P<token>{SLUG})\.{re.escape(domain)}(?:[:/?#]|$)", re.IGNORECASE
    )
    board = rf"https?://{SLUG}\.{re.escape(domain)}/?$"
    return Pattern(source, domain, token, board, by_domain=True)


# Platforms whose connector takes the plain employer slug as its board token. Each shape was
# read off the connector's own board address (``Connector.board_url``).
PATTERNS: list[Pattern] = [
    path_pattern("boards.greenhouse.io", "greenhouse"),
    path_pattern("job-boards.greenhouse.io", "greenhouse"),
    path_pattern("jobs.lever.co", "lever"),
    path_pattern("jobs.ashbyhq.com", "ashby"),
    path_pattern("apply.workable.com", "workable"),
    path_pattern("jobs.polymer.co", "polymer"),
    path_pattern("jobs.jobvite.com", "jobvite"),
    path_pattern("ats.rippling.com", "rippling"),
    subdomain_pattern("recruitee.com", "recruitee"),
    subdomain_pattern("bamboohr.com", "bamboohr"),
    subdomain_pattern("breezy.hr", "breezy"),
    subdomain_pattern("teamtailor.com", "teamtailor"),
    subdomain_pattern("jobs.personio.de", "personio"),
    subdomain_pattern("jobs.personio.com", "personio"),
    subdomain_pattern("pinpointhq.com", "pinpoint"),
    subdomain_pattern("hirehive.com", "hirehive"),
    subdomain_pattern("applytojob.com", "jazzhr"),
]


def cdx_url(pattern: Pattern, limit: int = PAGE_ROWS, resume_key: str | None = None) -> str:
    """The CDX request for one page of a pattern's archived addresses."""
    params: dict[str, str | list[str]] = {
        "url": pattern.query,
        "output": "json",
        "fl": "original",
        "collapse": "urlkey",
        "filter": ["statuscode:200", pattern.root_filter],
        "limit": str(limit),
        "showResumeKey": "true",
    }
    if pattern.by_domain:
        params["matchType"] = "domain"
    if resume_key:
        params["resumeKey"] = resume_key
    return f"{CDX}?{urlencode(params, doseq=True)}"


def parse_cdx(body: bytes) -> tuple[list[str], str | None]:
    """Addresses and the key of the next page from a CDX JSON answer.

    The answer is a list of rows: a header row, then one row per address; with
    ``showResumeKey`` a page that has a successor ends with an empty row and a row holding the key.
    """
    rows: list[Any] = json.loads(body) if body.strip() else []
    if not isinstance(rows, list):
        raise ValueError("the CDX answer is not a list of rows")
    urls: list[str] = []
    resume_key: str | None = None
    for position, row in enumerate(rows):
        if not isinstance(row, list):
            raise ValueError("a CDX row is not a list")
        if not row:
            tail = rows[position + 1] if position + 1 < len(rows) else None
            if isinstance(tail, list) and len(tail) == 1:
                resume_key = str(tail[0])
            break
        if position == 0 and row == ["original"]:
            continue
        urls.append(str(row[0]))
    return urls, resume_key


def tokens_in(pattern: Pattern, urls: list[str]) -> list[str]:
    """Employer tokens named by archived addresses, each once (case-insensitively)."""
    found: dict[str, str] = {}
    for url in urls:
        match = pattern.token.match(url)
        if not match:
            continue
        token = match["token"]
        if token.lower() in PLATFORM_WORDS or token.lower().startswith("www"):
            continue
        found.setdefault(token.lower(), token)
    return list(found.values())


class State(Protocol):
    """What the discovery remembers between runs."""

    def resume_key(self, pattern: str) -> tuple[str | None, int | None]:
        """Where the next run starts, and when the last full pass finished (None while one runs)."""
        ...

    def save_resume(self, pattern: str, key: str | None, now: int, done: bool) -> None: ...

    def rejected(self, source: str, tokens: list[str]) -> set[str]: ...

    def reject(self, source: str, token: str, now: int) -> None: ...


class MemoryState:
    def __init__(self) -> None:
        self.resume: dict[str, tuple[str | None, int | None]] = {}
        self.refused: dict[str, set[str]] = {}

    def resume_key(self, pattern: str) -> tuple[str | None, int | None]:
        key, finished = self.resume.get(pattern, (None, None))
        return key, finished

    def save_resume(self, pattern: str, key: str | None, now: int, done: bool) -> None:
        self.resume[pattern] = (key, now if done else None)

    def rejected(self, source: str, tokens: list[str]) -> set[str]:
        return {t for t in tokens if t.lower() in self.refused.get(source, set())}

    def reject(self, source: str, token: str, now: int) -> None:
        self.refused.setdefault(source, set()).add(token.lower())


class RedisState:
    """The same, in Redis: a resume key per pattern and the tokens a platform turned away."""

    def __init__(self, redis: Any):
        self.redis = redis

    def resume_key(self, pattern: str) -> tuple[str | None, int | None]:
        row = self.redis.hgetall(f"erio:archive:resume:{pattern}")
        key = (row.get(b"key") or b"").decode() or None
        stamp = row.get(b"done_at")
        return key, int(stamp) if stamp else None

    def save_resume(self, pattern: str, key: str | None, now: int, done: bool) -> None:
        self.redis.hset(
            f"erio:archive:resume:{pattern}",
            mapping={"key": key or "", "done_at": now if done else ""},
        )

    def rejected(self, source: str, tokens: list[str]) -> set[str]:
        if not tokens:
            return set()
        flags = self.redis.hmget(f"erio:archive:rejected:{source}", [t.lower() for t in tokens])
        return {token for token, flag in zip(tokens, flags, strict=True) if flag}

    def reject(self, source: str, token: str, now: int) -> None:
        self.redis.hset(f"erio:archive:rejected:{source}", token.lower(), now)


@dataclass
class ArchiveResult:
    pages: int = 0
    candidates: int = 0
    probed: int = 0
    found: dict[str, list[str]] = field(default_factory=dict)  # source -> tokens registered
    errors: list[str] = field(default_factory=list)


def pretty(token: str) -> str:
    """A company name for a token nothing else names yet ("acme-corp" is "Acme Corp")."""
    return re.sub(r"[-_]+", " ", token).strip().title() or token


def known_tokens(session: Session, source: str, tokens: list[str]) -> set[str]:
    rows = session.scalars(
        select(CompanyBoard.board_token).where(
            CompanyBoard.source_slug == source,
            func.lower(CompanyBoard.board_token).in_([t.lower() for t in tokens]),
        )
    )
    return {row.lower() for row in rows}


def register(session: Session, source: str, token: str, now: datetime) -> bool:
    """A company and its board for a token the platform confirmed; False if already known."""
    existing = session.scalar(
        select(CompanyBoard.id).where(
            CompanyBoard.source_slug == source, CompanyBoard.board_token == token
        )
    )
    if existing:
        return False
    company = Company(name=pretty(token))
    session.add(company)
    session.flush()
    session.execute(
        insert(CompanyBoard)
        .values(company_id=company.id, source_slug=source, board_token=token, next_crawl_at=now)
        .on_conflict_do_nothing(index_elements=["source_slug", "board_token"])
    )
    return True


def discover_from_archive(
    engine: Engine,
    archive: Fetcher,
    boards: Fetcher,
    state: State,
    now: Callable[[], datetime],
    patterns: list[Pattern] | None = None,
    connectors: Mapping[str, Connector] = CONNECTORS,
    pages: int = 4,
    validate: int = 400,
) -> ArchiveResult:
    """Read up to ``pages`` CDX pages per pattern and register up to ``validate`` new boards.

    A pattern resumes where its last run stopped; one that reached the end of the archive
    starts again after ``RESTART_AFTER_S``. ``archive`` reads the CDX index, ``boards`` probes
    candidate boards.
    """
    result = ArchiveResult()
    budget = validate
    with Session(engine) as session:
        live = set(
            session.scalars(
                select(Source.slug).where(
                    Source.status != "paused", Source.slug.in_(list(connectors))
                )
            )
        )
    for pattern in patterns if patterns is not None else PATTERNS:
        if pattern.source not in live or budget <= 0:
            continue
        stamp = int(now().timestamp())
        resume, finished = state.resume_key(pattern.key)
        if finished is not None and stamp - finished < RESTART_AFTER_S:
            continue  # read to the end lately
        for _ in range(pages):
            page_key = resume
            try:
                response = archive.get(cdx_url(pattern, PAGE_ROWS, resume))
                if response.status != 200:
                    raise FetchError(
                        "http_error", f"CDX answered {response.status}", response.status
                    )
                urls, resume = parse_cdx(response.body)
            except (FetchError, ValueError) as error:
                result.errors.append(f"{pattern.key}: {error}"[:300])
                break
            result.pages += 1
            tokens = tokens_in(pattern, urls)
            result.candidates += len(tokens)
            with Session(engine) as session:
                skip = known_tokens(session, pattern.source, tokens)
            skip |= {t.lower() for t in state.rejected(pattern.source, tokens)}
            waiting = [t for t in tokens if t.lower() not in skip]
            exhausted = False
            for token in waiting:
                if budget <= 0:
                    exhausted = True
                    break
                budget -= 1
                result.probed += 1
                confirmed = connectors[pattern.source].discover(boards, [token])
                if confirmed is None:
                    state.reject(pattern.source, token, stamp)
                    continue
                with Session(engine) as session, session.begin():
                    if register(session, pattern.source, confirmed, now()):
                        result.found.setdefault(pattern.source, []).append(confirmed)
            if exhausted:
                # Candidates are left on this page: the next run reads it again (the ones
                # already probed are skipped, known or rejected) instead of moving past them.
                state.save_resume(pattern.key, page_key, stamp, done=False)
                break
            state.save_resume(pattern.key, resume, stamp, done=resume is None)
            if resume is None or budget <= 0:
                break
    return result


def main(argv: list[str]) -> int:
    import argparse
    from datetime import UTC

    from redis import Redis
    from sqlalchemy import create_engine

    from erio_core.settings import get_settings
    from erio_ingest.worker import archive_fetcher, fetcher

    parser = argparse.ArgumentParser(description="Find employers' boards in the Internet Archive")
    parser.add_argument("platforms", nargs="*", help="platform slugs to read (default: all)")
    parser.add_argument("--pages", type=int, default=4, help="CDX pages per address shape")
    parser.add_argument("--validate", type=int, default=400, help="candidate boards to probe")
    args = parser.parse_args(argv[1:])
    settings = get_settings()
    patterns = [p for p in PATTERNS if not args.platforms or p.source in args.platforms]
    result = discover_from_archive(
        create_engine(settings.sqlalchemy_url),
        archive_fetcher(),
        fetcher(),
        RedisState(Redis.from_url(settings.redis_url)),
        lambda: datetime.now(UTC),
        patterns=patterns,
        pages=args.pages,
        validate=args.validate,
    )
    found = {source: len(tokens) for source, tokens in result.found.items()}
    print(
        f"read {result.pages} archive pages, {result.candidates} candidates, probed "
        f"{result.probed}, registered {found or 'none'}; errors: {result.errors or 'none'}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
