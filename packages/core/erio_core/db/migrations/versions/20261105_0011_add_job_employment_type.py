"""add job employment_type

Revision ID: 0011
Revises: 0010
Create date: 2026-11-05 18:14:02.505499+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column(
            "employment_type",
            sa.Enum(
                "full_time",
                "part_time",
                "contract",
                "temporary",
                "internship",
                "volunteer",
                name="employment_type",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("jobs", "employment_type")
