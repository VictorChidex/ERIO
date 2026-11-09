from datetime import UTC, date, datetime

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from erio_core.db.models import Company, CompanyBoard, FxRate, Job, JobSource, RawPosting
from erio_core.db.seed import sync_sources
from erio_ingest.repay import repay

T0 = datetime(2026, 11, 5, 9, 0, tzinfo=UTC)

# job id: (min, max, currency, period, stored usd value, stored unreliable flag)
JOBS = {
    "j_fine": (90_000, 120_000, "USD", "year", 90_000, False),
    "j_rupees": (4, 5, "INR", "year", None, False),  # 4.5 lakh read as rupees
    "j_peso": (374, 420, "PHP", "year", None, False),
    "j_small": (2_000, 2_400, "USD", "year", 2_000, False),  # passed the old 1,000 dollar floor
    "j_hourly": (18, 24, "USD", "hour", 37_440, False),
    "j_restore": (80_000, 90_000, "USD", "year", None, True),  # flagged earlier, plausible now
    "j_nopay": (None, None, None, None, None, False),
}


def test_repay_corrects_the_rows_whose_verdict_changed(migrated_engine: Engine) -> None:
    sync_sources(migrated_engine)
    with Session(migrated_engine) as session, session.begin():
        company = Company(name="Acme", domain="acme.example")
        session.add(company)
        session.flush()
        board = CompanyBoard(company_id=company.id, source_slug="greenhouse", board_token="acme")
        session.add(board)
        session.add_all(
            [
                FxRate(day=date(2026, 11, 4), currency="INR", usd_per_unit=0.012, source="t"),
                FxRate(day=date(2026, 11, 4), currency="PHP", usd_per_unit=0.017, source="t"),
            ]
        )
        session.flush()
        for n, (job_id, (low, high, currency, period, usd, unreliable)) in enumerate(JOBS.items()):
            session.add(
                Job(
                    canonical_id=job_id,
                    title=job_id,
                    company_id=company.id,
                    remote_status="onsite",
                    apply_url="https://example.test/apply",
                    indexed_at=T0,
                    updated_at=T0,
                    salary_min=low,
                    salary_max=high,
                    salary_currency=currency,
                    salary_period=period,
                    salary_usd_annual_min=usd,
                    salary_unreliable=unreliable,
                )
            )
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
            session.add(JobSource(job_id=job_id, raw_posting_id=posting.id, is_primary=True))

    result = repay(migrated_engine, renormalize=True)

    assert (result.checked, result.updated, result.unreliable, result.restored) == (6, 4, 3, 1)
    assert dict(result.by_currency) == {"INR": 1, "PHP": 1, "USD": 1}
    with Session(migrated_engine) as session:
        jobs = {
            j.canonical_id: (
                j.salary_min,
                j.salary_period,
                j.salary_usd_annual_min,
                j.salary_unreliable,
            )
            for j in session.scalars(select(Job))
        }
        marked = {
            external_id: hash_ is None
            for external_id, hash_ in session.execute(
                select(RawPosting.external_id, RawPosting.normalized_hash)
            )
        }
    assert jobs == {
        "j_fine": (90_000, "year", 90_000, False),
        "j_rupees": (4, "year", None, True),  # the posted numbers are kept
        "j_peso": (374, "year", None, True),
        "j_small": (2_000, "year", None, True),
        "j_hourly": (18, "hour", 37_440, False),
        "j_restore": (80_000, "year", 80_000, False),
        "j_nopay": (None, None, None, False),
    }
    # Only the postings of the jobs left unreliable are read again.
    assert sorted(e for e, again in marked.items() if again) == ["1", "2", "3"]

    again = repay(migrated_engine)
    assert (again.checked, again.updated) == (6, 0)  # nothing left to correct
