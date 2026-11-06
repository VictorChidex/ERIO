"""POST /v1/search/refresh and GET /v1/search/refresh/{id}: a search that reads the live boards.

A search answers from the index at once. A refresh then asks ERIO to re-read the
employer boards behind that search's results, on the fast ``live`` queue, so a job
posted a minute ago appears within seconds. The caller polls the refresh until it
has finished and searches again when it found something new. The limits that keep
this polite (one refresh per distinct search, one read per board per cooldown, a
cap on boards and on the queue) are in ``erio_core.live``.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from functools import lru_cache
from typing import Annotated, Any, get_args

from celery import Celery
from fastapi import APIRouter, Depends, Path, Query
from opensearchpy import OpenSearch
from pydantic import BaseModel
from redis import Redis
from sqlalchemy import Engine, desc, func, or_, select
from sqlalchemy.orm import Session

from erio_api.access import rate_limit, redis_client
from erio_api.deps import engine, run_search, search_alias, search_client
from erio_api.errors import ApiError
from erio_api.routes.jobs import _check, _codes, _list
from erio_api.search import JobQuery, build_search
from erio_core import live
from erio_core.connectors import CONNECTORS
from erio_core.db.models import CompanyBoard, Job, Source
from erio_core.schemas import EmploymentType, RemoteStatus, RoleCategory
from erio_core.settings import get_settings

router = APIRouter(prefix="/v1", tags=["search"], dependencies=[Depends(rate_limit)])

# Boards are chosen from this many of the search's best matches.
SAMPLE = 100

Enqueue = Callable[[int, str], None]


class RefreshOut(BaseModel):
    id: str
    boards: int
    done: int
    new_postings: int
    changed_postings: int
    finished: bool
    shared: bool = False


@lru_cache
def _celery() -> Celery:
    return Celery("erio_api", broker=get_settings().redis_url)


def get_enqueue() -> Enqueue:
    def enqueue(board_id: int, refresh_id: str) -> None:
        _celery().send_task(live.TASK, args=[board_id, refresh_id], queue=live.QUEUE)

    return enqueue


def _out(refresh_id: str, state: dict[str, Any], shared: bool = False) -> dict[str, Any]:
    return {
        "id": refresh_id,
        "boards": state["boards"],
        "done": state["done"],
        "new_postings": state["new"],
        "changed_postings": state["changed"],
        "finished": state["finished"],
        "shared": shared,
    }


def _boards_for(db: Engine, job_ids: list[str], now: datetime) -> list[int]:
    """The boards behind these jobs, those with the most matches first."""
    if not job_ids:
        return []
    with Session(db) as session:
        rows = session.execute(
            select(CompanyBoard.id, func.count().label("matches"))
            .join(Job, Job.company_id == CompanyBoard.company_id)
            .join(Source, Source.slug == CompanyBoard.source_slug)
            .where(
                Job.canonical_id.in_(job_ids),
                CompanyBoard.source_slug.in_(list(CONNECTORS)),
                Source.status != "paused",
                or_(CompanyBoard.paused_until.is_(None), CompanyBoard.paused_until <= now),
            )
            .group_by(CompanyBoard.id)
            .order_by(desc("matches"), CompanyBoard.id)
            .limit(live.MAX_BOARDS * 3)
        ).all()
    return [board_id for board_id, _ in rows]


@router.post(
    "/search/refresh",
    response_model=RefreshOut,
    status_code=202,
    summary="Re-read the employer boards behind a search, now",
)
def start_refresh(
    db: Annotated[Engine, Depends(engine)],
    search: Annotated[OpenSearch, Depends(search_client)],
    alias: Annotated[str, Depends(search_alias)],
    redis: Annotated[Redis, Depends(redis_client)],
    enqueue: Annotated[Enqueue, Depends(get_enqueue)],
    q: Annotated[str | None, Query(max_length=200, description="Words to find")] = None,
    country: Annotated[str | None, Query(description="ISO codes, comma-separated")] = None,
    include_worldwide: Annotated[bool, Query()] = True,
    remote_status: Annotated[str | None, Query()] = None,
    role: Annotated[str | None, Query()] = None,
    salary_min_usd: Annotated[int | None, Query(ge=0)] = None,
    platform: Annotated[str | None, Query()] = None,
    company: Annotated[str | None, Query(max_length=200)] = None,
    location: Annotated[str | None, Query(max_length=200)] = None,
    employment_type: Annotated[str | None, Query()] = None,
) -> dict[str, Any]:
    query = JobQuery(
        q=q.strip() if q and q.strip() else None,
        countries=_codes(country),
        include_worldwide=include_worldwide,
        remote_status=_check(_list(remote_status), get_args(RemoteStatus), "remote_status"),
        roles=_check(_list(role), get_args(RoleCategory), "role"),
        salary_min_usd=salary_min_usd,
        platforms=_list(platform),
        company=company.strip() if company and company.strip() else None,
        location=location.strip() if location and location.strip() else None,
        employment_types=_check(
            _list(employment_type), get_args(EmploymentType), "employment_type"
        ),
        sort="recent",
        per_page=SAMPLE,
    )
    if not (query.q or query.company or query.location or query.roles or query.countries):
        raise ApiError(400, "invalid_parameter", "give a search (words, company, place or role)")
    identity = {
        k: v
        for k, v in vars(query).items()
        if k not in ("cursor", "per_page", "sort") and v not in (None, [], "")
    }

    held = live.running_for(redis, identity)
    if held and (state := live.read(redis, held)):
        return _out(held, state, shared=True)
    if live.queue_is_full(redis):
        raise ApiError(
            503, "busy", "live refresh is busy; try again shortly", {"Retry-After": "15"}
        )

    body = build_search(query)
    body.pop("aggs", None)
    body["_source"] = False
    response = run_search(search, alias, body)
    job_ids = [hit["_id"] for hit in response["hits"]["hits"]]
    candidates = _boards_for(db, job_ids, datetime.now(UTC))
    chosen = [b for b in candidates if live.claim_board(redis, b)][: live.MAX_BOARDS]

    refresh_id = live.start(redis, len(chosen))
    live.remember(redis, identity, refresh_id)
    for board_id in chosen:
        enqueue(board_id, refresh_id)
    state = {"boards": len(chosen), "done": 0, "new": 0, "changed": 0, "finished": not chosen}
    return _out(refresh_id, state)


@router.get(
    "/search/refresh/{refresh_id}",
    response_model=RefreshOut,
    summary="Progress of a refresh",
)
def refresh_status(
    refresh_id: Annotated[str, Path(pattern=r"^[0-9a-f]{32}$")],
    redis: Annotated[Redis, Depends(redis_client)],
) -> dict[str, Any]:
    state = live.read(redis, refresh_id)
    if state is None:
        raise ApiError(404, "not_found", "no such refresh (they expire after ten minutes)")
    return _out(refresh_id, state)
