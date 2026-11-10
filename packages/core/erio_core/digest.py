"""Job alerts by email: the confirmation message, and the digest of new jobs that fit a CV.

A digest holds only open jobs indexed since the last one, ranked by how much of each job's
requirements the profile's skills cover (``erio_core.skills``), best first, never the same
job twice. Nothing is sent to an address that has not opened its confirmation link.
"""

import html
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote

from opensearchpy import OpenSearch
from opensearchpy.exceptions import NotFoundError
from sqlalchemy import select
from sqlalchemy.orm import Session

from erio_core import skills
from erio_core.db.workspace_models import (
    MAIL_SENT_IDS_KEPT,
    WorkspaceMail,
    WorkspaceProfile,
)
from erio_core.mail import MailError, Message, send
from erio_core.search.params import SearchParams
from erio_core.search.query import build_search

log = logging.getLogger(__name__)

CANDIDATES = 200
PER_DIGEST = 10
MAX_BOUNCES = 5
CONFIRM_VALID = timedelta(hours=48)
PERIOD = {"daily": timedelta(hours=23), "weekly": timedelta(days=7) - timedelta(hours=1)}
OVERLAP = timedelta(minutes=5)

Mailer = Callable[[Message], bool]


@dataclass(frozen=True)
class Pick:
    job_id: str
    title: str
    company: str
    location: str | None
    apply_url: str
    score: int
    why: str


def rank_new_jobs(
    client: OpenSearch,
    alias: str,
    profile: WorkspaceProfile,
    *,
    since: datetime,
    skip: set[str],
    limit: int = PER_DIGEST,
) -> list[Pick]:
    """Open jobs indexed after ``since`` that suit the profile, best score first."""
    own = list(profile.skills)
    if not own:
        return []
    params = SearchParams.model_validate(
        {
            "country": list(profile.countries),
            "remote_status": ["remote"] if profile.remote_only else [],
        }
    )
    body = build_search(params.to_query(indexed_after=since - OVERLAP, per_page=CANDIDATES))
    body.pop("aggs", None)
    body.pop("search_after", None)
    phrases = [*profile.titles, *skills.search_phrases(own)]
    body["query"]["bool"]["should"] = [
        {"multi_match": {"query": p, "type": "phrase", "fields": ["title^2", "description_text"]}}
        for p in phrases
    ]
    body["query"]["bool"]["minimum_should_match"] = 1
    body["sort"] = [{"_score": "desc"}, {"canonical_id": "asc"}]
    body["_source"] = True
    body["track_total_hits"] = False
    try:
        hits = client.search(index=alias, body=body)["hits"]["hits"]
    except NotFoundError:
        return []
    ranked: list[Pick] = []
    seen: set[tuple[str, str, str]] = set()
    for hit in hits:
        source: dict[str, Any] = hit["_source"]
        job_id = source["canonical_id"]
        if job_id in skip:
            continue
        # The same opening listed several times (one per requisition) is one line, not five.
        same = (
            str(source.get("title", "")).lower(),
            str(source.get("company_name", "")).lower(),
            str(source.get("location_text") or "").lower(),
        )
        if same in seen:
            continue
        seen.add(same)
        text = f"{source.get('title', '')}\n{source.get('description_text') or ''}"
        result = skills.compare(own, skills.extract_skills(text))
        if result.matched and result.score >= profile.min_score:
            ranked.append(
                Pick(
                    job_id=job_id,
                    title=source.get("title", ""),
                    company=source.get("company_name", ""),
                    location=source.get("location_text"),
                    apply_url=source.get("apply_url", ""),
                    score=result.score,
                    why=result.explanation(),
                )
            )
    ranked.sort(key=lambda pick: -pick.score)
    return ranked[:limit]


def _links(site_url: str, mail: WorkspaceMail) -> tuple[str, str]:
    site = site_url.rstrip("/")
    return f"{site}/alerts/{quote(mail.manage_token)}", site


