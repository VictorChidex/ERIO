"""Normalizing real recorded Greenhouse postings into canonical job fields."""

import json
from pathlib import Path

from erio_core.connectors.greenhouse import GreenhouseConnector
from erio_core.normalize.job import (
    CITY_MAX,
    LOCATION_MAX,
    TITLE_MAX,
    canonical_id,
    fit,
    normalize,
)
from erio_core.schemas import PartialJob, RawPosting

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "greenhouse"
RATES = {"GBP": 1.30, "EUR": 1.10, "NGN": 0.0007}


def jobs(board: str) -> list[RawPosting]:
    data = json.loads((FIXTURES / f"{board}.json").read_bytes())
    return [
        RawPosting(source_slug="greenhouse", board_token=board, external_id=str(j["id"]), payload=j)
        for j in data["jobs"]
    ]


def by_location(board: str, location: str) -> RawPosting:
    return next(p for p in jobs(board) if p.payload["location"]["name"] == location)


def test_canonical_id_is_stable() -> None:
    assert canonical_id("greenhouse", "123") == canonical_id("greenhouse", "123")
    assert canonical_id("greenhouse", "123") != canonical_id("lever", "123")
    assert canonical_id("greenhouse", "123").startswith("j_")


def test_london_onsite_job() -> None:
    raw = by_location("truelayer", "London, United Kingdom")
    job = normalize(GreenhouseConnector().parse(raw), RATES)
    columns = job.columns()

    assert columns["country_code"] == "GB"
    assert columns["city"] == "London"
    assert columns["remote_status"] == "onsite"
    assert columns["location_text"] == "London, United Kingdom"
    assert columns["role_category"] == "operations"  # Customer Success Manager
    assert columns["review_reason"] is None
    assert columns["description_html"] and "<script" not in columns["description_html"]
    assert columns["description_text"] and "<" not in columns["description_text"][:200]


def test_remote_nigeria_job() -> None:
    raw = by_location("moniepoint", "Remote, Nigeria")
    columns = normalize(GreenhouseConnector().parse(raw), RATES).columns()

    assert columns["remote_status"] == "remote"
    assert columns["remote_scope"] == "country"
    assert columns["country_code"] == "NG"
    assert columns["eligible_country_codes"] == ["NG"]
    assert columns["role_category"] == "sales"  # Business Relationship Manager


def test_every_recorded_posting_normalizes() -> None:
    for board in ("truelayer", "moniepoint"):
        for raw in jobs(board):
            columns = normalize(GreenhouseConnector().parse(raw), RATES).columns()
            assert columns["title"]
            assert columns["country_code"] or columns["eligible_country_codes"]


def test_text_longer_than_its_column_is_clipped_not_rejected() -> None:
    partial = PartialJob(
        source_slug="deel",
        external_id="1",
        title="Senior " + "Engineer " * 60,
        apply_url="https://jobs.example.org/1",
        location_text="Remote, " + "Somewhere " * 60,
    )

    columns = normalize(partial, RATES).columns()

    assert len(str(columns["title"])) == TITLE_MAX and str(columns["title"]).endswith("…")
    assert len(str(columns["location_text"])) == LOCATION_MAX


def test_fit_leaves_text_that_fits_alone() -> None:
    assert fit("Nurse", 300) == "Nurse"
    assert fit(None, CITY_MAX) is None
    assert fit("x" * 120, 120) == "x" * 120
    assert fit("x" * 121, 120) == "x" * 119 + "…"
