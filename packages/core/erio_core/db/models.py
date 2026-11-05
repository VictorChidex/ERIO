"""ERIO's Postgres tables, as defined in spec section 4.

Raw postings record what each source said; canonical jobs record what ERIO
believes. Enum-like columns are stored as text with CHECK constraints, so
adding a value is a one-line migration rather than an ALTER TYPE.
"""

from datetime import date, datetime
from typing import Any, ClassVar

from sqlalchemy import (
    ARRAY,
    CHAR,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Double,
    Enum,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Stable constraint names, so migrations can always refer to them.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

SOURCE_KINDS = ("ats", "board")
SOURCE_STATUSES = ("live", "indexing", "scheduled", "paused")
CRAWL_OUTCOMES = ("ok", "http_error", "timeout", "parse_error", "rate_limited")
ROLE_CATEGORIES = (
    "engineering",
    "product",
    "design",
    "data",
    "operations",
    "sales",
    "marketing",
    "other",
)
REMOTE_STATUSES = ("remote", "hybrid", "onsite")
REMOTE_SCOPES = ("country", "region", "worldwide")
SALARY_PERIODS = ("year", "month", "hour")
JOB_STATUSES = ("open", "closed", "unknown")
DEDUP_METHODS = ("exact_id", "exact_key", "simhash")
TOKEN_TIERS = ("free", "pro")


def text_enum(name: str, values: tuple[str, ...]) -> Enum:
    return Enum(*values, name=name, native_enum=False, create_constraint=True, length=32)


def created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map: ClassVar[dict[Any, Any]] = {datetime: DateTime(timezone=True)}


class Country(Base):
    """ISO 3166-1 reference: the 233 entries the globe draws (seeded in step 3b)."""

    __tablename__ = "countries"

    code: Mapped[str] = mapped_column(CHAR(2), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    region: Mapped[str | None] = mapped_column(String(40))
    subregion: Mapped[str | None] = mapped_column(String(60))
    # Region phrases a remote job can name, e.g. EU, EMEA, LATAM, APAC, Africa.
    region_groups: Mapped[list[str]] = mapped_column(
        ARRAY(String(16)), server_default="{}", nullable=False
    )


class Source(Base):
    """One row per connector (Greenhouse, Lever, ...)."""

    __tablename__ = "sources"

    slug: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(text_enum("source_kind", SOURCE_KINDS))
    status: Mapped[str] = mapped_column(
        text_enum("source_status", SOURCE_STATUSES), server_default="scheduled"
    )
    default_cadence_min: Mapped[int] = mapped_column(SmallInteger, server_default="15")
    # Legal review is recorded on the source before it goes live (spec section 5).
    legal_reviewed_at: Mapped[datetime | None]
    legal_reviewer: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = created_at()


class Company(Base):
    """An employer ERIO tracks."""

    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200))
    domain: Mapped[str | None] = mapped_column(String(253), unique=True)
    logo_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()


