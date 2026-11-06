"""widen role categories beyond tech

Revision ID: 0012
Revises: 0011
Create date: 2026-11-06 03:10:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = ("engineering", "product", "design", "data", "operations", "sales", "marketing", "other")
NEW = (
    *OLD[:-1],
    "healthcare",
    "education",
    "hospitality",
    "retail",
    "logistics",
    "trades",
    "security",
    "other",
)
CONSTRAINT = "role_category"  # the naming convention makes it ck_jobs_role_category


def _replace(values: tuple[str, ...]) -> None:
    op.drop_constraint(CONSTRAINT, "jobs", type_="check")
    listed = ", ".join(f"'{value}'" for value in values)
    op.create_check_constraint(CONSTRAINT, "jobs", f"role_category IN ({listed})")


def upgrade() -> None:
    _replace(NEW)


def downgrade() -> None:
    jobs = sa.table("jobs", sa.column("role_category", sa.String))
    op.execute(
        sa.update(jobs).where(jobs.c.role_category.notin_(OLD)).values(role_category="other")
    )
    _replace(OLD)
