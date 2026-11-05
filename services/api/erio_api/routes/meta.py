"""GET /v1/countries, /v1/platforms and /v1/stats (spec section 7).

Every number comes from the live index or database; nothing is hard-coded.
"""

from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from opensearchpy import OpenSearch
from pydantic import BaseModel
from sqlalchemy import Engine, case, func, select
from sqlalchemy.orm import Session

from erio_api.deps import engine, search_alias, search_client
from erio_core.connectors import CONNECTORS
from erio_core.db.models import CompanyBoard, Country, CrawlRun, Source
from erio_core.db.seed import load_countries

router = APIRouter(prefix="/v1", tags=["reference"])

LIVE_WITHIN = timedelta(hours=1)


@lru_cache
def _centres() -> dict[str, tuple[float, float]]:
    """Each country's point on the globe, for countries without job pins."""
    return {row["code"]: (row["lat"], row["lon"]) for row in load_countries()}


class City(BaseModel):
    name: str
    lat: float
    lon: float
    job_count: int


class CountryOut(BaseModel):
    code: str
    name: str
    region: str | None
    subregion: str | None
    region_groups: list[str]
    lat: float
    lon: float
    job_count: int  # jobs a filter on this country returns (worldwide-remote not included)
    local_job_count: int  # jobs located in the country
    cities: list[City]


class CountriesOut(BaseModel):
    data: list[CountryOut]
    meta: dict[str, int]


class PlatformOut(BaseModel):
    slug: str
    name: str
    kind: str
    status: str
    boards: int
    job_count: int
    last_success_at: datetime | None
    fetch_success_rate_24h: float | None


class PlatformsOut(BaseModel):
    data: list[PlatformOut]


class StatsOut(BaseModel):
    total_jobs: int
    remote_jobs: int
    worldwide_remote_jobs: int
    countries_with_jobs: int
    sources_live: int
    boards_tracked: int
    last_refresh_at: datetime | None
    refresh_lag_minutes: float | None


def _search(
    search: OpenSearch, alias: str, aggs: dict[str, Any], query: dict[str, Any] | None = None
) -> Any:
    body = {
        "size": 0,
        "track_total_hits": True,
        "query": query or {"term": {"status": "open"}},
        "aggs": aggs,
    }
    return search.search(index=alias, body=body)


@router.get(
    "/countries", response_model=CountriesOut, summary="All 233 countries with live job counts"
)
def countries(
    db: Annotated[Engine, Depends(engine)],
    search: Annotated[OpenSearch, Depends(search_client)],
    alias: Annotated[str, Depends(search_alias)],
) -> dict[str, Any]:
    result = _search(
        search,
        alias,
        {
            "filterable": {"terms": {"field": "filter_countries", "size": 300}},
            "worldwide": {"filter": {"term": {"worldwide": True}}},
            "local": {
                "terms": {"field": "country_code", "size": 300},
                "aggs": {
                    "cities": {
                        "terms": {"field": "city", "size": 3},
                        "aggs": {"centre": {"geo_centroid": {"field": "location"}}},
                    }
                },
            },
        },
    )
    aggs = result["aggregations"]
    filterable = {b["key"]: b["doc_count"] for b in aggs["filterable"]["buckets"]}
    local = {b["key"]: b for b in aggs["local"]["buckets"]}

    centres = _centres()
    with Session(db) as session:
        rows = session.scalars(select(Country).order_by(Country.name)).all()
    data = []
    for country in rows:
        bucket = local.get(country.code)
        cities = []
        for city in (bucket or {}).get("cities", {}).get("buckets", []):
            centre = city["centre"].get("location")
            if centre:
                cities.append(
                    {
                        "name": city["key"],
                        "lat": centre["lat"],
                        "lon": centre["lon"],
                        "job_count": city["doc_count"],
                    }
                )
        lat, lon = centres[country.code]
        data.append(
            {
                "code": country.code,
                "name": country.name,
                "region": country.region,
                "subregion": country.subregion,
                "region_groups": country.region_groups,
                "lat": lat,
                "lon": lon,
                "job_count": filterable.get(country.code, 0),
                "local_job_count": bucket["doc_count"] if bucket else 0,
                "cities": cities,
            }
        )
    return {
        "data": data,
        "meta": {
            "countries": len(data),
            "countries_with_jobs": sum(1 for c in data if c["local_job_count"]),
            "worldwide_remote_jobs": aggs["worldwide"]["doc_count"],
        },
    }


