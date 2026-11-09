"""GET /v1/insights/pulse, /v1/companies and /v1/companies/{slug}.

What the index knows about itself: the market as a whole (the pulse) and each
employer. Nothing is estimated: every figure is a count or an exact quartile
of what is stored, and pay is never converted between currencies.

Counts of open roles come from OpenSearch aggregations (the same documents a
search returns). Anything about roles that left, and the exact quartiles,
comes from Postgres, which keeps closed jobs and the stored salary fields.
"""

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query
from opensearchpy import OpenSearch
from pydantic import BaseModel
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import ColumnElement, Engine, and_, func, or_, select
from sqlalchemy.orm import Session

from erio_api.access import rate_limit, redis_client
from erio_api.deps import engine, run_search, search_alias, search_client
from erio_api.errors import ApiError
from erio_core.db.models import Company, CompanyBoard, Country, Job, JobSource, RawPosting, Source

router = APIRouter(prefix="/v1", tags=["insights"], dependencies=[Depends(rate_limit)])

PULSE_CACHE_SECONDS = 300
FLOW_DAYS = 30
TOP_COUNTRIES = 10
SLUG_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"

# Buckets are fixed lists, so an empty bucket is still shown (as 0).
POSTED_BUCKETS = [
    ("week", "Posted this week"),
    ("weeks", "1 to 4 weeks ago"),
    ("months", "1 to 3 months ago"),
    ("older", "Over 3 months ago"),
    ("undated", "No date given"),
]
SEEN_BUCKETS = [
    ("day", "Last 24 hours"),
    ("days", "1 to 3 days ago"),
    ("week", "3 to 7 days ago"),
    ("older", "Over a week ago"),
]


class Bucket(BaseModel):
    key: str
    label: str
    count: int


class Quartiles(BaseModel):
    """Lower quartile, median and upper quartile of each posted range's midpoint."""

    currency: str
    period: str
    roles: int
    lower: float
    median: float
    upper: float


class FlowDay(BaseModel):
    date: date
    added: int
    removed: int


class Flow(BaseModel):
    days: list[FlowDay]
    added: int
    removed: int
    # Roles that left are only known from the day ERIO started following them.
    removals_tracked_since: datetime | None


class PulseTotals(BaseModel):
    open_roles: int
    companies_hiring: int
    sources_watched: int
    platforms_live: int
    roles_stating_pay: int
    pay_stated_pct: float | None
    remote_roles: int


class PulseCountry(BaseModel):
    code: str
    name: str
    roles: int
    remote_pct: float | None
    pay_stated_pct: float | None


class PulsePlatform(BaseModel):
    slug: str
    name: str
    kind: str
    roles: int


class PulseSources(BaseModel):
    platforms: list[PulsePlatform]
    # Roles carried by at least one platform of the kind; a role on two
    # platforms of one kind counts once.
    ats_roles: int
    board_roles: int


class Pulse(BaseModel):
    generated_at: datetime
    totals: PulseTotals
    flow: Flow
    posted: list[Bucket]
    last_seen: list[Bucket]
    roles: list[Bucket]
    work_mode: list[Bucket]
    pay: list[Quartiles]
    countries: list[PulseCountry]
    sources: PulseSources


class PulseOut(BaseModel):
    data: Pulse


class CompanyRow(BaseModel):
    slug: str
    name: str
    domain: str | None
    logo_url: str | None
    country_code: str | None
    open_roles: int


class CompaniesOut(BaseModel):
    data: list[CompanyRow]
    meta: dict[str, int]


class Place(BaseModel):
    key: str
    label: str
    count: int


class Opening(BaseModel):
    canonical_id: str
    title: str
    location_text: str | None
    country_code: str | None
    remote_status: str
    employment_type: str | None
    posted_at: datetime | None
    indexed_at: datetime


class CompanyPlatform(BaseModel):
    slug: str
    name: str
    kind: str
    roles: int


class CompanyProfile(BaseModel):
    slug: str
    name: str
    domain: str | None
    logo_url: str | None
    country_code: str | None
    tracked_since: datetime
    last_checked_at: datetime | None
    open_roles: int
    added_30d: int
    removed_30d: int
    remote_pct: float | None
    pay_stated_pct: float | None
    flow: Flow
    roles: list[Bucket]
    countries: list[Place]
    locations: list[Place]
    work_mode: list[Bucket]
    contracts: list[Bucket]
    posted: list[Bucket]
    pay: list[Quartiles]
    platforms: list[CompanyPlatform]
    latest: list[Opening]


class CompanyOut(BaseModel):
    data: CompanyProfile


