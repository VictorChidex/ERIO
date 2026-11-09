"""The anonymous workspace API: /v1/workspace/*, and the public Atom feeds at /v1/feeds/*.

No account and no email. ``POST /v1/workspace`` makes a workspace and returns its
token once; the browser keeps it and sends it as ``X-Workspace-Token``. The database holds
only the token's SHA-256. Everything under a workspace is deleted with it.
"""

import base64
import hashlib
import os
import re
import time
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any, Literal
from xml.etree import ElementTree

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from opensearchpy import OpenSearch
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError
from redis import Redis
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from erio_api.access import _SLIDING_WINDOW, WINDOW_S, Caller, hash_token, rate_limit, redis_client
from erio_api.deps import engine, search_alias, search_client
from erio_api.errors import ApiError
from erio_core import saved_search
from erio_core.db.models import Company, Job
from erio_core.db.workspace_models import (
    APPLICATION_STAGES,
    EVENT_KINDS,
    MAX_APPLICATIONS,
    MAX_EVENTS_PER_APPLICATION,
    MAX_NOTE_BYTES,
    MAX_NOTES_TOTAL_BYTES,
    MAX_SAVED,
    MAX_SEARCHES,
    RETENTION_DAYS,
    Application,
    ApplicationEvent,
    SavedSearch,
    SavedSearchMatch,
    Workspace,
)
from erio_core.search.params import SearchParams
from erio_core.settings import get_settings
from erio_core.webhook import WebhookRejected, validate_url

TOKEN_PREFIX = "erw_"  # noqa: S105 (a public label, not a credential)
TOKEN_PATTERN = re.compile(r"^erw_[A-Za-z0-9_-]{43}$")
TOUCH_EVERY = timedelta(hours=1)
WORKSPACE_PER_MINUTE = 240
CREATE_PER_MINUTE = 30
MAX_WORKSPACES = 500_000
MAX_BODY = 128 * 1024
MAX_IMPORT_BODY = 2 * 1024 * 1024
STAGE_NUDGE_DAYS = {"applied": 14, "interviewing": 10}

Stage = Literal["saved", "applied", "interviewing", "offer", "rejected", "withdrawn"]
Line = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]

router = APIRouter(prefix="/v1/workspace", tags=["workspace"])
feeds = APIRouter(prefix="/v1/feeds", tags=["workspace"], dependencies=[Depends(rate_limit)])

LIMITS = {
    "applications": MAX_APPLICATIONS,
    "saved": MAX_SAVED,
    "searches": MAX_SEARCHES,
    "note_bytes": MAX_NOTE_BYTES,
    "notes_total_bytes": MAX_NOTES_TOTAL_BYTES,
    "retention_days": RETENTION_DAYS,
}


def now() -> datetime:
    return datetime.now(UTC)


def new_token() -> str:
    """256 random bits from the operating system, as a URL-safe string."""
    return TOKEN_PREFIX + base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()


# --- access ---------------------------------------------------------------------------------


def _count(redis: Redis, key: str, limit: int) -> tuple[bool, int]:
    allowed, _, reset = redis.register_script(_SLIDING_WINDOW)(
        keys=[f"erio:rate:{key}"],
        args=[limit, WINDOW_S, f"{time.time()}:{uuid.uuid4().hex}"],
    )
    return bool(int(allowed)), max(1, int(float(reset)) + 1)


def bucket_limit(redis: Redis, key: str, limit: int, what: str) -> None:
    allowed, retry = _count(redis, key, limit)
    if not allowed:
        raise ApiError(
            429,
            "rate_limited",
            f"too many {what}; try again shortly",
            {"Retry-After": str(retry)},
        )


async def small_body(request: Request) -> None:
    await _check_body(request, MAX_BODY)


async def import_body(request: Request) -> None:
    await _check_body(request, MAX_IMPORT_BODY)


async def _check_body(request: Request, limit: int) -> None:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise ApiError(413, "too_large", f"request body is over {limit // 1024} KB")
    if len(await request.body()) > limit:
        raise ApiError(413, "too_large", f"request body is over {limit // 1024} KB")


def current_workspace(
    request: Request,
    db: Annotated[Engine, Depends(engine)],
    redis: Annotated[Redis, Depends(redis_client)],
    _: Annotated[Caller, Depends(rate_limit)],
) -> int:
    """The workspace id for this request's token, counted against that workspace's own limit."""
    token = request.headers.get("x-workspace-token", "")
    if not TOKEN_PATTERN.match(token):
        raise ApiError(401, "invalid_workspace", "send your workspace token as X-Workspace-Token")
    with Session(db) as session, session.begin():
        row = session.scalars(
            select(Workspace).where(Workspace.token_hash == hash_token(token))
        ).one_or_none()
        if row is None:
            raise ApiError(401, "invalid_workspace", "no workspace for that token (deleted?)")
        workspace_id = row.id
        if now() - row.last_used_at > TOUCH_EVERY:
            row.last_used_at = now()
    bucket_limit(
        redis, f"workspace:{workspace_id}", WORKSPACE_PER_MINUTE, "requests for this workspace"
    )
    return workspace_id


