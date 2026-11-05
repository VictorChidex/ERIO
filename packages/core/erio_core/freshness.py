"""Freshness: how long a new job takes to become searchable (spec section 10).

Measured once per job, when the indexer first makes it searchable: from its
first sighting (the first successful fetch that listed any of its postings)
to that moment (``jobs.freshness_seconds``). The median over the last day is
the "refresh lag" the website shows.
"""

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from erio_core.db.models import Job

WINDOW = timedelta(hours=24)


def freshness_seconds(session: Session, now: datetime) -> dict[float, float]:
    """Median and p95 freshness of jobs made searchable in the last day; empty
    when there were none."""
    row = session.execute(
        select(
            func.count(Job.freshness_seconds),
            func.percentile_cont(0.5).within_group(Job.freshness_seconds),
            func.percentile_cont(0.95).within_group(Job.freshness_seconds),
        ).where(Job.searchable_at >= now - WINDOW, Job.freshness_seconds.is_not(None))
    ).one()
    if not row[0]:
        return {}
    return {0.5: float(row[1]), 0.95: float(row[2])}
