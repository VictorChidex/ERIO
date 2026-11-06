from datetime import UTC, datetime

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from erio_core.db.models import Company, Job
from erio_ingest.reclassify import reclassify

T0 = datetime(2026, 11, 5, 9, 0, tzinfo=UTC)


def test_jobs_in_other_move_to_the_category_the_rules_now_find(migrated_engine: Engine) -> None:
    with Session(migrated_engine) as session, session.begin():
        company = Company(name="Acme Care", domain="acme.example")
        session.add(company)
        session.flush()
        common = {
            "company_id": company.id,
            "remote_status": "onsite",
            "apply_url": "https://example.test/apply",
            "indexed_at": T0,
            "updated_at": T0,
            "status": "open",
        }
        session.add_all(
            [
                Job(
                    canonical_id="j_nurse",
                    title="Registered Nurse",
                    role_category="other",
                    **common,
                ),
                Job(
                    canonical_id="j_driver", title="Class A Driver", role_category="other", **common
                ),
                Job(
                    canonical_id="j_misc",
                    title="Vibes Wizard",
                    role_category="other",
                    **common,
                ),
                # Already recognised, so left alone even if a new rule would also match.
                Job(
                    canonical_id="j_eng",
                    title="Backend Engineer",
                    role_category="engineering",
                    **common,
                ),
                # The AI fallback decided this role: the rules never overrule it.
                Job(
                    canonical_id="j_ai",
                    title="Registered Nurse",
                    role_category="other",
                    ai_filled=["role"],
                    **common,
                ),
            ]
        )

    moved = reclassify(migrated_engine)

    assert dict(moved) == {"healthcare": 1, "logistics": 1}
    with Session(migrated_engine) as session:
        roles = dict(session.execute(select(Job.canonical_id, Job.role_category)).tuples().all())
        changed = session.scalar(select(Job.updated_at).where(Job.canonical_id == "j_nurse"))
        untouched = session.scalar(select(Job.updated_at).where(Job.canonical_id == "j_misc"))
    assert roles == {
        "j_nurse": "healthcare",
        "j_driver": "logistics",
        "j_misc": "other",
        "j_eng": "engineering",
        "j_ai": "other",
    }
    assert changed is not None and untouched is not None
    assert changed > untouched  # the index sync follows updated_at