class CompanyBoard(Base):
    """A company's job board on one source."""

    __tablename__ = "company_boards"
    __table_args__ = (UniqueConstraint("source_slug", "board_token"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    source_slug: Mapped[str] = mapped_column(ForeignKey("sources.slug"))
    board_token: Mapped[str] = mapped_column(String(200))
    cadence_min: Mapped[int] = mapped_column(SmallInteger, server_default="15")
    last_ok_at: Mapped[datetime | None]
    consecutive_failures: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    paused_until: Mapped[datetime | None]
    # The scheduler queues a board once next_crawl_at has passed.
    next_crawl_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)
    # Last successful fetch that found a new or changed posting; boards quiet
    # for 7 days drop to a 60-minute cadence.
    last_change_at: Mapped[datetime | None]
    # ETag of the last successful response, sent as If-None-Match.
    etag: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = created_at()


class CrawlRun(Base):
    """Every fetch of a board, successful or not."""

    __tablename__ = "crawl_runs"
    __table_args__ = (Index(None, "board_id", "started_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    board_id: Mapped[int] = mapped_column(ForeignKey("company_boards.id", ondelete="CASCADE"))
    started_at: Mapped[datetime]
    finished_at: Mapped[datetime | None]
    http_status: Mapped[int | None] = mapped_column(SmallInteger)
    outcome: Mapped[str | None] = mapped_column(text_enum("crawl_outcome", CRAWL_OUTCOMES))
    postings_seen: Mapped[int | None] = mapped_column(Integer)
    raw_s3_key: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)


class RawPosting(Base):
    """A posting as one source reports it."""

    __tablename__ = "raw_postings"
    __table_args__ = (UniqueConstraint("source_slug", "external_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_slug: Mapped[str] = mapped_column(ForeignKey("sources.slug"))
    board_id: Mapped[int] = mapped_column(
        ForeignKey("company_boards.id", ondelete="CASCADE"), index=True
    )
    external_id: Mapped[str] = mapped_column(String(200))
    content_hash: Mapped[str] = mapped_column(CHAR(64))
    first_seen_at: Mapped[datetime]
    last_seen_at: Mapped[datetime]
    # First successful fetch that no longer listed this posting.
    missing_since: Mapped[datetime | None]
    # Set when a second successful fetch, 30+ minutes later, still misses it.
    closed_at: Mapped[datetime | None]
    payload_s3_key: Mapped[str | None] = mapped_column(Text)
    # content_hash of the version the normalizer last turned into a job.
    normalized_hash: Mapped[str | None] = mapped_column(CHAR(64))


class Job(Base):
    """A canonical job: what the API returns as JobRecord."""

    __tablename__ = "jobs"
    __table_args__ = (
        Index(None, "eligible_country_codes", postgresql_using="gin"),
        Index(None, "status", "posted_at"),
    )

    canonical_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    role_category: Mapped[str] = mapped_column(
        text_enum("role_category", ROLE_CATEGORIES), server_default="other"
    )
    location_text: Mapped[str | None] = mapped_column(String(300))
    city: Mapped[str | None] = mapped_column(String(120))
    region: Mapped[str | None] = mapped_column(String(120))
    # Null only for worldwide-remote roles.
    country_code: Mapped[str | None] = mapped_column(ForeignKey("countries.code"), index=True)
    lat: Mapped[float | None] = mapped_column(Double)
    lon: Mapped[float | None] = mapped_column(Double)
    remote_status: Mapped[str] = mapped_column(text_enum("remote_status", REMOTE_STATUSES))
    remote_scope: Mapped[str | None] = mapped_column(text_enum("remote_scope", REMOTE_SCOPES))
    # Countries a remote role accepts; empty means worldwide.
    eligible_country_codes: Mapped[list[str]] = mapped_column(
        ARRAY(CHAR(2)), server_default="{}", nullable=False
    )
    salary_min: Mapped[int | None] = mapped_column(BigInteger)
    salary_max: Mapped[int | None] = mapped_column(BigInteger)
    salary_currency: Mapped[str | None] = mapped_column(CHAR(3))
    salary_period: Mapped[str | None] = mapped_column(text_enum("salary_period", SALARY_PERIODS))
    # Used only for filtering and sorting; never displayed as the posted salary.
    salary_usd_annual_min: Mapped[int | None] = mapped_column(Integer, index=True)
    # Indexed through (status, posted_at) above.
    status: Mapped[str] = mapped_column(
        text_enum("job_status", JOB_STATUSES), server_default="open"
    )
    posted_at: Mapped[datetime | None] = mapped_column(index=True)
    indexed_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_verified_at: Mapped[datetime | None]
    closed_at: Mapped[datetime | None]
    dedup_method: Mapped[str | None] = mapped_column(text_enum("dedup_method", DEDUP_METHODS))
    apply_url: Mapped[str] = mapped_column(Text)
    description_html: Mapped[str | None] = mapped_column(Text)
    description_text: Mapped[str | None] = mapped_column(Text)
    # Why the normalizer could not resolve this job; such jobs are kept out
    # of country filters until fixed in the admin review queue.
    review_reason: Mapped[str | None] = mapped_column(Text)
    # Last change to any field; the search indexer follows this.
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), index=True
    )


class JobSource(Base):
    """Links a canonical job to every raw posting it was built from."""

    __tablename__ = "job_sources"

    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.canonical_id", ondelete="CASCADE"), primary_key=True
    )
    raw_posting_id: Mapped[int] = mapped_column(
        ForeignKey("raw_postings.id", ondelete="CASCADE"), primary_key=True, unique=True
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, server_default="false")
    dedup_method: Mapped[str | None] = mapped_column(text_enum("dedup_method", DEDUP_METHODS))


class FxRate(Base):
    """Daily exchange rates for USD salary values (spec section 6)."""

    __tablename__ = "fx_rates"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    currency: Mapped[str] = mapped_column(CHAR(3), primary_key=True)
    usd_per_unit: Mapped[float] = mapped_column(Double)
    source: Mapped[str] = mapped_column(String(40))


class ApiToken(Base):
    """API access tokens. Only a hash of each token is stored."""

    __tablename__ = "api_tokens"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_email: Mapped[str] = mapped_column(String(320), index=True)
    token_hash: Mapped[str] = mapped_column(CHAR(64), unique=True)
    tier: Mapped[str] = mapped_column(text_enum("token_tier", TOKEN_TIERS), server_default="free")
    created_at: Mapped[datetime] = created_at()
    last_used_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]