def _platform_status(source: Source, last_success: datetime | None, now: datetime) -> str:
    if source.status == "paused":
        return "paused"
    if source.slug not in CONNECTORS:
        return "scheduled"
    if last_success and now - last_success <= LIVE_WITHIN:
        return "live"
    return "indexing"


@router.get(
    "/platforms", response_model=PlatformsOut, summary="Sources with live status and job counts"
)
def platforms(
    db: Annotated[Engine, Depends(engine)],
    search: Annotated[OpenSearch, Depends(search_client)],
    alias: Annotated[str, Depends(search_alias)],
) -> dict[str, Any]:
    now = datetime.now(UTC)
    jobs = {
        b["key"]: b["doc_count"]
        for b in _search(search, alias, {"s": {"terms": {"field": "sources", "size": 100}}})[
            "aggregations"
        ]["s"]["buckets"]
    }
    with Session(db) as session:
        boards = dict(
            session.execute(
                select(CompanyBoard.source_slug, func.count()).group_by(CompanyBoard.source_slug)
            )
            .tuples()
            .all()
        )
        last_ok = dict(
            session.execute(
                select(CompanyBoard.source_slug, func.max(CompanyBoard.last_ok_at)).group_by(
                    CompanyBoard.source_slug
                )
            )
            .tuples()
            .all()
        )
        runs = {
            slug: (ok, total)
            for slug, ok, total in session.execute(
                select(
                    CompanyBoard.source_slug,
                    func.count().filter(CrawlRun.outcome == "ok"),
                    func.count(),
                )
                .join(CompanyBoard, CompanyBoard.id == CrawlRun.board_id)
                .where(
                    CrawlRun.started_at > now - timedelta(hours=24), CrawlRun.outcome.is_not(None)
                )
                .group_by(CompanyBoard.source_slug)
            ).tuples()
        }
        sources = session.scalars(
            select(Source).order_by(
                case((Source.slug.in_(list(CONNECTORS)), 0), else_=1), Source.name
            )
        ).all()
    data = []
    for source in sources:
        ok, total = runs.get(source.slug, (0, 0))
        data.append(
            {
                "slug": source.slug,
                "name": source.name,
                "kind": source.kind,
                "status": _platform_status(source, last_ok.get(source.slug), now),
                "boards": boards.get(source.slug, 0),
                "job_count": jobs.get(source.slug, 0),
                "last_success_at": last_ok.get(source.slug),
                "fetch_success_rate_24h": round(ok / total, 4) if total else None,
            }
        )
    return {"data": data}


@router.get("/stats", response_model=StatsOut, summary="Totals and refresh lag for the Home page")
def stats(
    db: Annotated[Engine, Depends(engine)],
    search: Annotated[OpenSearch, Depends(search_client)],
    alias: Annotated[str, Depends(search_alias)],
) -> dict[str, Any]:
    now = datetime.now(UTC)
    aggs = _search(
        search,
        alias,
        {
            "remote": {"filter": {"term": {"remote_status": "remote"}}},
            "worldwide": {"filter": {"term": {"worldwide": True}}},
            "countries": {"cardinality": {"field": "country_code"}},
        },
    )
    with Session(db) as session:
        boards_tracked = session.scalar(select(func.count()).select_from(CompanyBoard)) or 0
        last_ok = [
            ok
            for ok in session.scalars(
                select(CompanyBoard.last_ok_at).where(CompanyBoard.last_ok_at.is_not(None))
            )
            if ok is not None
        ]
    ages = sorted((now - ok).total_seconds() / 60 for ok in last_ok)
    live_sources = {
        p["slug"] for p in platforms(db, search, alias)["data"] if p["status"] == "live"
    }
    return {
        "total_jobs": aggs["hits"]["total"]["value"],
        "remote_jobs": aggs["aggregations"]["remote"]["doc_count"],
        "worldwide_remote_jobs": aggs["aggregations"]["worldwide"]["doc_count"],
        "countries_with_jobs": aggs["aggregations"]["countries"]["value"],
        "sources_live": len(live_sources),
        "boards_tracked": boards_tracked,
        "last_refresh_at": max(last_ok) if last_ok else None,
        "refresh_lag_minutes": round(ages[len(ages) // 2], 1) if ages else None,
    }