def confirmation(site_url: str, mail: WorkspaceMail, token: str) -> Message:
    manage, site = _links(site_url, mail)
    link = f"{site}/alerts/confirm?token={quote(token)}"
    text = (
        "Someone (you, we hope) asked ERIO to email job matches to this address.\n\n"
        f"Confirm here, within 48 hours: {link}\n\n"
        "If it was not you, ignore this message: nothing is sent unless you confirm.\n"
        f"Stop or delete at any time: {manage}\n"
    )
    page = (
        "<p>Someone (you, we hope) asked ERIO to email job matches to this address.</p>"
        f'<p><a href="{html.escape(link)}">Confirm my email</a> (valid for 48 hours)</p>'
        "<p>If it was not you, ignore this message: nothing is sent unless you confirm.</p>"
    )
    return Message(mail.email, "Confirm your ERIO job alerts", text, page, manage)


def digest_message(site_url: str, mail: WorkspaceMail, picks: list[Pick]) -> Message:
    manage, site = _links(site_url, mail)
    count = len(picks)
    subject = f"{count} new job{'s' if count != 1 else ''} that fit your CV"
    lines, rows = [], []
    for pick in picks:
        where = f" · {pick.location}" if pick.location else ""
        view = f"{site}/jobs/{quote(pick.job_id)}"
        lines.append(
            f"{pick.title} at {pick.company}{where} ({pick.score}% match)\n  {pick.why}\n  {view}"
        )
        rows.append(
            f'<li><a href="{html.escape(view)}"><b>{html.escape(pick.title)}</b></a> at '
            f"{html.escape(pick.company)}{html.escape(where)} ({pick.score}% match)<br>"
            f"<small>{html.escape(pick.why)}</small> "
            f'<a href="{html.escape(pick.apply_url)}">Apply</a></li>'
        )
    text = (
        "New jobs since the last message, best match first:\n\n"
        + "\n\n".join(lines)
        + f"\n\nChange or stop these emails, or delete your address: {manage}\n"
        "Always read the posting before you apply; ERIO only links to it.\n"
    )
    page = (
        "<p>New jobs since the last message, best match first:</p><ol>"
        + "".join(rows)
        + f'</ol><p><a href="{html.escape(manage)}">Change or stop these emails</a></p>'
    )
    return Message(mail.email, subject, text, page, manage)


@dataclass
class DigestResult:
    checked: int = 0
    sent: int = 0
    jobs: int = 0
    failed: int = 0


def send_digests(
    session: Session,
    client: OpenSearch,
    alias: str,
    site_url: str,
    now: datetime,
    *,
    mailer: Mailer = send,
) -> DigestResult:
    """One pass: every confirmed, unpaused address that is due gets its new matches."""
    result = DigestResult()
    due = session.scalars(
        select(WorkspaceMail).where(
            WorkspaceMail.confirmed_at.is_not(None), WorkspaceMail.paused.is_(False)
        )
    ).all()
    for mail in due:
        if now - mail.last_checked_at < PERIOD[mail.frequency]:
            continue
        profile = session.get(WorkspaceProfile, mail.workspace_id)
        result.checked += 1
        if profile is None or not profile.skills:
            mail.last_checked_at = now
            continue
        picks: list[Pick] = []
        try:
            picks = rank_new_jobs(
                client, alias, profile, since=mail.last_checked_at, skip=set(mail.sent_job_ids)
            )
            if picks:
                mailer(digest_message(site_url, mail, picks))
        except MailError:
            log.warning("digest mail failed", extra={"workspace_id": mail.workspace_id})
            mail.bounces += 1
            mail.paused = mail.bounces >= MAX_BOUNCES
            result.failed += 1
            continue
        except Exception:
            log.exception("digest failed", extra={"workspace_id": mail.workspace_id})
            result.failed += 1
            continue
        mail.last_checked_at = now
        if picks:
            mail.last_sent_at = now
            mail.bounces = 0
            mail.sent_job_ids = [*mail.sent_job_ids, *(p.job_id for p in picks)][
                -MAIL_SENT_IDS_KEPT:
            ]
            result.sent += 1
            result.jobs += len(picks)
    return result