def _pct(part: int, whole: int) -> float | None:
    return round(100 * part / whole, 1) if whole else None


def _open() -> list[ColumnElement[bool]]:
    """The roles the index serves as open: the same rule the indexer applies."""
    return [Job.status == "open", Job.review_reason.is_(None), Job.merged_into.is_(None)]


def _added_at() -> ColumnElement[datetime]:
    """When a role appeared: the date its employer gave, else the day ERIO first saw it."""
    return func.coalesce(Job.posted_at, Job.indexed_at)


def _day(value: Any) -> ColumnElement[date]:
    return func.date(func.timezone("UTC", value))


def _flow(session: Session, now: datetime, company_id: int | None = None) -> Flow:
    today = now.astimezone(UTC).date()
    first = today - timedelta(days=FLOW_DAYS - 1)
    start = datetime.combine(first, datetime.min.time(), tzinfo=UTC)
    scope: list[ColumnElement[bool]] = [Job.merged_into.is_(None), Job.review_reason.is_(None)]
    if company_id is not None:
        scope.append(Job.company_id == company_id)
    added_day = _day(_added_at())
    added = dict(
        session.execute(
            select(added_day, func.count())
            .where(*scope, _added_at() >= start, _added_at() < start + timedelta(days=FLOW_DAYS))
            .group_by(added_day)
        )
        .tuples()
        .all()
    )
    removed_day = _day(Job.closed_at)
    removed = dict(
        session.execute(
            select(removed_day, func.count())
            .where(
                *scope, Job.closed_at >= start, Job.closed_at < start + timedelta(days=FLOW_DAYS)
            )
            .group_by(removed_day)
        )
        .tuples()
        .all()
    )
    tracked_since = session.scalar(select(func.min(Job.indexed_at)).where(*scope))
    days = [
        FlowDay(date=d, added=added.get(d, 0), removed=removed.get(d, 0))
        for d in (first + timedelta(days=n) for n in range(FLOW_DAYS))
    ]
    return Flow(
        days=days,
        added=sum(d.added for d in days),
        removed=sum(d.removed for d in days),
        removals_tracked_since=tracked_since,
    )


def _quartiles(
    session: Session, company_id: int | None = None, periods: tuple[str, ...] = ("year",)
) -> list[Quartiles]:
    """Quartiles of each range's midpoint, per currency and period, in the posted currency."""
    low = func.coalesce(Job.salary_min, Job.salary_max)
    high = func.coalesce(Job.salary_max, Job.salary_min)
    middle = (low + high) / 2.0
    statement = (
        select(
            Job.salary_currency,
            Job.salary_period,
            func.count(),
            func.percentile_cont(0.25).within_group(middle),
            func.percentile_cont(0.5).within_group(middle),
            func.percentile_cont(0.75).within_group(middle),
        )
        .where(
            *_open(),
            Job.salary_currency.is_not(None),
            Job.salary_period.in_(periods),
            or_(Job.salary_min.is_not(None), Job.salary_max.is_not(None)),
        )
        .group_by(Job.salary_currency, Job.salary_period)
        .order_by(func.count().desc(), Job.salary_currency)
    )
    if company_id is not None:
        statement = statement.where(Job.company_id == company_id)
    return [
        Quartiles(
            currency=str(currency),
            period=str(period),
            roles=roles,
            lower=round(float(q1), 2),
            median=round(float(q2), 2),
            upper=round(float(q3), 2),
        )
        for currency, period, roles, q1, q2, q3 in session.execute(statement).tuples()
    ]


def _buckets(counts: dict[str, int], labels: list[tuple[str, str]]) -> list[Bucket]:
    return [Bucket(key=key, label=label, count=counts.get(key, 0)) for key, label in labels]


def _titled(key: str) -> str:
    return key.replace("_", " ").capitalize()


def _seen(gte: str | None = None, lt: str | None = None) -> dict[str, Any]:
    """Last seen live: the last check of the job, or the day it was indexed if never checked."""
    bounds = {k: v for k, v in (("gte", gte), ("lt", lt)) if v}
    return {
        "bool": {
            "should": [
                {"range": {"last_verified_at": bounds}},
                {
                    "bool": {
                        "must_not": {"exists": {"field": "last_verified_at"}},
                        "filter": {"range": {"indexed_at": bounds}},
                    }
                },
            ],
            "minimum_should_match": 1,
        }
    }


def _open_pay() -> dict[str, Any]:
    return {
        "bool": {
            "should": [
                {"exists": {"field": "salary_min"}},
                {"exists": {"field": "salary_max"}},
            ],
            "minimum_should_match": 1,
        }
    }


