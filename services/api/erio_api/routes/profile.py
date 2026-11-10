"""The workspace profile and email job alerts: /v1/workspace/profile, /mail and /v1/alerts/*.

A person uploads a CV; ERIO reads the skills out of it and throws the file away. The profile
keeps those skills, the titles and places wanted, and how the workspace looks. Alerts are
opt-in: an address receives nothing until the link in the first message is opened, and every
message links to a page (the ``manage`` token, which can do nothing else) that pauses the
emails or deletes the address.
"""

import base64
import hashlib
import os
import re
from datetime import datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Path, Query, Request, Response
from opensearchpy import OpenSearch
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from redis import Redis
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from erio_api.access import rate_limit, redis_client
from erio_api.cvfile import extract_text
from erio_api.deps import engine, search_alias, search_client
from erio_api.errors import ApiError
from erio_api.routes.workspace import Db, WorkspaceId, bucket_limit, now
from erio_core import skills
from erio_core.db.workspace_models import (
    PROFILE_SKILLS_MAX,
    PROFILE_TITLES_MAX,
    WorkspaceMail,
    WorkspaceProfile,
)
from erio_core.digest import CONFIRM_VALID, confirmation, rank_new_jobs
from erio_core.mail import MailError, send
from erio_core.settings import get_settings

EMAIL_PATTERN = re.compile(
    r"^[A-Za-z0-9._%+'-]{1,64}@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,24}$"
)
TOKEN_PATTERN = r"^[A-Za-z0-9_-]{20,64}$"  # noqa: S105 (a pattern, not a credential)
CV_PER_MINUTE = 10
CONFIRM_MAILS_PER_HOUR = 3
MAX_PREFS_BYTES = 2000
LOOKBACK = timedelta(days=30)

router = APIRouter(prefix="/v1/workspace", tags=["workspace"])
alerts = APIRouter(prefix="/v1/alerts", tags=["alerts"], dependencies=[Depends(rate_limit)])

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=80)]
Country = Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")]
Frequency = Literal["daily", "weekly"]


class SkillOut(BaseModel):
    id: str
    label: str
    cat: str


def _skills_out(ids: list[str]) -> list[SkillOut]:
    return [SkillOut(id=s.id, label=s.label, cat=s.cat) for i in ids if (s := skills.skill_for(i))]


class Prefs(BaseModel):
    """How the workspace looks. Small, fixed choices; nothing free-form is stored."""

    model_config = ConfigDict(extra="forbid")

    accent: Literal["default", "teal", "violet", "amber", "rose"] = "default"
    density: Literal["comfortable", "compact"] = "comfortable"
    start_tab: Literal["overview", "tracker", "searches", "cv"] = "overview"
    hidden_cards: list[Literal["stats", "next", "matches", "searches"]] = Field(
        default_factory=list, max_length=4
    )


class MailOut(BaseModel):
    email: str
    frequency: Frequency
    confirmed: bool
    paused: bool
    last_sent_at: datetime | None


class ProfileOut(BaseModel):
    skills: list[SkillOut]
    titles: list[str]
    countries: list[str]
    remote_only: bool
    min_score: int
    prefs: Prefs
    mail: MailOut | None


class ProfileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skills: list[str] | None = Field(default=None, max_length=PROFILE_SKILLS_MAX)
    titles: list[Title] | None = Field(default=None, max_length=PROFILE_TITLES_MAX)
    countries: list[Country] | None = Field(default=None, max_length=30)
    remote_only: bool | None = None
    min_score: int | None = Field(default=None, ge=10, le=90)
    prefs: Prefs | None = None


def _profile(session: Session, workspace_id: int) -> WorkspaceProfile:
    row = session.get(WorkspaceProfile, workspace_id)
    if row is None:
        row = WorkspaceProfile(
            workspace_id=workspace_id,
            skills=[],
            titles=[],
            countries=[],
            remote_only=False,
            min_score=40,
            prefs={},
            updated_at=now(),
        )
        session.add(row)
        session.flush()
    return row


def _mail_out(mail: WorkspaceMail | None) -> MailOut | None:
    if mail is None:
        return None
    return MailOut(
        email=mail.email,
        frequency=mail.frequency,  # type: ignore[arg-type]
        confirmed=mail.confirmed_at is not None,
        paused=mail.paused,
        last_sent_at=mail.last_sent_at,
    )


def _profile_out(session: Session, workspace_id: int) -> ProfileOut:
    row = _profile(session, workspace_id)
    return ProfileOut(
        skills=_skills_out(list(row.skills)),
        titles=list(row.titles),
        countries=list(row.countries),
        remote_only=row.remote_only,
        min_score=row.min_score,
        prefs=Prefs.model_validate(row.prefs or {}),
        mail=_mail_out(session.get(WorkspaceMail, workspace_id)),
    )


