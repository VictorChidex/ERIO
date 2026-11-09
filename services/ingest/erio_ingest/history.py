"""A job's history: one ``job_events`` row for each real thing that happened to it.

The normalizer records ``added`` when a job is first created and ``changed`` when a new
version of its posting moves one of the tracked fields; the status rules record ``closed`` and
``reopened``; dedup records ``merged`` on the surviving job. Nothing is written when nothing
moved, so a job that is re-read unchanged costs no row.
"""

from collections.abc import Collection, Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import insert
from sqlalchemy.orm import Session

from erio_core.db.models import JobEvent

# The fields a "changed" event reports, each as [old, new].
TRACKED = (
    "title",
    "location_text",
    "country_code",
    "role_category",
    "employment_type",
    "remote_status",
    "salary_min",
    "salary_max",
    "salary_currency",
    "salary_period",
)
# Fields the AI fallback fills when the rules left them open (``jobs.ai_filled``). A new version
# of the posting rebuilds them from the rules and the fallback fills them again, so a move in
# one of these says nothing about the posting and is not reported.
AI_FILLED_FIELDS = {
    "role": ("role_category",),
    "location": ("country_code", "remote_status"),
    "salary": ("salary_min", "salary_max", "salary_currency", "salary_period"),
}


def changed_fields(
    old: Mapping[str, Any], new: Mapping[str, Any], ai_filled: Collection[str] = ()
) -> dict[str, list[Any]]:
    """Each tracked field whose value moved, as ``[old, new]``."""
    skipped = {field for kind in ai_filled for field in AI_FILLED_FIELDS.get(kind, ())}
    return {
        field: [old.get(field), new.get(field)]
        for field in TRACKED
        if field not in skipped and old.get(field) != new.get(field)
    }


def record_event(
    session: Session,
    job_id: str,
    kind: str,
    at: datetime,
    changes: Mapping[str, Any] | None = None,
) -> None:
    session.execute(
        insert(JobEvent).values(job_id=job_id, at=at, kind=kind, changes=dict(changes or {}))
    )