WorkspaceId = Annotated[int, Depends(current_workspace)]
Db = Annotated[Engine, Depends(engine)]


# --- shapes ---------------------------------------------------------------------------------


class EventOut(BaseModel):
    id: int
    at: datetime
    kind: str
    stage: str | None
    text: str | None


class JobState(BaseModel):
    status: str | None  # the job's status now; null when ERIO no longer lists it
    closed_at: datetime | None
    changes: list[str]  # what changed since the person last looked


class ApplicationOut(BaseModel):
    id: int
    job_id: str | None
    title: str
    company: str
    location: str | None
    url: str | None
    stage: str
    notes: str
    applied_on: date | None
    follow_up_on: date | None
    stage_changed_at: datetime
    created_at: datetime
    updated_at: datetime
    job: JobState | None
    nudge: str | None
    events: list[EventOut] | None = None


class ApplicationsOut(BaseModel):
    data: list[ApplicationOut]


class ApplicationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,40}$")] | None = None
    title: Line | None = None
    company: Line | None = None
    location: Annotated[str, StringConstraints(max_length=300)] | None = None
    url: Annotated[str, StringConstraints(max_length=2000, pattern=r"^https?://")] | None = None
    stage: Stage = "saved"
    notes: str = Field(default="", max_length=MAX_NOTE_BYTES)
    applied_on: date | None = None
    follow_up_on: date | None = None


class ApplicationPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Line | None = None
    company: Line | None = None
    location: Annotated[str, StringConstraints(max_length=300)] | None = None
    url: Annotated[str, StringConstraints(max_length=2000, pattern=r"^https?://|^$")] | None = None
    stage: Stage | None = None
    notes: str | None = Field(default=None, max_length=MAX_NOTE_BYTES)
    applied_on: date | None = None
    follow_up_on: date | None = None
    clear_follow_up: bool = False


class EventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class SearchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Line
    params: SearchParams
    webhook_url: Annotated[str, StringConstraints(max_length=2000)] | None = None


class SearchPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Line | None = None
    webhook_url: Annotated[str, StringConstraints(max_length=2000)] | None = None
    clear_webhook: bool = False


class SearchOut(BaseModel):
    id: int
    name: str
    params: dict[str, Any]
    feed_token: str
    webhook_url: str | None
    webhook_disabled: bool
    webhook_failures: int
    created_at: datetime
    last_evaluated_at: datetime
    last_viewed_at: datetime
    new_count: int


class MatchOut(BaseModel):
    job_id: str
    title: str
    company: str
    location: str | None
    apply_url: str
    posted_at: datetime | None
    matched_at: datetime
    is_new: bool


# --- workspace ------------------------------------------------------------------------------


class Created(BaseModel):
    token: str
    limits: dict[str, int]


@router.post("", response_model=Created, status_code=201, summary="Create an anonymous workspace")
def create_workspace(
    db: Db,
    redis: Annotated[Redis, Depends(redis_client)],
    caller: Annotated[Caller, Depends(rate_limit)],
) -> dict[str, Any]:
    """Returns the token once. ERIO keeps only its SHA-256; lose the token and the workspace
    cannot be recovered (use the workspace link or an export to keep a copy)."""
    bucket_limit(redis, f"workspace-create:{caller.key}", CREATE_PER_MINUTE, "new workspaces")
    token = new_token()
    with Session(db) as session, session.begin():
        total = session.scalar(select(func.count()).select_from(Workspace)) or 0
        if total >= MAX_WORKSPACES:
            raise ApiError(503, "workspaces_full", "no new workspaces can be made right now")
        session.add(Workspace(token_hash=hash_token(token)))
    return {"token": token, "limits": LIMITS}


class Summary(BaseModel):
    created_at: datetime
    last_used_at: datetime
    counts: dict[str, int]
    limits: dict[str, int]


def _summary(session: Session, workspace_id: int) -> dict[str, Any]:
    ws = session.get_one(Workspace, workspace_id)
    stages = dict(
        session.execute(
            select(Application.stage, func.count())
            .where(Application.workspace_id == workspace_id)
            .group_by(Application.stage)
        ).all()
    )
    searches = (
        session.scalar(
            select(func.count())
            .select_from(SavedSearch)
            .where(SavedSearch.workspace_id == workspace_id)
        )
        or 0
    )
    return {
        "created_at": ws.created_at,
        "last_used_at": ws.last_used_at,
        "counts": {"applications": sum(stages.values()), "searches": searches}
        | {stage: stages.get(stage, 0) for stage in APPLICATION_STAGES},
        "limits": LIMITS,
    }


