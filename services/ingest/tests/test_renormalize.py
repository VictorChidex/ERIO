from datetime import UTC, datetime

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from erio_core.db.models import Company, CompanyBoard, Job, JobSource, RawPosting
from erio_core.db.seed import sync_sources
from erio_ingest.renormalize import reopen_for_review

T0 = datetime(2026, 11, 5, 9, 0, tzinfo=UTC)


def test_only_the_postings_of_live_jobs_flagged_for_review_are_reopened(
    migrated_engine: Engine,
) -> None:
    sync_sources(migrated_engine)
    with Session(migrated_engine) as session, session.begin():
        company = Company(name="Acme", domain="acme.example")
        session.add(company)
        session.flush()
        board = CompanyBoard(company_id=company.id, source_slug="greenhouse", board_token="acme")
        session.add(board)
        session.flush()
        common = {
            "company_id": company.id,
            "remote_status": "onsite",
            "apply_url": "https://example.test/apply",
            "indexed_at": T0,
            "updated_at": T0,
            "status": "open",
        }
        jobs = [
            ("j_fine", {}),
            ("j_review", {"review_reason": "no country found in 'Texas-Austin'"}),
            ("j_merged", {"review_reason": "no location given", "merged_into": "j_fine"}),
        ]
        for n, (canonical_id, extra) in enumerate(jobs):
            session.add(Job(canonical_id=canonical_id, title=canonical_id, **common, **extra))
            session.flush()
            posting = RawPosting(
                source_slug="greenhouse",
                board_id=board.id,
                external_id=str(n),
                content_hash="a" * 64,
                normalized_hash="a" * 64,
                payload_s3_key=f"postings/greenhouse/{n}/{'a' * 64}.json.gz",
                first_seen_at=T0,
                last_seen_at=T0,
            )
            session.add(posting)
            session.flush()
            session.add(JobSource(job_id=canonical_id, raw_posting_id=posting.id, is_primary=True))

    assert reopen_for_review(migrated_engine) == 1

    with Session(migrated_engine) as session:
        hashes = dict(
            session.execute(select(RawPosting.external_id, RawPosting.normalized_hash))
            .tuples()
            .all()
        )
    assert hashes == {"0": "a" * 64, "1": None, "2": "a" * 64}  # only j_review is reopened
