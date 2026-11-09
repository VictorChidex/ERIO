"""add company slug

Revision ID: 0014
Revises: 0013
Create date: 2026-11-09 09:00:00.000000+00:00
"""

import re
import unicodedata
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _slugify(name: str) -> str:
    # Kept here, not imported, so this migration never changes meaning with the app.
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")[:80].strip("-") or "company"


def upgrade() -> None:
    op.add_column("companies", sa.Column("slug", sa.String(length=100), nullable=True))
    connection = op.get_bind()
    taken: set[str] = set()
    for company_id, name in connection.execute(
        sa.text("SELECT id, name FROM companies ORDER BY id")
    ).all():
        base = _slugify(name)
        slug, n = base, 1
        while slug in taken:
            n += 1
            slug = f"{base}-{n}"
        taken.add(slug)
        connection.execute(
            sa.text("UPDATE companies SET slug = :slug WHERE id = :id"),
            {"slug": slug, "id": company_id},
        )
    op.alter_column("companies", "slug", nullable=False)
    op.create_unique_constraint(op.f("uq_companies_slug"), "companies", ["slug"])


def downgrade() -> None:
    op.drop_constraint(op.f("uq_companies_slug"), "companies", type_="unique")
    op.drop_column("companies", "slug")
