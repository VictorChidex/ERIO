"""Read postings again that the parsers and the location rules have since learned to understand.

A posting is normalized once, when its content first arrives. When a connector starts reading
a field it used to skip, or the place rules learn a new format, the jobs built earlier keep
their old result: a job left without a country stays out of every country search.
``reopen_for_review`` marks the postings of every live job still flagged for review as not yet
normalized, so the normalizer reads them again from their stored payloads. A job that still
cannot be resolved just ends up flagged again; one that can is searchable at the next index sync:

    python -m erio_ingest.renormalize
"""

from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from erio_core.db.models import Job, JobSource, RawPosting


def reopen_for_review(engine: Engine) -> int:
    """How many postings were marked for normalizing again."""
    with Session(engine) as session, session.begin():
        flagged = (
            select(JobSource.raw_posting_id)
            .join(Job, Job.canonical_id == JobSource.job_id)
            .where(Job.review_reason.is_not(None), Job.merged_into.is_(None))
        )
        result = session.execute(
            update(RawPosting)
            .where(RawPosting.id.in_(flagged), RawPosting.payload_s3_key.is_not(None))
            .values(normalized_hash=None)
        )
        return int(result.rowcount)  # type: ignore[attr-defined]


def main() -> None:
    from sqlalchemy import create_engine

    from erio_core.settings import get_settings

    count = reopen_for_review(create_engine(get_settings().sqlalchemy_url))
    print(f"marked {count} postings to be normalized again")


if __name__ == "__main__":
    main()