def _compute_pulse(db: Engine, search: OpenSearch, alias: str, now: datetime) -> dict[str, Any]:
    pay = _open_pay()
    body: dict[str, Any] = {
        "size": 0,
        "track_total_hits": True,
        "query": {"term": {"status": "open"}},
        "aggs": {
            "companies": {"cardinality": {"field": "company_name.kw"}},
            "pay": {"filter": pay},
            "remote": {"filter": {"term": {"remote_status": "remote"}}},
            "posted": {
                "filters": {
                    "filters": {
                        "week": {"range": {"posted_at": {"gte": "now-7d"}}},
                        "weeks": {"range": {"posted_at": {"gte": "now-28d", "lt": "now-7d"}}},
                        "months": {"range": {"posted_at": {"gte": "now-90d", "lt": "now-28d"}}},
                        "older": {"range": {"posted_at": {"lt": "now-90d"}}},
                        "undated": {"bool": {"must_not": {"exists": {"field": "posted_at"}}}},
                    }
                }
            },
            "seen": {
                "filters": {
                    "filters": {
                        "day": _seen(gte="now-24h"),
                        "days": _seen(gte="now-3d", lt="now-24h"),
                        "week": _seen(gte="now-7d", lt="now-3d"),
                        "older": _seen(lt="now-7d"),
                    }
                }
            },
            "roles": {"terms": {"field": "role_category", "size": 30}},
            "work_mode": {"terms": {"field": "remote_status", "size": 5}},
            "work_mode_unstated": {"missing": {"field": "remote_status"}},
            "countries": {
                "terms": {"field": "country_code", "size": TOP_COUNTRIES},
                "aggs": {
                    "remote": {"filter": {"term": {"remote_status": "remote"}}},
                    "pay": {"filter": pay},
                },
            },
            "platforms": {"terms": {"field": "sources", "size": 200}},
        },
    }
    with Session(db) as session:
        kinds = {
            slug: (name, kind)
            for slug, name, kind in session.execute(
                select(Source.slug, Source.name, Source.kind)
            ).tuples()
        }
        names = dict(session.execute(select(Country.code, Country.name)).tuples().all())
        boards = session.scalar(select(func.count()).select_from(CompanyBoard)) or 0
        flow = _flow(session, now)
        quartiles = _quartiles(session)
    for kind in ("ats", "board"):
        slugs = [slug for slug, (_, k) in kinds.items() if k == kind]
        body["aggs"][f"{kind}_roles"] = {"filter": {"terms": {"sources": slugs}}}
    aggs = run_search(search, alias, body)["aggregations"]
    total = run_search(
        search, alias, {"size": 0, "track_total_hits": True, "query": {"term": {"status": "open"}}}
    )["hits"]["total"]["value"]
    open_roles = int(total)
    stating_pay = aggs["pay"]["doc_count"]
    modes = {b["key"]: b["doc_count"] for b in aggs["work_mode"]["buckets"]}
    modes["not_stated"] = aggs["work_mode_unstated"]["doc_count"]
    platforms = [
        PulsePlatform(
            slug=b["key"],
            name=kinds.get(b["key"], (b["key"], "ats"))[0],
            kind=kinds.get(b["key"], (b["key"], "ats"))[1],
            roles=b["doc_count"],
        )
        for b in aggs["platforms"]["buckets"]
    ]
    pulse = Pulse(
        generated_at=now,
        totals=PulseTotals(
            open_roles=open_roles,
            companies_hiring=aggs["companies"]["value"],
            sources_watched=boards,
            platforms_live=len(platforms),
            roles_stating_pay=stating_pay,
            pay_stated_pct=_pct(stating_pay, open_roles),
            remote_roles=aggs["remote"]["doc_count"],
        ),
        flow=flow,
        posted=_buckets(
            {k: v["doc_count"] for k, v in aggs["posted"]["buckets"].items()}, POSTED_BUCKETS
        ),
        last_seen=_buckets(
            {k: v["doc_count"] for k, v in aggs["seen"]["buckets"].items()}, SEEN_BUCKETS
        ),
        roles=[
            Bucket(key=b["key"], label=_titled(b["key"]), count=b["doc_count"])
            for b in aggs["roles"]["buckets"]
        ],
        work_mode=_buckets(
            modes,
            [
                ("remote", "Remote"),
                ("hybrid", "Hybrid"),
                ("onsite", "On-site"),
                ("not_stated", "Not stated"),
            ],
        ),
        pay=quartiles,
        countries=[
            PulseCountry(
                code=b["key"],
                name=names.get(b["key"], b["key"]),
                roles=b["doc_count"],
                remote_pct=_pct(b["remote"]["doc_count"], b["doc_count"]),
                pay_stated_pct=_pct(b["pay"]["doc_count"], b["doc_count"]),
            )
            for b in aggs["countries"]["buckets"]
        ],
        sources=PulseSources(
            platforms=platforms,
            ats_roles=aggs["ats_roles"]["doc_count"],
            board_roles=aggs["board_roles"]["doc_count"],
        ),
    )
    return pulse.model_dump(mode="json")


