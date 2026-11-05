"""Ask AI about what the rules left open (spec section 13: normalization fallback).

Every few minutes, for live jobs the AI has not looked at since they were
last normalized:

- role "other": ask for a role category;
- in the review queue (no country found): ask where the job is;
- no salary found, but the text talks about pay: ask for the stated range.

Model calls happen outside any transaction; each job's answers are then
written in a short one, and only if the job was not normalized again in the
meantime. A job is marked checked only when a model answered: if AI is off,
over budget or every provider is down, the job keeps its rules result and
is tried again later, so no job ever fails because of AI.
"""

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import Engine, or_, select, update
from sqlalchemy.orm import Session

from erio_core.ai.gateway import Gateway
from erio_core.ai.tasks import PAY_CUE, ai_location, ai_role, ai_salary
from erio_core.db.models import Job
from erio_core.normalize.fx import usd_annual
from erio_ingest.normalizer import latest_rates

BATCH = 50
# Postgres-side prefilter for PAY_CUE; the Python pattern decides.
PAY_PREFILTER = r"(salary|compensation|pay|per (year|annum|month|hour)|[$€£₦₹¥]\s?[0-9])"


@dataclass
class FallbackResult:
    looked_at: int = 0
    checked: int = 0
    filled: Counter[str] = field(default_factory=Counter)


def _pending(session: Session, limit: int) -> list[Job]:
    return list(
        session.scalars(
            select(Job)
            .where(
                Job.merged_into.is_(None),
                Job.status != "closed",
                Job.ai_checked_at.is_(None),
                or_(
                    Job.role_category == "other",
                    Job.review_reason.is_not(None),
                    Job.salary_min.is_(None)
                    & Job.salary_max.is_(None)
                    & Job.description_text.regexp_match(PAY_PREFILTER, "i"),
                ),
            )
            .order_by(Job.indexed_at)
            .limit(limit)
        )
    )


def _answers(
    gateway: Gateway, job: Job, rates: dict[str, float]
) -> tuple[bool, dict[str, Any], list[str]]:
    """Ask every question the job needs: (all answered, column values, fields filled)."""
    answered = True
    values: dict[str, Any] = {}
    filled: list[str] = []
    if job.role_category == "other":
        role = ai_role(gateway, job.title, [])
        answered &= role.answered
        if role.value and role.value != "other":
            values["role_category"] = role.value
            filled.append("role")
    if job.review_reason:
        place = ai_location(gateway, job.location_text or "", job.title)
        answered &= place.answered
        if place.value:
            loc = place.value
            values |= {
                "country_code": loc.country_code,
                "city": loc.city,
                "region": loc.region,
                "lat": loc.lat,
                "lon": loc.lon,
                "remote_status": loc.remote_status,
                "remote_scope": loc.remote_scope,
                "eligible_country_codes": loc.eligible_country_codes,
                "review_reason": None,
            }
            filled.append("location")
    if (
        job.salary_min is None
        and job.salary_max is None
        and PAY_CUE.search(job.description_text or "")
    ):
        pay = ai_salary(gateway, job.description_text)
        answered &= pay.answered
        if pay.value:
            low = pay.value.min if pay.value.min is not None else pay.value.max
            values |= {
                "salary_min": pay.value.min,
                "salary_max": pay.value.max,
                "salary_currency": pay.value.currency,
                "salary_period": pay.value.period,
                "salary_usd_annual_min": usd_annual(
                    low, pay.value.currency, pay.value.period, rates
                ),
            }
            filled.append("salary")
    return answered, values, filled


def fill_with_ai(
    engine: Engine, gateway: Gateway, now: Callable[[], datetime], limit: int = BATCH
) -> FallbackResult:
    result = FallbackResult()
    with Session(engine) as session:
        rates = latest_rates(session)
        jobs = _pending(session, limit)
        session.expunge_all()
    for job in jobs:
        result.looked_at += 1
        answered, values, filled = _answers(gateway, job, rates)
        if not answered and not filled:
            continue
        with Session(engine) as session, session.begin():
            changes = values | {"ai_filled": sorted(set(job.ai_filled) | set(filled))}
            if answered:
                changes["ai_checked_at"] = now()
            # Only a filled field changes what search shows.
            changes["updated_at"] = now() if filled else Job.updated_at
            written = session.execute(
                update(Job)
                # Skip it if the normalizer rebuilt the job while we asked.
                .where(Job.canonical_id == job.canonical_id, Job.indexed_at == job.indexed_at)
                .values(changes)
            )
        if getattr(written, "rowcount", 0):
            result.checked += answered
            result.filled.update(filled)
    return result
