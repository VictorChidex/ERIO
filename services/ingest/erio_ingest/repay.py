"""Check stored pay again against the pay sanity rules.

Jobs normalized before the rules existed may hold an hourly or monthly figure labeled yearly
(INR 4.5, PHP 374.5): the pay statistics read it as a tiny salary, and ``salary_usd_annual_min``
may hold a value between 1,000 and 3,000 dollars that is no longer believed. ``repay`` runs
``check_pay`` on every job's stored figures and updates the rows whose verdict differs: the USD
value is cleared and ``salary_unreliable`` set for an implausible figure, and a figure that is
plausible again is restored. The posted numbers and period are never changed here. Changed
jobs are picked up by the next index sync, which follows ``updated_at``:

    python -m erio_ingest.repay                 # update the rows
    python -m erio_ingest.repay --renormalize   # also read the postings of unreliable jobs again

A stored job no longer knows whether its period was stated or guessed from the size, so the
rows are judged as labeled. ``--renormalize`` marks the postings of the jobs left unreliable as
not yet normalized: the normalizer reads their payloads again and, where the text never named a
period, may infer an hourly or monthly one from the size.
"""

from collections import Counter
from dataclasses import dataclass, field
from typing import cast

from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from erio_core.db.models import Job, JobSource, RawPosting
from erio_core.normalize.salary_check import check_pay
from erio_core.schemas import SalaryHint, SalaryPeriod
from erio_ingest.normalizer import latest_rates

BATCH = 2000


@dataclass
class RepayResult:
    checked: int = 0
    updated: int = 0
    unreliable: int = 0
    restored: int = 0
    reopened: int = 0
    by_currency: Counter[str] = field(default_factory=Counter)


def repay(engine: Engine, renormalize: bool = False) -> RepayResult:
    """Judge every job with a posted salary; update the rows whose verdict changed."""
    result = RepayResult()
    after = ""
    with Session(engine) as session:
        rates = latest_rates(session)
    while True:
        with Session(engine) as session, session.begin():
            rows = session.execute(
                select(
                    Job.canonical_id,
                    Job.salary_min,
                    Job.salary_max,
                    Job.salary_currency,
                    Job.salary_period,
                    Job.salary_usd_annual_min,
                    Job.salary_unreliable,
                )
                .where(
                    Job.canonical_id > after,
                    Job.salary_currency.is_not(None),
                    Job.salary_min.is_not(None) | Job.salary_max.is_not(None),
                )
                .order_by(Job.canonical_id)
                .limit(BATCH)
            ).all()
            for job_id, low, high, currency, period, usd, unreliable in rows:
                hint = SalaryHint(
                    min=low, max=high, currency=currency, period=cast(SalaryPeriod | None, period)
                )
                verdict = check_pay(hint, rates)
                if (verdict.usd_annual_min, verdict.unreliable) == (usd, unreliable):
                    continue
                session.execute(
                    update(Job)
                    .where(Job.canonical_id == job_id)
                    .values(
                        salary_usd_annual_min=verdict.usd_annual_min,
                        salary_unreliable=verdict.unreliable,
                    )
                )
                result.updated += 1
                if verdict.unreliable:
                    result.unreliable += 1
                    result.by_currency[str(currency)] += 1
                elif unreliable:
                    result.restored += 1
        result.checked += len(rows)
        if len(rows) < BATCH:
            break
        after = rows[-1].canonical_id
    if renormalize:
        result.reopened = reopen_unreliable(engine)
    return result


def reopen_unreliable(engine: Engine) -> int:
    """Mark the postings of live jobs with unreliable pay for normalizing again."""
    with Session(engine) as session, session.begin():
        flagged = (
            select(JobSource.raw_posting_id)
            .join(Job, Job.canonical_id == JobSource.job_id)
            .where(Job.salary_unreliable, Job.merged_into.is_(None))
        )
        done = session.execute(
            update(RawPosting)
            .where(RawPosting.id.in_(flagged), RawPosting.payload_s3_key.is_not(None))
            .values(normalized_hash=None)
        )
        return int(done.rowcount)  # type: ignore[attr-defined]


def main() -> None:
    import sys

    from sqlalchemy import create_engine

    from erio_core.settings import get_settings

    result = repay(
        create_engine(get_settings().sqlalchemy_url), renormalize="--renormalize" in sys.argv[1:]
    )
    print(
        f"checked {result.checked} jobs with pay: {result.updated} updated "
        f"({result.unreliable} now unreliable {dict(result.by_currency)}, "
        f"{result.restored} plausible again); {result.reopened} postings marked to be read again"
    )


if __name__ == "__main__":
    main()
