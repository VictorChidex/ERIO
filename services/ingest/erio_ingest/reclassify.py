"""Give stored jobs the role category the current rules find.

Role rules change over time, and a job is classified once, when it is
normalized. ``reclassify`` re-runs the rules on the title of every job still
in ``other`` (a job in any other category was recognised already) and moves
the ones the rules now recognise. A role the AI fallback filled is left as
the model decided it. Changed jobs are picked up by the next index sync, which
follows ``updated_at``:

    python -m erio_ingest.reclassify
"""

from collections import Counter

from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from erio_core.db.models import Job
from erio_core.normalize.roles import classify_role


def reclassify(engine: Engine) -> Counter[str]:
    """How many jobs moved to each category."""
    moved: Counter[str] = Counter()
    with Session(engine) as session, session.begin():
        rows = session.execute(
            select(Job.canonical_id, Job.title, Job.ai_filled).where(Job.role_category == "other")
        ).all()
        for canonical_id, title, ai_filled in rows:
            if "role" in (ai_filled or []):
                continue
            role = classify_role(title)
            if role != "other":
                session.execute(
                    update(Job).where(Job.canonical_id == canonical_id).values(role_category=role)
                )
                moved[role] += 1
    return moved


def main() -> None:
    from sqlalchemy import create_engine

    from erio_core.settings import get_settings

    moved = reclassify(create_engine(get_settings().sqlalchemy_url))
    print(f"moved {sum(moved.values())} jobs out of other: {dict(moved)}")


if __name__ == "__main__":
    main()