def _remembered(
    redis: Redis, key: str, seconds: int, compute: Callable[[], dict[str, Any]]
) -> dict[str, Any]:
    """The cached answer for ``key``, computed and kept for ``seconds`` when absent.

    A Redis outage only costs the cache: the answer is computed as usual.
    """
    try:
        hit = redis.get(key)
        if hit is not None:
            cached: dict[str, Any] = json.loads(hit)
            return cached
    except (RedisError, ValueError):
        pass
    value = compute()
    try:
        redis.set(key, json.dumps(value), ex=seconds)
    except RedisError:
        pass
    return value


@router.get(
    "/insights/pulse",
    response_model=PulseOut,
    summary="Market pulse: live figures across every open role",
)
def pulse(
    db: Annotated[Engine, Depends(engine)],
    search: Annotated[OpenSearch, Depends(search_client)],
    alias: Annotated[str, Depends(search_alias)],
    redis: Annotated[Redis, Depends(redis_client)],
) -> dict[str, Any]:
    """Every figure is a count of stored roles or an exact quartile; nothing is
    estimated and pay is never converted. Cached for five minutes."""
    scope = hashlib.sha256(f"{db.url}|{alias}".encode()).hexdigest()[:16]
    data = _remembered(
        redis,
        f"erio:insights:pulse:{scope}",
        PULSE_CACHE_SECONDS,
        lambda: _compute_pulse(db, search, alias, datetime.now(UTC)),
    )
    return {"data": data}


