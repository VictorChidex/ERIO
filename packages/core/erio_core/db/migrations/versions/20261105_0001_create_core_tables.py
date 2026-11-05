"""create core tables

Revision ID: 0001
Revises:
Create date: 2026-11-05 03:25:51.561552+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "api_tokens",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("owner_email", sa.String(length=320), nullable=False),
        sa.Column("token_hash", sa.CHAR(length=64), nullable=False),
        sa.Column(
            "tier",
            sa.Enum(
                "free",
                "pro",
                name="token_tier",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="free",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_api_tokens_token_hash")),
    )
    op.create_index(op.f("ix_api_tokens_owner_email"), "api_tokens", ["owner_email"], unique=False)
    op.create_table(
        "companies",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("domain", sa.String(length=253), nullable=True),
        sa.Column("logo_url", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_companies")),
        sa.UniqueConstraint("domain", name=op.f("uq_companies_domain")),
    )
    op.create_table(
        "countries",
        sa.Column("code", sa.CHAR(length=2), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("region", sa.String(length=40), nullable=True),
        sa.Column("subregion", sa.String(length=60), nullable=True),
        sa.Column(
            "region_groups", sa.ARRAY(sa.String(length=16)), server_default="{}", nullable=False
        ),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_countries")),
        sa.UniqueConstraint("name", name=op.f("uq_countries_name")),
    )
    op.create_table(
        "sources",
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "ats",
                "board",
                name="source_kind",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "live",
                "indexing",
                "scheduled",
                "paused",
                name="source_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="scheduled",
            nullable=False,
        ),
        sa.Column("default_cadence_min", sa.SmallInteger(), server_default="15", nullable=False),
        sa.Column("legal_reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("legal_reviewer", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("slug", name=op.f("pk_sources")),
    )
    op.create_table(
        "company_boards",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("company_id", sa.BigInteger(), nullable=False),
        sa.Column("source_slug", sa.String(length=40), nullable=False),
        sa.Column("board_token", sa.String(length=200), nullable=False),
        sa.Column("cadence_min", sa.SmallInteger(), server_default="15", nullable=False),
        sa.Column("last_ok_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consecutive_failures", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("paused_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_company_boards_company_id_companies"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_slug"], ["sources.slug"], name=op.f("fk_company_boards_source_slug_sources")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_company_boards")),
        sa.UniqueConstraint(
            "source_slug", "board_token", name=op.f("uq_company_boards_source_slug_board_token")
        ),
    )
    op.create_table(
        "jobs",
        sa.Column("canonical_id", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("company_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "role_category",
            sa.Enum(
                "engineering",
                "product",
                "design",
                "data",
                "operations",
                "sales",
                "marketing",
                "other",
                name="role_category",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="other",
            nullable=False,
        ),
        sa.Column("location_text", sa.String(length=300), nullable=True),
        sa.Column("city", sa.String(length=120), nullable=True),
        sa.Column("region", sa.String(length=120), nullable=True),
        sa.Column("country_code", sa.CHAR(length=2), nullable=True),
        sa.Column("lat", sa.Double(), nullable=True),
        sa.Column("lon", sa.Double(), nullable=True),
        sa.Column(
            "remote_status",
            sa.Enum(
                "remote",
                "hybrid",
                "onsite",
                name="remote_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "remote_scope",
            sa.Enum(
                "country",
                "region",
                "worldwide",
                name="remote_scope",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column(
            "eligible_country_codes",
            sa.ARRAY(sa.CHAR(length=2)),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("salary_min", sa.BigInteger(), nullable=True),
        sa.Column("salary_max", sa.BigInteger(), nullable=True),
        sa.Column("salary_currency", sa.CHAR(length=3), nullable=True),
        sa.Column(
            "salary_period",
            sa.Enum(
                "year",
                "month",
                "hour",
                name="salary_period",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column("salary_usd_annual_min", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "open",
                "closed",
                "unknown",
                name="job_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="open",
            nullable=False,
        ),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "indexed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "dedup_method",
            sa.Enum(
                "exact_id",
                "exact_key",
                "simhash",
                name="dedup_method",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column("apply_url", sa.Text(), nullable=False),
        sa.Column("description_html", sa.Text(), nullable=True),
        sa.Column("description_text", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], name=op.f("fk_jobs_company_id_companies")
        ),
        sa.ForeignKeyConstraint(
            ["country_code"], ["countries.code"], name=op.f("fk_jobs_country_code_countries")
        ),
        sa.PrimaryKeyConstraint("canonical_id", name=op.f("pk_jobs")),
    )
    op.create_index(op.f("ix_jobs_company_id"), "jobs", ["company_id"], unique=False)
    op.create_index(op.f("ix_jobs_country_code"), "jobs", ["country_code"], unique=False)
    op.create_index(
        op.f("ix_jobs_eligible_country_codes"),
        "jobs",
        ["eligible_country_codes"],
        unique=False,
        postgresql_using="gin",
    )
    op.create_index(op.f("ix_jobs_posted_at"), "jobs", ["posted_at"], unique=False)
    op.create_index(
        op.f("ix_jobs_salary_usd_annual_min"), "jobs", ["salary_usd_annual_min"], unique=False
    )
    op.create_index(op.f("ix_jobs_status_posted_at"), "jobs", ["status", "posted_at"], unique=False)
    op.create_table(
        "crawl_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("board_id", sa.BigInteger(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("http_status", sa.SmallInteger(), nullable=True),
        sa.Column(
            "outcome",
            sa.Enum(
                "ok",
                "http_error",
                "timeout",
                "parse_error",
                "rate_limited",
                name="crawl_outcome",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column("postings_seen", sa.Integer(), nullable=True),
        sa.Column("raw_s3_key", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["board_id"],
            ["company_boards.id"],
            name=op.f("fk_crawl_runs_board_id_company_boards"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_crawl_runs")),
    )
    op.create_index(
        op.f("ix_crawl_runs_board_id_started_at"),
        "crawl_runs",
        ["board_id", "started_at"],
        unique=False,
    )
    op.create_table(
        "raw_postings",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source_slug", sa.String(length=40), nullable=False),
        sa.Column("board_id", sa.BigInteger(), nullable=False),
        sa.Column("external_id", sa.String(length=200), nullable=False),
        sa.Column("content_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("missing_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload_s3_key", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["board_id"],
            ["company_boards.id"],
            name=op.f("fk_raw_postings_board_id_company_boards"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_slug"], ["sources.slug"], name=op.f("fk_raw_postings_source_slug_sources")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_raw_postings")),
        sa.UniqueConstraint(
            "source_slug", "external_id", name=op.f("uq_raw_postings_source_slug_external_id")
        ),
    )
    op.create_index(op.f("ix_raw_postings_board_id"), "raw_postings", ["board_id"], unique=False)
    op.create_table(
        "job_sources",
        sa.Column("job_id", sa.String(length=40), nullable=False),
        sa.Column("raw_posting_id", sa.BigInteger(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "dedup_method",
            sa.Enum(
                "exact_id",
                "exact_key",
                "simhash",
                name="dedup_method",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.canonical_id"],
            name=op.f("fk_job_sources_job_id_jobs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["raw_posting_id"],
            ["raw_postings.id"],
            name=op.f("fk_job_sources_raw_posting_id_raw_postings"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("job_id", "raw_posting_id", name=op.f("pk_job_sources")),
        sa.UniqueConstraint("raw_posting_id", name=op.f("uq_job_sources_raw_posting_id")),
    )


def downgrade() -> None:
    op.drop_table("job_sources")
    op.drop_index(op.f("ix_raw_postings_board_id"), table_name="raw_postings")
    op.drop_table("raw_postings")
    op.drop_index(op.f("ix_crawl_runs_board_id_started_at"), table_name="crawl_runs")
    op.drop_table("crawl_runs")
    op.drop_index(op.f("ix_jobs_status_posted_at"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_salary_usd_annual_min"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_posted_at"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_eligible_country_codes"), table_name="jobs", postgresql_using="gin")
    op.drop_index(op.f("ix_jobs_country_code"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_company_id"), table_name="jobs")
    op.drop_table("jobs")
    op.drop_table("company_boards")
    op.drop_table("sources")
    op.drop_table("countries")
    op.drop_table("companies")
    op.drop_index(op.f("ix_api_tokens_owner_email"), table_name="api_tokens")
    op.drop_table("api_tokens")
