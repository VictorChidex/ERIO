"""allow public job services as a source kind

Revision ID: 0016
Revises: 0015
Create date: 2026-11-09 18:00:00.000000+00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT = "source_kind"


def upgrade() -> None:
    op.drop_constraint(CONSTRAINT, "sources", type_="check")
    op.create_check_constraint(CONSTRAINT, "sources", "kind IN ('ats', 'board', 'service')")


def downgrade() -> None:
    op.execute("DELETE FROM sources WHERE kind = 'service'")
    op.drop_constraint(CONSTRAINT, "sources", type_="check")
    op.create_check_constraint(CONSTRAINT, "sources", "kind IN ('ats', 'board')")