@router.get("/profile", response_model=ProfileOut, summary="CV skills, wishes, look and alerts")
def get_profile(workspace_id: WorkspaceId, db: Db) -> ProfileOut:
    with Session(db) as session, session.begin():
        return _profile_out(session, workspace_id)


@router.put("/profile", response_model=ProfileOut, summary="Change any part of the profile")
def put_profile(body: ProfileIn, workspace_id: WorkspaceId, db: Db) -> ProfileOut:
    with Session(db) as session, session.begin():
        row = _profile(session, workspace_id)
        if body.skills is not None:
            row.skills = skills.known_ids(body.skills)
        if body.titles is not None:
            row.titles = list(dict.fromkeys(body.titles))
        if body.countries is not None:
            row.countries = list(dict.fromkeys(body.countries))
        if body.remote_only is not None:
            row.remote_only = body.remote_only
        if body.min_score is not None:
            row.min_score = body.min_score
        if body.prefs is not None:
            row.prefs = body.prefs.model_dump()
        row.updated_at = now()
        return _profile_out(session, workspace_id)


class ResumeOut(BaseModel):
    skills: list[SkillOut]
    kept: bool = Field(description="Always false: the file is read and discarded")


@router.post(
    "/profile/resume",
    response_model=ResumeOut,
    summary="Read the skills out of a CV file (PDF, Word or text); the file is not stored",
)
async def read_resume(
    request: Request,
    workspace_id: WorkspaceId,
    db: Db,
    redis: Annotated[Redis, Depends(redis_client)],
    x_filename: Annotated[str, Header(max_length=200)] = "cv.txt",
    save: Annotated[bool, Query(description="Replace the profile's skills with these")] = True,
) -> ResumeOut:
    """Send the file's bytes as the body, its name in ``X-Filename``."""
    bucket_limit(redis, f"cv-file:{workspace_id}", CV_PER_MINUTE, "CV uploads")
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > 3 * 1024 * 1024:
        raise ApiError(413, "too_large", "the CV file is over 2 MB")
    text = extract_text(x_filename, await request.body())
    found = skills.extract_skills(text)[:PROFILE_SKILLS_MAX]
    if not found:
        raise ApiError(
            422,
            "no_skills_found",
            "no skills, tools, licences or languages were recognised; add more detail",
        )
    if save:
        with Session(db) as session, session.begin():
            row = _profile(session, workspace_id)
            row.skills = found
            row.updated_at = now()
    return ResumeOut(skills=_skills_out(found), kept=False)


class PickOut(BaseModel):
    job_id: str
    title: str
    company: str
    location: str | None
    apply_url: str
    score: int
    why: str


@router.get(
    "/profile/jobs",
    response_model=list[PickOut],
    summary="Jobs found for this profile (open jobs indexed in the last 30 days)",
)
def profile_jobs(
    workspace_id: WorkspaceId,
    db: Db,
    client: Annotated[OpenSearch, Depends(search_client)],
    alias: Annotated[str, Depends(search_alias)],
    limit: Annotated[int, Query(ge=1, le=30)] = 20,
) -> list[PickOut]:
    with Session(db) as session:
        profile = session.get(WorkspaceProfile, workspace_id)
        if profile is None or not profile.skills:
            raise ApiError(409, "no_profile", "add your CV or some skills first")
        picks = rank_new_jobs(
            client, alias, profile, since=now() - LOOKBACK, skip=set(), limit=limit
        )
    return [PickOut(**pick.__dict__) for pick in picks]


# --- email alerts ---------------------------------------------------------------------------


class MailIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: Annotated[str, StringConstraints(strip_whitespace=True, max_length=254)]
    frequency: Frequency = "daily"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _new_token(size: int = 32) -> str:
    return base64.urlsafe_b64encode(os.urandom(size)).rstrip(b"=").decode()