@router.get("", response_model=Summary, summary="Counts and limits for this workspace")
def get_workspace(workspace_id: WorkspaceId, db: Db) -> dict[str, Any]:
    with Session(db) as session:
        return _summary(session, workspace_id)


@router.delete("", status_code=204, summary="Delete the workspace and everything in it")
def delete_workspace(workspace_id: WorkspaceId, db: Db) -> Response:
    with Session(db) as session, session.begin():
        session.delete(session.get_one(Workspace, workspace_id))
    return Response(status_code=204)


# --- applications ---------------------------------------------------------------------------


def _digest(job: Job) -> str:
    raw = "|".join(
        str(part)
        for part in (job.title, job.location_text, job.apply_url, job.salary_min, job.salary_max)
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _jobs_by_id(session: Session, job_ids: list[str]) -> dict[str, Job]:
    if not job_ids:
        return {}
    rows = session.scalars(select(Job).where(Job.canonical_id.in_(job_ids)))
    return {job.canonical_id: job for job in rows}


def _job_state(app: Application, job: Job | None) -> JobState | None:
    if app.job_id is None:
        return None
    if job is None:
        return JobState(status=None, closed_at=None, changes=["no longer listed"])
    changes = []
    if app.seen_status and job.status != app.seen_status:
        changes.append(
            "closed"
            if job.status == "closed"
            else "open again"
            if job.status == "open"
            else job.status
        )
    if app.seen_digest and _digest(job) != app.seen_digest:
        changes.append("details changed")
    return JobState(status=job.status, closed_at=job.closed_at, changes=changes)


def _nudge(app: Application, today: date, moment: datetime) -> str | None:
    if app.stage in ("rejected", "withdrawn", "offer"):
        return None
    if app.follow_up_on is not None and app.follow_up_on <= today:
        days = (today - app.follow_up_on).days
        return "Follow-up due today" if days == 0 else f"Follow-up was due {days} days ago"
    limit = STAGE_NUDGE_DAYS.get(app.stage)
    if limit is not None:
        idle = (moment - app.updated_at).days
        if idle >= limit:
            return f"No movement for {idle} days"
    return None


def _application_out(
    app: Application, job: Job | None, events: list[ApplicationEvent] | None = None
) -> ApplicationOut:
    moment = now()
    return ApplicationOut(
        id=app.id,
        job_id=app.job_id,
        title=app.title,
        company=app.company,
        location=app.location,
        url=app.url,
        stage=app.stage,
        notes=app.notes,
        applied_on=app.applied_on,
        follow_up_on=app.follow_up_on,
        stage_changed_at=app.stage_changed_at,
        created_at=app.created_at,
        updated_at=app.updated_at,
        job=_job_state(app, job),
        nudge=_nudge(app, moment.date(), moment),
        events=None
        if events is None
        else [EventOut.model_validate(e, from_attributes=True) for e in events],
    )


def _own(session: Session, workspace_id: int, application_id: int) -> Application:
    app = session.scalars(
        select(Application).where(
            Application.id == application_id, Application.workspace_id == workspace_id
        )
    ).one_or_none()
    if app is None:
        raise ApiError(404, "not_found", "no such saved job or application")
    return app


def _event(
    session: Session, app: Application, kind: str, *, stage: str | None = None, text: str | None
) -> None:
    assert kind in EVENT_KINDS  # noqa: S101 (a programming error, not input)
    count = (
        session.scalar(
            select(func.count())
            .select_from(ApplicationEvent)
            .where(ApplicationEvent.application_id == app.id)
        )
        or 0
    )
    if count < MAX_EVENTS_PER_APPLICATION:
        session.add(ApplicationEvent(application_id=app.id, kind=kind, stage=stage, text=text))


def _notes_total(session: Session, workspace_id: int) -> int:
    return (
        session.scalar(
            select(func.coalesce(func.sum(func.octet_length(Application.notes)), 0)).where(
                Application.workspace_id == workspace_id
            )
        )
        or 0
    )


def _check_caps(session: Session, workspace_id: int, stage: str, extra_notes: int = 0) -> None:
    total = (
        session.scalar(
            select(func.count())
            .select_from(Application)
            .where(Application.workspace_id == workspace_id)
        )
        or 0
    )
    if total >= MAX_APPLICATIONS:
        raise ApiError(409, "limit_reached", f"a workspace holds at most {MAX_APPLICATIONS} items")
    if stage == "saved":
        saved = (
            session.scalar(
                select(func.count())
                .select_from(Application)
                .where(Application.workspace_id == workspace_id, Application.stage == "saved")
            )
            or 0
        )
        if saved >= MAX_SAVED:
            raise ApiError(
                409, "limit_reached", f"at most {MAX_SAVED} saved jobs; move or remove some"
            )
    if extra_notes and _notes_total(session, workspace_id) + extra_notes > MAX_NOTES_TOTAL_BYTES:
        raise ApiError(409, "limit_reached", "this workspace's notes are full")


def _apply_stage(app: Application, stage: str, session: Session, moment: datetime) -> None:
    if stage == app.stage:
        return
    app.stage = stage
    app.stage_changed_at = moment
    if stage == "applied" and app.applied_on is None:
        app.applied_on = moment.date()
    _event(session, app, "stage", stage=stage, text=None)


def _resolve_job(session: Session, job_id: str) -> Job:
    job = session.get(Job, job_id)
    for _ in range(3):  # a merged job lives on under the survivor
        if job is None or job.merged_into is None:
            break
        job = session.get(Job, job.merged_into)
    if job is None or job.review_reason is not None:
        raise ApiError(404, "not_found", f"no job {job_id}")
    return job


@router.get("/applications", response_model=ApplicationsOut, summary="Saved jobs and applications")
def list_applications(
    workspace_id: WorkspaceId,
    db: Db,
    stage: Annotated[Stage | None, Query()] = None,
) -> dict[str, Any]:
    with Session(db) as session:
        query = select(Application).where(Application.workspace_id == workspace_id)
        if stage:
            query = query.where(Application.stage == stage)
        apps = session.scalars(query.order_by(Application.updated_at.desc())).all()
        jobs = _jobs_by_id(session, [a.job_id for a in apps if a.job_id])
        return {"data": [_application_out(a, jobs.get(a.job_id or "")) for a in apps]}


@router.get("/saved-ids", summary="Job ids in this workspace (so a page can mark saved jobs)")
def saved_ids(workspace_id: WorkspaceId, db: Db) -> dict[str, list[str]]:
    with Session(db) as session:
        ids = session.scalars(
            select(Application.job_id).where(
                Application.workspace_id == workspace_id, Application.job_id.is_not(None)
            )
        ).all()
    return {"job_ids": [i for i in ids if i]}


@router.post(
    "/applications",
    response_model=ApplicationOut,
    status_code=201,
    dependencies=[Depends(small_body)],
    summary="Save a job, or add an application made elsewhere",
)
def create_application(body: ApplicationIn, workspace_id: WorkspaceId, db: Db) -> ApplicationOut:
    with Session(db) as session, session.begin():
        _check_caps(session, workspace_id, body.stage, len(body.notes.encode()))
        job: Job | None = None
        values: dict[str, Any] = {
            "title": body.title,
            "company": body.company,
            "location": body.location,
            "url": body.url,
        }
        if body.job_id:
            job = _resolve_job(session, body.job_id)
            employer = session.get(Company, job.company_id)
            company = employer.name if employer else None
            values = {
                "title": job.title,
                "company": company or body.company or "Unknown employer",
                "location": job.location_text,
                "url": job.apply_url,
            }
            existing = session.scalars(
                select(Application).where(
                    Application.workspace_id == workspace_id, Application.job_id == job.canonical_id
                )
            ).one_or_none()
            if existing is not None:
                return _application_out(existing, job)
        if not values["title"] or not values["company"]:
            raise ApiError(400, "invalid_parameter", "title and company are required")
        moment = now()
        app = Application(
            workspace_id=workspace_id,
            job_id=job.canonical_id if job else None,
            stage=body.stage,
            notes=body.notes,
            applied_on=body.applied_on or (moment.date() if body.stage == "applied" else None),
            follow_up_on=body.follow_up_on,
            stage_changed_at=moment,
            created_at=moment,
            updated_at=moment,
            seen_status=job.status if job else None,
            seen_digest=_digest(job) if job else None,
            **values,
        )
        session.add(app)
        session.flush()
        _event(session, app, "created", stage=body.stage, text=None)
        session.flush()
        return _application_out(app, job)


@router.get("/applications/{application_id}", response_model=ApplicationOut)
def get_application(application_id: int, workspace_id: WorkspaceId, db: Db) -> ApplicationOut:
    with Session(db) as session:
        app = _own(session, workspace_id, application_id)
        events = list(
            session.scalars(
                select(ApplicationEvent)
                .where(ApplicationEvent.application_id == app.id)
                .order_by(ApplicationEvent.at.desc(), ApplicationEvent.id.desc())
            )
        )
        job = session.get(Job, app.job_id) if app.job_id else None
        return _application_out(app, job, events)


@router.patch(
    "/applications/{application_id}",
    response_model=ApplicationOut,
    dependencies=[Depends(small_body)],
)
def update_application(
    application_id: int, body: ApplicationPatch, workspace_id: WorkspaceId, db: Db
) -> ApplicationOut:
    with Session(db) as session, session.begin():
        app = _own(session, workspace_id, application_id)
        moment = now()
        if (
            body.stage
            and body.stage != app.stage
            and (body.stage == "saved" and app.stage != "saved")
        ):
            _check_caps_saved_only(session, workspace_id)
        if body.notes is not None:
            growth = len(body.notes.encode()) - len(app.notes.encode())
            if growth > 0 and _notes_total(session, workspace_id) + growth > MAX_NOTES_TOTAL_BYTES:
                raise ApiError(409, "limit_reached", "this workspace's notes are full")
            if body.notes != app.notes:
                app.notes = body.notes
        for name in ("title", "company", "location"):
            value = getattr(body, name)
            if value is not None:
                setattr(app, name, value)
        if body.url is not None:
            app.url = body.url or None
        if body.applied_on is not None:
            app.applied_on = body.applied_on
        if body.clear_follow_up:
            app.follow_up_on = None
        elif body.follow_up_on is not None and body.follow_up_on != app.follow_up_on:
            app.follow_up_on = body.follow_up_on
            _event(session, app, "reminder", text=f"Follow up on {body.follow_up_on.isoformat()}")
        if body.stage:
            _apply_stage(app, body.stage, session, moment)
        app.updated_at = moment
        session.flush()
        job = session.get(Job, app.job_id) if app.job_id else None
        return _application_out(app, job)


def _check_caps_saved_only(session: Session, workspace_id: int) -> None:
    saved = (
        session.scalar(
            select(func.count())
            .select_from(Application)
            .where(Application.workspace_id == workspace_id, Application.stage == "saved")
        )
        or 0
    )
    if saved >= MAX_SAVED:
        raise ApiError(409, "limit_reached", f"at most {MAX_SAVED} saved jobs; move or remove some")


@router.delete("/applications/{application_id}", status_code=204)
def delete_application(application_id: int, workspace_id: WorkspaceId, db: Db) -> Response:
    with Session(db) as session, session.begin():
        session.delete(_own(session, workspace_id, application_id))
    return Response(status_code=204)


@router.post(
    "/applications/{application_id}/events",
    response_model=ApplicationOut,
    status_code=201,
    dependencies=[Depends(small_body)],
    summary="Add a line to the timeline",
)
def add_event(
    application_id: int, body: EventIn, workspace_id: WorkspaceId, db: Db
) -> ApplicationOut:
    with Session(db) as session, session.begin():
        app = _own(session, workspace_id, application_id)
        _event(session, app, "note", text=body.text)
        app.updated_at = now()
        session.flush()
        return _application_out(app, None)


@router.post("/applications/{application_id}/ack", response_model=ApplicationOut)
def acknowledge_job_change(
    application_id: int, workspace_id: WorkspaceId, db: Db
) -> ApplicationOut:
    """Mark the job's current state as seen, and put what changed on the timeline."""
    with Session(db) as session, session.begin():
        app = _own(session, workspace_id, application_id)
        job = session.get(Job, app.job_id) if app.job_id else None
        state = _job_state(app, job)
        if job is not None and state is not None and state.changes:
            kind = (
                "job_closed"
                if job.status == "closed"
                else "job_reopened"
                if "open again" in state.changes
                else "job_changed"
            )
            _event(session, app, kind, text="; ".join(state.changes))
            app.seen_status = job.status
            app.seen_digest = _digest(job)
        session.flush()
        return _application_out(app, job)


# --- saved searches -------------------------------------------------------------------------


def _check_webhook(url: str | None) -> str | None:
    if not url:
        return None
    try:
        return validate_url(url)
    except WebhookRejected as error:
        raise ApiError(400, "invalid_webhook", f"webhook address refused: {error}") from error


def _search_out(session: Session, search: SavedSearch) -> SearchOut:
    return SearchOut(
        id=search.id,
        name=search.name,
        params=search.params,
        feed_token=search.feed_token,
        webhook_url=search.webhook_url,
        webhook_disabled=search.webhook_disabled,
        webhook_failures=search.webhook_failures,
        created_at=search.created_at,
        last_evaluated_at=search.last_evaluated_at,
        last_viewed_at=search.last_viewed_at,
        new_count=saved_search.new_count(session, search),
    )


def _own_search(session: Session, workspace_id: int, search_id: int) -> SavedSearch:
    found = session.scalars(
        select(SavedSearch).where(
            SavedSearch.id == search_id, SavedSearch.workspace_id == workspace_id
        )
    ).one_or_none()
    if found is None:
        raise ApiError(404, "not_found", "no such saved search")
    return found


def _new_search(
    session: Session,
    workspace_id: int,
    name: str,
    params: SearchParams,
    webhook_url: str | None,
    client: OpenSearch,
    alias: str,
) -> SavedSearch:
    total = (
        session.scalar(
            select(func.count())
            .select_from(SavedSearch)
            .where(SavedSearch.workspace_id == workspace_id)
        )
        or 0
    )
    if total >= MAX_SEARCHES:
        raise ApiError(409, "limit_reached", f"a workspace holds at most {MAX_SEARCHES} searches")
    moment = now()
    search = SavedSearch(
        workspace_id=workspace_id,
        name=name,
        params=params.model_dump(mode="json", exclude_defaults=True),
        feed_token=base64.urlsafe_b64encode(os.urandom(24)).decode(),
        webhook_url=webhook_url,
        created_at=moment,
        last_evaluated_at=moment,
        last_viewed_at=moment,
    )
    session.add(search)
    session.flush()
    saved_search.baseline(session, search, client, alias, moment)
    return search


@router.get("/searches", response_model=list[SearchOut], summary="Saved searches with new counts")
def list_searches(workspace_id: WorkspaceId, db: Db) -> list[SearchOut]:
    with Session(db) as session:
        rows = session.scalars(
            select(SavedSearch)
            .where(SavedSearch.workspace_id == workspace_id)
            .order_by(SavedSearch.id)
        ).all()
        return [_search_out(session, s) for s in rows]


@router.post(
    "/searches",
    response_model=SearchOut,
    status_code=201,
    dependencies=[Depends(small_body)],
    summary="Save a search: new-match counter, Atom feed, optional webhook",
)
def create_search(
    body: SearchIn,
    workspace_id: WorkspaceId,
    db: Db,
    client: Annotated[OpenSearch, Depends(search_client)],
    alias: Annotated[str, Depends(search_alias)],
) -> SearchOut:
    webhook = _check_webhook(body.webhook_url)
    with Session(db) as session, session.begin():
        search = _new_search(session, workspace_id, body.name, body.params, webhook, client, alias)
        return _search_out(session, search)


@router.patch("/searches/{search_id}", response_model=SearchOut, dependencies=[Depends(small_body)])
def update_search(
    search_id: int, body: SearchPatch, workspace_id: WorkspaceId, db: Db
) -> SearchOut:
    webhook = _check_webhook(body.webhook_url)
    with Session(db) as session, session.begin():
        search = _own_search(session, workspace_id, search_id)
        if body.name:
            search.name = body.name
        if body.clear_webhook:
            search.webhook_url = None
            search.webhook_disabled = False
            search.webhook_failures = 0
        elif webhook:
            search.webhook_url = webhook
            search.webhook_disabled = False
            search.webhook_failures = 0
        session.flush()
        return _search_out(session, search)


@router.delete("/searches/{search_id}", status_code=204)
def delete_search(search_id: int, workspace_id: WorkspaceId, db: Db) -> Response:
    with Session(db) as session, session.begin():
        session.delete(_own_search(session, workspace_id, search_id))
    return Response(status_code=204)


@router.post(
    "/searches/{search_id}/seen", response_model=SearchOut, summary="Reset the new counter"
)
def mark_seen(search_id: int, workspace_id: WorkspaceId, db: Db) -> SearchOut:
    with Session(db) as session, session.begin():
        search = _own_search(session, workspace_id, search_id)
        search.last_viewed_at = now()
        session.flush()
        return _search_out(session, search)


@router.get("/searches/{search_id}/matches", response_model=list[MatchOut])
def search_matches(search_id: int, workspace_id: WorkspaceId, db: Db) -> list[MatchOut]:
    with Session(db) as session:
        search = _own_search(session, workspace_id, search_id)
        rows = session.scalars(
            select(SavedSearchMatch)
            .where(SavedSearchMatch.search_id == search.id)
            .order_by(SavedSearchMatch.matched_at.desc(), SavedSearchMatch.id.desc())
            .limit(50)
        ).all()
        return [
            MatchOut(
                job_id=m.job_id,
                title=m.title,
                company=m.company,
                location=m.location,
                apply_url=m.apply_url,
                posted_at=m.posted_at,
                matched_at=m.matched_at,
                is_new=m.matched_at > search.last_viewed_at,
            )
            for m in rows
        ]


@router.post("/searches/{search_id}/test-webhook", summary="Send a test message to the webhook")
def test_webhook(
    search_id: int,
    workspace_id: WorkspaceId,
    db: Db,
    redis: Annotated[Redis, Depends(redis_client)],
) -> dict[str, Any]:
    from erio_core.webhook import deliver

    bucket_limit(redis, f"webhook-test:{workspace_id}", 6, "webhook tests")
    with Session(db) as session:
        search = _own_search(session, workspace_id, search_id)
        if not search.webhook_url:
            raise ApiError(400, "invalid_parameter", "this search has no webhook")
        body = saved_search.webhook_body(search, [], get_settings().site_url, now())
        result = deliver(search.webhook_url, body)
    return {"ok": result.ok, "status": result.status, "error": result.error}


# --- export and import ----------------------------------------------------------------------


class ExportEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    at: datetime
    kind: Literal[
        "created", "stage", "note", "reminder", "job_closed", "job_reopened", "job_changed"
    ]
    stage: str | None = Field(default=None, max_length=16)
    text: str | None = Field(default=None, max_length=2000)


class ExportApplication(BaseModel):
    model_config = ConfigDict(extra="ignore")

    job_id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,40}$")] | None = None
    title: Line
    company: Line
    location: str | None = Field(default=None, max_length=300)
    url: str | None = Field(default=None, max_length=2000)
    stage: Stage = "saved"
    notes: str = Field(default="", max_length=MAX_NOTE_BYTES)
    applied_on: date | None = None
    follow_up_on: date | None = None
    created_at: datetime | None = None
    events: list[ExportEvent] = Field(default_factory=list, max_length=MAX_EVENTS_PER_APPLICATION)