def _like(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


@router.get(
    "/companies", response_model=CompaniesOut, summary="Employers ERIO tracks, by open roles"
)
def companies(
    db: Annotated[Engine, Depends(engine)],
    q: Annotated[str | None, Query(max_length=100, description="Part of a company name")] = None,
    country: Annotated[
        str | None,
        Query(
            pattern=r"^[A-Za-z]{2}$",
            description="ISO country code: companies with open roles located there",
        ),
    ] = None,
    hiring_only: Annotated[bool, Query(description="Only companies with open roles")] = True,
    sort: Annotated[str, Query(pattern="^(roles|name)$")] = "roles",
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 24,
) -> dict[str, Any]:
    open_counts = (
        select(Job.company_id, func.count().label("open_roles"))
        .where(*_open())
        .group_by(Job.company_id)
        .subquery()
    )
    roles = func.coalesce(open_counts.c.open_roles, 0)
    filters: list[ColumnElement[bool]] = []
    if q and q.strip():
        filters.append(Company.name.ilike(_like(q.strip()), escape="\\"))
    if country:
        in_country = select(Job.company_id).where(*_open(), Job.country_code == country.upper())
        filters.append(Company.id.in_(in_country))
    if hiring_only:
        filters.append(roles > 0)
    base = (
        select(Company, roles.label("open_roles"))
        .outerjoin(open_counts, open_counts.c.company_id == Company.id)
        .where(*filters)
    )
    order = (
        [Company.name, Company.id] if sort == "name" else [roles.desc(), Company.name, Company.id]
    )
    with Session(db) as session:
        total = session.scalar(select(func.count()).select_from(base.subquery())) or 0
        rows = session.execute(base.order_by(*order).limit(per_page).offset((page - 1) * per_page))
        data = [
            {
                "slug": company.slug,
                "name": company.name,
                "domain": company.domain,
                "logo_url": company.logo_url,
                "country_code": company.country_code,
                "open_roles": open_roles,
            }
            for company, open_roles in rows.tuples()
        ]
    return {"data": data, "meta": {"total": total, "page": page, "per_page": per_page}}


def _counted(
    session: Session, column: Any, company_id: int, limit: int | None = None
) -> list[tuple[Any, int]]:
    statement = (
        select(column, func.count())
        .where(*_open(), Job.company_id == company_id)
        .group_by(column)
        .order_by(func.count().desc(), column)
    )
    if limit:
        statement = statement.limit(limit)
    return [(key, n) for key, n in session.execute(statement).tuples()]


def _company_profile(session: Session, company: Company, now: datetime) -> dict[str, Any]:
    cid = company.id
    open_roles = session.scalar(select(func.count()).where(*_open(), Job.company_id == cid)) or 0
    remote = (
        session.scalar(
            select(func.count()).where(
                *_open(), Job.company_id == cid, Job.remote_status == "remote"
            )
        )
        or 0
    )
    paid = (
        session.scalar(
            select(func.count()).where(
                *_open(),
                Job.company_id == cid,
                or_(Job.salary_min.is_not(None), Job.salary_max.is_not(None)),
            )
        )
        or 0
    )
    flow = _flow(session, now, cid)
    names = dict(session.execute(select(Country.code, Country.name)).tuples().all())
    start = now - timedelta(days=90)
    week, month = now - timedelta(days=7), now - timedelta(days=28)
    posted = {
        "week": and_(Job.posted_at >= week),
        "weeks": and_(Job.posted_at >= month, Job.posted_at < week),
        "months": and_(Job.posted_at >= start, Job.posted_at < month),
        "older": and_(Job.posted_at < start),
        "undated": Job.posted_at.is_(None),
    }
    posted_counts = {
        key: session.scalar(select(func.count()).where(*_open(), Job.company_id == cid, cond)) or 0
        for key, cond in posted.items()
    }
    work = dict(_counted(session, Job.remote_status, cid))
    contracts = [
        Bucket(key=str(k or "not_stated"), label=_titled(str(k or "not_stated")), count=n)
        for k, n in _counted(session, Job.employment_type, cid)
    ]
    platforms = session.execute(
        select(Source.slug, Source.name, Source.kind, func.count(func.distinct(Job.canonical_id)))
        .join(RawPosting, RawPosting.source_slug == Source.slug)
        .join(JobSource, JobSource.raw_posting_id == RawPosting.id)
        .join(Job, Job.canonical_id == JobSource.job_id)
        .where(*_open(), Job.company_id == cid)
        .group_by(Source.slug, Source.name, Source.kind)
        .order_by(func.count(func.distinct(Job.canonical_id)).desc(), Source.slug)
    ).tuples()
    latest = session.scalars(
        select(Job)
        .where(*_open(), Job.company_id == cid)
        .order_by(_added_at().desc(), Job.canonical_id)
        .limit(10)
    ).all()
    boards = session.execute(
        select(func.min(CompanyBoard.created_at), func.max(CompanyBoard.last_ok_at)).where(
            CompanyBoard.company_id == cid
        )
    ).one()
    profile = CompanyProfile(
        slug=company.slug,
        name=company.name,
        domain=company.domain,
        logo_url=company.logo_url,
        country_code=company.country_code,
        tracked_since=min(company.created_at, boards[0] or company.created_at),
        last_checked_at=boards[1],
        open_roles=open_roles,
        added_30d=flow.added,
        removed_30d=flow.removed,
        remote_pct=_pct(remote, open_roles),
        pay_stated_pct=_pct(paid, open_roles),
        flow=flow,
        roles=[
            Bucket(key=str(k), label=_titled(str(k)), count=n)
            for k, n in _counted(session, Job.role_category, cid)
        ],
        countries=[
            Place(key=str(k), label=names.get(k, str(k)), count=n)
            for k, n in _counted(session, Job.country_code, cid, 10)
            if k
        ],
        locations=[
            Place(key=str(k), label=str(k), count=n)
            for k, n in _counted(session, Job.city, cid, 10)
            if k
        ],
        work_mode=_buckets(
            work, [("remote", "Remote"), ("hybrid", "Hybrid"), ("onsite", "On-site")]
        ),
        contracts=contracts,
        posted=_buckets(posted_counts, POSTED_BUCKETS),
        pay=_quartiles(session, cid, ("year", "month", "hour")),
        platforms=[
            CompanyPlatform(slug=slug, name=name, kind=kind, roles=n)
            for slug, name, kind, n in platforms
        ],
        latest=[Opening.model_validate(job, from_attributes=True) for job in latest],
    )
    return profile.model_dump(mode="json")


@router.get(
    "/companies/{slug}",
    response_model=CompanyOut,
    summary="One employer: roles in and out, what it hires for, where, and pay",
)
def company_profile(
    slug: Annotated[str, Path(pattern=SLUG_PATTERN, max_length=100)],
    db: Annotated[Engine, Depends(engine)],
) -> dict[str, Any]:
    with Session(db) as session:
        company = session.scalars(select(Company).where(Company.slug == slug)).one_or_none()
        if company is None:
            raise ApiError(404, "not_found", f"no company {slug}")
        return {"data": _company_profile(session, company, datetime.now(UTC))}