@router.put(
    "/mail", response_model=MailOut, summary="Ask for job alerts by email (confirm by link)"
)
def put_mail(
    body: MailIn,
    workspace_id: WorkspaceId,
    db: Db,
    redis: Annotated[Redis, Depends(redis_client)],
) -> MailOut:
    email = body.email.lower()
    if not EMAIL_PATTERN.match(email):
        raise ApiError(400, "invalid_parameter", "that does not look like an email address")
    with Session(db) as session, session.begin():
        profile = session.get(WorkspaceProfile, workspace_id)
        if profile is None or not profile.skills:
            raise ApiError(409, "no_profile", "add your CV or some skills before asking for alerts")
        mail = session.get(WorkspaceMail, workspace_id)
        if mail is not None and mail.email == email and mail.confirmed_at is not None:
            mail.frequency = body.frequency
            return _mail_out(mail)  # type: ignore[return-value]
        # One confirmation message per address and workspace each hour: nobody can use ERIO to
        # fill a stranger's inbox.
        bucket_limit(
            redis, f"mail-ws:{workspace_id}", CONFIRM_MAILS_PER_HOUR, "confirmation emails"
        )
        bucket_limit(
            redis, f"mail-to:{_hash(email)}", CONFIRM_MAILS_PER_HOUR, "confirmation emails"
        )
        token = _new_token()
        if mail is None:
            mail = WorkspaceMail(workspace_id=workspace_id, manage_token=_new_token(24))
            session.add(mail)
        mail.email = email
        mail.frequency = body.frequency
        mail.confirm_token_hash = _hash(token)
        mail.confirm_sent_at = now()
        mail.confirmed_at = None
        mail.paused = False
        mail.bounces = 0
        mail.sent_job_ids = []
        mail.last_checked_at = now()
        session.flush()
        try:
            send(confirmation(get_settings().site_url, mail, token))
        except MailError as error:
            raise ApiError(
                502, "mail_unavailable", "the confirmation email could not be sent"
            ) from error
        return _mail_out(mail)  # type: ignore[return-value]


@router.delete("/mail", status_code=204, summary="Stop alerts and delete the address")
def delete_mail(workspace_id: WorkspaceId, db: Db) -> Response:
    with Session(db) as session, session.begin():
        mail = session.get(WorkspaceMail, workspace_id)
        if mail is not None:
            session.delete(mail)
    return Response(status_code=204)


# The links in the emails open the website, which calls these. No workspace token: the key
# is in the link, and it can only confirm, pause, change the rhythm of, or delete the address.


class ConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: Annotated[str, StringConstraints(pattern=TOKEN_PATTERN)]


class AlertState(BaseModel):
    email: str
    frequency: Frequency
    paused: bool
    confirmed: bool


def _masked(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:1]}{'*' * max(1, len(local) - 1)}@{domain}"


def _state(mail: WorkspaceMail) -> AlertState:
    return AlertState(
        email=_masked(mail.email),
        frequency=mail.frequency,  # type: ignore[arg-type]
        paused=mail.paused,
        confirmed=mail.confirmed_at is not None,
    )


def _by_manage(session: Session, token: str) -> WorkspaceMail:
    mail = session.scalars(
        select(WorkspaceMail).where(WorkspaceMail.manage_token == token)
    ).one_or_none()
    if mail is None:
        raise ApiError(404, "not_found", "this alert link is no longer valid")
    return mail


ManageToken = Annotated[str, Path(pattern=TOKEN_PATTERN)]


@alerts.post("/confirm", response_model=AlertState, summary="Confirm an email address")
def confirm(body: ConfirmIn, db: Annotated[Engine, Depends(engine)]) -> AlertState:
    with Session(db) as session, session.begin():
        mail = session.scalars(
            select(WorkspaceMail).where(WorkspaceMail.confirm_token_hash == _hash(body.token))
        ).one_or_none()
        if mail is None or mail.confirm_sent_at is None:
            raise ApiError(404, "not_found", "this confirmation link is not valid")
        if now() - mail.confirm_sent_at > CONFIRM_VALID:
            raise ApiError(410, "expired", "this confirmation link has expired; ask for a new one")
        mail.confirmed_at = now()
        mail.confirm_token_hash = None
        mail.last_checked_at = now()
        return _state(mail)


@alerts.get("/{token}", response_model=AlertState, summary="State of one alert subscription")
def alert_state(token: ManageToken, db: Annotated[Engine, Depends(engine)]) -> AlertState:
    with Session(db) as session:
        return _state(_by_manage(session, token))


class AlertPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paused: bool | None = None
    frequency: Frequency | None = None


@alerts.patch("/{token}", response_model=AlertState, summary="Pause, resume or change the rhythm")
def alert_patch(
    token: ManageToken, body: AlertPatch, db: Annotated[Engine, Depends(engine)]
) -> AlertState:
    with Session(db) as session, session.begin():
        mail = _by_manage(session, token)
        if body.paused is not None:
            mail.paused = body.paused
            if not body.paused:
                mail.bounces = 0
                mail.last_checked_at = now()
        if body.frequency is not None:
            mail.frequency = body.frequency
        return _state(mail)


@alerts.delete("/{token}", status_code=204, summary="Delete the address")
def alert_delete(token: ManageToken, db: Annotated[Engine, Depends(engine)]) -> Response:
    with Session(db) as session, session.begin():
        session.delete(_by_manage(session, token))
    return Response(status_code=204)