class ExportSearch(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: Line
    params: SearchParams
    webhook_url: str | None = Field(default=None, max_length=2000)


class WorkspaceExport(BaseModel):
    model_config = ConfigDict(extra="ignore")

    format: Literal["erio-workspace"] = "erio-workspace"
    version: Literal[1] = 1
    exported_at: datetime | None = None
    applications: list[ExportApplication] = Field(default_factory=list, max_length=MAX_APPLICATIONS)
    searches: list[ExportSearch] = Field(default_factory=list, max_length=MAX_SEARCHES)


@router.get(
    "/export", response_model=WorkspaceExport, summary="Everything in the workspace, as JSON"
)
def export_workspace(workspace_id: WorkspaceId, db: Db) -> dict[str, Any]:
    """Your data, to keep or to import elsewhere. CVs are never stored, so none is included."""
    with Session(db) as session:
        apps = session.scalars(
            select(Application)
            .where(Application.workspace_id == workspace_id)
            .order_by(Application.id)
        ).all()
        events: dict[int, list[ApplicationEvent]] = {}
        for event in session.scalars(
            select(ApplicationEvent)
            .join(Application, Application.id == ApplicationEvent.application_id)
            .where(Application.workspace_id == workspace_id)
            .order_by(ApplicationEvent.at, ApplicationEvent.id)
        ):
            events.setdefault(event.application_id, []).append(event)
        searches = session.scalars(
            select(SavedSearch)
            .where(SavedSearch.workspace_id == workspace_id)
            .order_by(SavedSearch.id)
        ).all()
        return {
            "format": "erio-workspace",
            "version": 1,
            "exported_at": now(),
            "applications": [
                {
                    "job_id": a.job_id,
                    "title": a.title,
                    "company": a.company,
                    "location": a.location,
                    "url": a.url,
                    "stage": a.stage,
                    "notes": a.notes,
                    "applied_on": a.applied_on,
                    "follow_up_on": a.follow_up_on,
                    "created_at": a.created_at,
                    "events": [
                        {"at": e.at, "kind": e.kind, "stage": e.stage, "text": e.text}
                        for e in events.get(a.id, [])
                    ],
                }
                for a in apps
            ],
            "searches": [
                {"name": s.name, "params": s.params, "webhook_url": s.webhook_url} for s in searches
            ],
        }


class ImportResult(BaseModel):
    applications_added: int
    applications_skipped: int
    searches_added: int
    searches_skipped: int
    notes: list[str]


@router.post(
    "/import",
    response_model=ImportResult,
    dependencies=[Depends(import_body)],
    summary="Add the items of an export to this workspace",
)
async def import_workspace(
    request: Request,
    workspace_id: WorkspaceId,
    db: Db,
    client: Annotated[OpenSearch, Depends(search_client)],
    alias: Annotated[str, Depends(search_alias)],
) -> ImportResult:
    try:
        data = WorkspaceExport.model_validate_json(await request.body())
    except ValidationError as error:
        problems = error.errors()
        where = ".".join(str(p) for p in problems[0]["loc"]) if problems else ""
        raise ApiError(400, "invalid_import", f"not an ERIO workspace export ({where})") from error
    return _import(db, workspace_id, data, client, alias)


def _import(
    db: Engine, workspace_id: int, data: WorkspaceExport, client: OpenSearch, alias: str
) -> ImportResult:
    result = ImportResult(
        applications_added=0, applications_skipped=0, searches_added=0, searches_skipped=0, notes=[]
    )
    with Session(db) as session, session.begin():
        have_jobs = set(
            session.scalars(
                select(Application.job_id).where(
                    Application.workspace_id == workspace_id, Application.job_id.is_not(None)
                )
            )
        )
        total = (
            session.scalar(
                select(func.count())
                .select_from(Application)
                .where(Application.workspace_id == workspace_id)
            )
            or 0
        )
        notes_used = _notes_total(session, workspace_id)
        for item in data.applications:
            size = len(item.notes.encode())
            if (
                (item.job_id and item.job_id in have_jobs)
                or total >= MAX_APPLICATIONS
                or notes_used + size > MAX_NOTES_TOTAL_BYTES
            ):
                result.applications_skipped += 1
                continue
            moment = now()
            app = Application(
                workspace_id=workspace_id,
                job_id=item.job_id,
                title=item.title,
                company=item.company,
                location=item.location,
                url=item.url if item.url and item.url.startswith(("http://", "https://")) else None,
                stage=item.stage,
                notes=item.notes,
                applied_on=item.applied_on,
                follow_up_on=item.follow_up_on,
                stage_changed_at=moment,
                created_at=item.created_at or moment,
                updated_at=moment,
            )
            session.add(app)
            session.flush()
            for event in item.events:
                session.add(
                    ApplicationEvent(
                        application_id=app.id,
                        at=event.at,
                        kind=event.kind,
                        stage=event.stage,
                        text=event.text,
                    )
                )
            if item.job_id:
                have_jobs.add(item.job_id)
            total += 1
            notes_used += size
            result.applications_added += 1
        for entry in data.searches:
            webhook: str | None = None
            if entry.webhook_url:
                try:
                    webhook = validate_url(entry.webhook_url)
                except WebhookRejected as error:
                    result.notes.append(f"webhook for '{entry.name}' dropped: {error}")
            try:
                _new_search(session, workspace_id, entry.name, entry.params, webhook, client, alias)
            except ApiError:
                result.searches_skipped += 1
                continue
            result.searches_added += 1
    return result


# --- Atom feeds -----------------------------------------------------------------------------

ATOM = "http://www.w3.org/2005/Atom"
XML_HEADER = b'<?xml version="1.0" encoding="utf-8"?>\n'


def _atom(search: SavedSearch, matches: list[SavedSearchMatch], site: str) -> bytes:
    ElementTree.register_namespace("", ATOM)

    def tag(name: str) -> str:
        return f"{{{ATOM}}}{name}"

    feed = ElementTree.Element(tag("feed"))
    ElementTree.SubElement(feed, tag("title")).text = f"ERIO: {search.name}"
    ElementTree.SubElement(
        feed, tag("subtitle")
    ).text = "New jobs matching a search saved in an ERIO workspace."
    # An id that does not reveal the feed address.
    ident = hashlib.sha256(search.feed_token.encode()).hexdigest()[:24]
    ElementTree.SubElement(feed, tag("id")).text = f"urn:erio:feed:{ident}"
    ElementTree.SubElement(feed, tag("link"), href=f"{site}/search", rel="alternate")
    updated = max([m.matched_at for m in matches], default=search.created_at)
    ElementTree.SubElement(feed, tag("updated")).text = updated.astimezone(UTC).isoformat()
    for match in matches:
        entry = ElementTree.SubElement(feed, tag("entry"))
        place = f" ({match.location})" if match.location else ""
        ElementTree.SubElement(
            entry, tag("title")
        ).text = f"{match.title} at {match.company}{place}"
        ElementTree.SubElement(entry, tag("id")).text = f"urn:erio:job:{match.job_id}"
        ElementTree.SubElement(entry, tag("link"), href=f"{site}/jobs/{match.job_id}")
        ElementTree.SubElement(entry, tag("updated")).text = match.matched_at.astimezone(
            UTC
        ).isoformat()
        ElementTree.SubElement(
            entry, tag("summary")
        ).text = f"{match.title} at {match.company}{place}. Apply: {match.apply_url}"
    xml: bytes = ElementTree.tostring(feed, "utf-8")
    return XML_HEADER + xml


@feeds.get(
    "/{feed_token}.atom",
    summary="Atom feed of a saved search (the address is the key; follow it in any reader)",
    response_class=Response,
)
def feed(feed_token: Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{20,48}$")], db: Db) -> Response:
    with Session(db) as session:
        search = session.scalars(
            select(SavedSearch).where(SavedSearch.feed_token == feed_token)
        ).one_or_none()
        if search is None:
            raise ApiError(404, "not_found", "no such feed")
        matches = list(
            session.scalars(
                select(SavedSearchMatch)
                .where(SavedSearchMatch.search_id == search.id)
                .order_by(SavedSearchMatch.matched_at.desc(), SavedSearchMatch.id.desc())
                .limit(50)
            )
        )
        body = _atom(search, matches, get_settings().site_url.rstrip("/"))
    return Response(body, media_type="application/atom+xml")
