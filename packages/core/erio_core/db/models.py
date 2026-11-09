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
    event,
    func,
    select,
    text,
)
from sqlalchemy.engine.default import DefaultExecutionContext
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from erio_core.slugs import slugify, unique_slug

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
    "healthcare",
    "education",
    "hospitality",
    "retail",
    "logistics",
    "trades",
    "security",
    "other",
)
REMOTE_STATUSES = ("remote", "hybrid", "onsite")
REMOTE_SCOPES = ("country", "region", "worldwide")
SALARY_PERIODS = ("year", "month", "hour")
EMPLOYMENT_TYPES = ("full_time", "part_time", "contract", "temporary", "internship", "volunteer")
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


def _new_company_slug(context: DefaultExecutionContext) -> str:
    """A slug for a company inserted without one, unique among those stored.

    Covers every single-row insert; bulk inserts assign slugs themselves
    (see ``erio_core.db.seed``), since rows of one statement cannot see each other.
    """
    name = str(context.get_current_parameters()["name"])  # type: ignore[no-untyped-call]
    taken = set(
        context.connection.execute(
            text("SELECT slug FROM companies WHERE slug LIKE :prefix"),
            {"prefix": slugify(name) + "%"},
        ).scalars()
    )
    return unique_slug(name, taken)


class Company(Base):
    """An employer ERIO tracks."""

    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200))
    # The company's page address, /company/{slug}: lowercase ASCII and hyphens.
    slug: Mapped[str] = mapped_column(String(100), unique=True, default=_new_company_slug)
    domain: Mapped[str | None] = mapped_column(String(253), unique=True)
    logo_url: Mapped[str | None] = mapped_column(Text)
    # Where the company is based, from the seed list (decision D-07); its
    # jobs may be anywhere.
    country_code: Mapped[str | None] = mapped_column(CHAR(2), ForeignKey("countries.code"))
    created_at: Mapped[datetime] = created_at()


@event.listens_for(Session, "before_flush")
def _slug_new_companies(session: Session, flush_context: Any, instances: Any) -> None:
    """Give companies added through the session their slugs together, so two new
    companies with the same name in one flush still get different slugs."""
    fresh = [c for c in session.new if isinstance(c, Company) and not c.slug]
    if not fresh:
        return
    taken = set(session.scalars(select(Company.slug)))
    for company in fresh:
        company.slug = unique_slug(company.name, taken)
        taken.add(company.slug)


class BoardDiscovery(Base):
    """Each search for a company's board on one source, found or not.

    Discovery skips a pair it tried recently, so the nightly run moves
    through the whole seed list instead of probing the same names again.
    """

    __tablename__ = "board_discovery"

    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True
    )
    source_slug: Mapped[str] = mapped_column(ForeignKey("sources.slug"), primary_key=True)
    tried_at: Mapped[datetime]
    board_token: Mapped[str | None] = mapped_column(String(200))


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
    # What this fetch changed, for the per-source metrics (spec section 10).
    postings_new: Mapped[int | None] = mapped_column(Integer)
    postings_closed: Mapped[int | None] = mapped_column(Integer)
    postings_reopened: Mapped[int | None] = mapped_column(Integer)
    raw_s3_key: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)


class SourceCheck(Base):
    """The nightly live smoke test of each source against one known board."""

    __tablename__ = "source_checks"
    __table_args__ = (Index(None, "source_slug", "checked_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_slug: Mapped[str] = mapped_column(ForeignKey("sources.slug"))
    board_token: Mapped[str | None] = mapped_column(String(200))
    checked_at: Mapped[datetime]
    ok: Mapped[bool] = mapped_column(Boolean)
    postings: Mapped[int | None] = mapped_column(Integer)
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
        Index(None, "company_id", "dedup_key"),
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
    employment_type: Mapped[str | None] = mapped_column(
        text_enum("employment_type", EMPLOYMENT_TYPES)
    )
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
    # Every raw posting first becomes its own job. When dedup finds that job
    # is another, its postings move there and it points at the survivor; it
    # leaves search, and its ID redirects (spec section 6).
    merged_into: Mapped[str | None] = mapped_column(
        ForeignKey("jobs.canonical_id", ondelete="SET NULL"), index=True
    )
    # Fingerprints of the posting this row was built from (erio_core.dedup).
    dedup_key: Mapped[str | None] = mapped_column(CHAR(64))
    simhash: Mapped[int | None] = mapped_column(BigInteger)
    apply_url: Mapped[str] = mapped_column(Text)
    description_html: Mapped[str | None] = mapped_column(Text)
    description_text: Mapped[str | None] = mapped_column(Text)
    # Why the normalizer could not resolve this job; such jobs are kept out
    # of country filters until fixed in the admin review queue.
    review_reason: Mapped[str | None] = mapped_column(Text)
    # The AI fallback (erio_ingest.ai_fallback): when it last looked at what
    # the rules left open, and which fields it filled (role, location,
    # salary). Normalizing the job again clears both.
    ai_checked_at: Mapped[datetime | None]
    ai_filled: Mapped[list[str]] = mapped_column(
        ARRAY(String(16)), server_default="{}", nullable=False
    )
    # When the indexer first made this job searchable: the end of the
    # freshness metric, which starts at the posting's first sighting.
    searchable_at: Mapped[datetime | None] = mapped_column(index=True)
    # Seconds from first sighting to searchable, measured once at that moment.
    freshness_seconds: Mapped[int | None] = mapped_column(Integer)
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
    # Set when dedup moved this posting here from the job built from it.
    dedup_method: Mapped[str | None] = mapped_column(text_enum("dedup_method", DEDUP_METHODS))
    merged_at: Mapped[datetime | None] = mapped_column(index=True)


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


class AiCall(Base):
    """Every AI gateway call: what it cost and how it went (spec section 13).

    Prompts and answers are not stored here, so no user search text is kept.
    """

    __tablename__ = "ai_calls"
    __table_args__ = (Index(None, "task", "at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    at: Mapped[datetime]
    task: Mapped[str] = mapped_column(String(40))
    provider: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(80))
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    latency_ms: Mapped[int] = mapped_column(Integer)
    cost_usd: Mapped[float] = mapped_column(Double)
    # ok, invalid_output, timeout, rate_limited, server, rejected, unavailable, bad_response
    outcome: Mapped[str] = mapped_column(String(20))


class AiCacheEntry(Base):
    """A validated AI answer, keyed by task and input, so no input is sent twice."""

    __tablename__ = "ai_cache"

    key: Mapped[str] = mapped_column(CHAR(64), primary_key=True)
    task: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(80))
    answer: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()


class AiEval(Base):
    """One model's score on one task's labeled set (the nightly AI evaluation)."""

    __tablename__ = "ai_evals"
    __table_args__ = (Index(None, "task", "at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    at: Mapped[datetime]
    task: Mapped[str] = mapped_column(String(40))
    # A routing model name, or "rules" for the rules engine on the same rows.
    model: Mapped[str] = mapped_column(String(80))
    rows: Mapped[int] = mapped_column(Integer)
    answered: Mapped[int] = mapped_column(Integer)
    accuracy: Mapped[float] = mapped_column(Double)
    cost_usd: Mapped[float] = mapped_column(Double)
