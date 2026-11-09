from datetime import UTC, datetime
from typing import get_args

import pytest
from pydantic import ValidationError

from erio_core import schemas
from erio_core.db import models
from erio_core.schemas import JobRecord, PartialJob, RawPosting, content_hash

# Spec section 4, "JobRecord (what the API returns)", in order.
SPEC_FIELDS = [
    "canonical_id",
    "title",
    "company",
    "role_category",
    "location_text",
    "city",
    "region",
    "country_code",
    "lat",
    "lon",
    "remote_status",
    "remote_scope",
    # Not in the spec table; the acquisition brief asks to keep it when a source gives it.
    "employment_type",
    "eligible_country_codes",
    "salary_min",
    "salary_max",
    "salary_currency",
    "salary_period",
    "salary_usd_annual_min",
    "status",
    "posted_at",
    "indexed_at",
    "last_verified_at",
    "closed_at",
    "sources",
    "dedup_method",
    "apply_url",
    "description_html",
    "description_text",
]


def _record() -> JobRecord:
    return JobRecord(
        canonical_id="job_01",
        title="Senior Backend Engineer",
        company={"name": "Paystack", "domain": "paystack.com", "logo_url": None},
        role_category="engineering",
        location_text="Lagos, Nigeria",
        city="Lagos",
        region="Lagos",
        country_code="NG",
        lat=6.52,
        lon=3.38,
        remote_status="hybrid",
        remote_scope=None,
        eligible_country_codes=[],
        salary_min=3_500_000,
        salary_max=5_000_000,
        salary_currency="NGN",
        salary_period="month",
        salary_usd_annual_min=27_000,
        status="open",
        posted_at=datetime(2026, 11, 4, 9, 30, tzinfo=UTC),
        indexed_at=datetime(2026, 11, 4, 9, 41, tzinfo=UTC),
        last_verified_at=datetime(2026, 11, 4, 9, 41, tzinfo=UTC),
        closed_at=None,
        sources=["greenhouse"],
        dedup_method=None,
        apply_url="https://boards.greenhouse.io/paystack/jobs/1",
        description_html="<p>Build payments.</p>",
        description_text="Build payments.",
    )


def test_job_record_has_exactly_the_spec_fields() -> None:
    assert list(JobRecord.model_fields) == SPEC_FIELDS


def test_job_record_serializes_to_the_spec_field_list() -> None:
    data = _record().model_dump(mode="json")

    assert list(data) == SPEC_FIELDS
    assert data["company"] == {
        "name": "Paystack",
        "slug": None,
        "domain": "paystack.com",
        "logo_url": None,
    }
    assert data["posted_at"] == "2026-11-04T09:30:00Z"
    assert data["salary_currency"] == "NGN"


@pytest.mark.parametrize(
    ("literal", "column_values"),
    [
        (schemas.RoleCategory, models.ROLE_CATEGORIES),
        (schemas.RemoteStatus, models.REMOTE_STATUSES),
        (schemas.RemoteScope, models.REMOTE_SCOPES),
        (schemas.SalaryPeriod, models.SALARY_PERIODS),
        (schemas.JobStatus, models.JOB_STATUSES),
        (schemas.DedupMethod, models.DEDUP_METHODS),
    ],
)
def test_allowed_values_match_the_database(literal: object, column_values: tuple[str]) -> None:
    assert set(get_args(literal)) == set(column_values)


def test_job_record_rejects_unknown_status() -> None:
    data = _record().model_dump()
    data["status"] = "deleted"
    with pytest.raises(ValidationError):
        JobRecord(**data)


def test_content_hash_ignores_key_order() -> None:
    assert content_hash({"a": 1, "b": [1, 2]}) == content_hash({"b": [1, 2], "a": 1})
    assert content_hash({"a": 1}) != content_hash({"a": 2})


def test_raw_posting_hashes_its_payload_and_needs_timezones() -> None:
    posting = RawPosting(
        source_slug="greenhouse",
        board_token="paystack",
        external_id="1",
        payload={"id": 1, "title": "Engineer"},
    )
    assert posting.content_hash == content_hash({"id": 1, "title": "Engineer"})
    assert posting.fetched_at.tzinfo is not None

    with pytest.raises(ValidationError):
        RawPosting(
            source_slug="greenhouse",
            board_token="paystack",
            external_id="1",
            payload={},
            fetched_at=datetime(2026, 11, 4, 9, 30),
        )


def test_partial_job_needs_a_valid_apply_url() -> None:
    with pytest.raises(ValidationError):
        PartialJob(source_slug="greenhouse", external_id="1", title="Engineer", apply_url="nope")


def test_a_partial_job_never_keeps_an_http_apply_link() -> None:
    from erio_core.schemas import PartialJob

    job = PartialJob(
        source_slug="gohire",
        external_id="1",
        title="HR Executive",
        apply_url="http://x.example.org/j/1",
    )

    assert str(job.apply_url) == "https://x.example.org/j/1"
