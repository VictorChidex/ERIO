"""Market pulse and company pages on real Postgres, OpenSearch and Redis, with a
small set of jobs whose every figure is worked out by hand below."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from erio_api import access
from erio_api.deps import engine as engine_dependency
from erio_api.deps import search_alias as alias_dependency
from erio_api.main import app
from erio_core.db.models import Company, CompanyBoard, Job, JobSource, RawPosting
from erio_core.db.seed import sync_countries, sync_sources
from erio_core.search.index import client
from erio_ingest.indexer import sync_changed

NOW = datetime.now(UTC)

# (id, company, country, work, role, contract, pay (min, max, currency, period), status,
#  days since posted, days since closed, hours since verified)
P1, P2 = (100_000, 140_000, "USD", "year"), (160_000, 200_000, "USD", "year")
P3, P4 = (5_000, 7_000, "NGN", "month"), (60_000, 80_000, "USD", "year")
JOBS: list[tuple[Any, ...]] = [
    ("a1", "A", "NG", "remote", "engineering", "full_time", P1, "open", 2, None, 1),
    ("a2", "A", "NG", "onsite", "engineering", "contract", P2, "open", 10, None, 48),
    ("a3", "A", "GB", "hybrid", "product", "full_time", None, "open", None, None, None),
    ("a4", "A", "NG", "onsite", "sales", None, None, "closed", 20, 3, None),
    ("b1", "B", "NG", "onsite", "sales", None, P3, "open", 100, None, 120),
    ("b2", "B", "DE", "remote", "data", "full_time", P4, "open", 1, None, 1),
]  # fmt: skip


@pytest.fixture
def api(migrated_engine: Engine, search_alias: str, redis_url: str) -> Iterator[TestClient]:
    sync_countries(migrated_engine)
    sync_sources(migrated_engine)
    with Session(migrated_engine) as session, session.begin():
        # No slug given: the model assigns one, and a name that folds to the same
        # words gets a numbered one.
        companies = {
            "A": Company(name="Café Acme", domain="acme.example"),
            "B": Company(name="Beta Labs", domain="beta.example", country_code="DE"),
        }
        for company in companies.values():
            session.add(company)
            session.flush()
        boards = {}
        for key, company in companies.items():
            boards[key] = CompanyBoard(
                company_id=company.id,
                source_slug="greenhouse",
                board_token=key.lower(),
                last_ok_at=NOW - timedelta(minutes=5),
            )
            session.add(boards[key])
        session.flush()
        for n, (cid, key, cc, work, role, contract, pay, status, posted, closed, seen) in enumerate(
            JOBS
        ):
            low, high, currency, period = pay or (None, None, None, None)
            session.add(
                Job(
                    canonical_id=cid,
                    title=f"{role} {cid}",
                    company_id=companies[key].id,
                    role_category=role,
                    city="Lagos" if cc == "NG" else None,
                    country_code=cc,
                    remote_status=work,
                    employment_type=contract,
                    salary_min=low,
                    salary_max=high,
                    salary_currency=currency,
                    salary_period=period,
                    status=status,
                    posted_at=None if posted is None else NOW - timedelta(days=posted),
                    indexed_at=NOW,
                    closed_at=None if closed is None else NOW - timedelta(days=closed),
                    last_verified_at=None if seen is None else NOW - timedelta(hours=seen),
                    apply_url=f"https://example.com/{cid}",
                    description_text=cid,
                )
            )
            posting = RawPosting(
                source_slug="greenhouse",
                board_id=boards[key].id,
                external_id=str(n),
                content_hash="0" * 64,
                first_seen_at=NOW,
                last_seen_at=NOW,
            )
            session.add(posting)
            session.flush()
            session.add(JobSource(job_id=cid, raw_posting_id=posting.id, is_primary=True))

    sync_changed(migrated_engine, client(), search_alias, None)
    app.dependency_overrides[engine_dependency] = lambda: migrated_engine
    app.dependency_overrides[alias_dependency] = lambda: search_alias
    app.dependency_overrides[access.redis_client] = lambda: Redis.from_url(redis_url)
    app.dependency_overrides[access.limits] = lambda: dict.fromkeys(
        ("internal", "pro", "free", "anonymous"), 10_000
    )
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def counts(buckets: list[dict[str, Any]]) -> dict[str, int]:
    return {b["key"]: b["count"] for b in buckets}


def test_pulse_totals(api: TestClient) -> None:
    totals = api.get("/v1/insights/pulse").json()["data"]["totals"]
    assert totals == {
        "open_roles": 5,  # the closed job is not counted
        "companies_hiring": 2,
        "sources_watched": 2,  # two boards
        "platforms_live": 1,
        "roles_stating_pay": 4,
        "pay_stated_pct": 80.0,
        "remote_roles": 2,
    }


def test_pulse_roles_added_and_removed_per_day(api: TestClient) -> None:
    flow = api.get("/v1/insights/pulse").json()["data"]["flow"]
    days = {d["date"]: d for d in flow["days"]}
    assert len(flow["days"]) == 30
    assert flow["days"][-1]["date"] == NOW.date().isoformat()
    # a1 (2 days ago), a2 (10), a4 (20), b2 (1) by posted date; a3 has none, so
    # the day it was first seen (today). b1, posted 100 days ago, is outside.
    assert flow["added"] == 5
    assert days[(NOW - timedelta(days=2)).date().isoformat()]["added"] == 1
    assert days[NOW.date().isoformat()]["added"] == 1
    # a4 went away 3 days ago; it is the only removal.
    assert flow["removed"] == 1
    assert days[(NOW - timedelta(days=3)).date().isoformat()]["removed"] == 1
    assert flow["removals_tracked_since"] is not None


def test_pulse_freshness_and_last_seen(api: TestClient) -> None:
    data = api.get("/v1/insights/pulse").json()["data"]
    assert counts(data["posted"]) == {
        "week": 2,  # a1, b2
        "weeks": 1,  # a2
        "months": 0,
        "older": 1,  # b1
        "undated": 1,  # a3
    }
    # a3 was never re-checked: it counts from the day it was indexed.
    assert counts(data["last_seen"]) == {"day": 3, "days": 1, "week": 1, "older": 0}


def test_pulse_roles_work_mode_and_countries(api: TestClient) -> None:
    data = api.get("/v1/insights/pulse").json()["data"]
    assert counts(data["roles"]) == {"engineering": 2, "product": 1, "sales": 1, "data": 1}
    assert counts(data["work_mode"]) == {"remote": 2, "hybrid": 1, "onsite": 2, "not_stated": 0}
    ng = next(c for c in data["countries"] if c["code"] == "NG")
    assert ng == {
        "code": "NG",
        "name": "Nigeria",
        "roles": 3,
        "remote_pct": 33.3,
        "pay_stated_pct": 100.0,
    }
    assert data["countries"][0]["code"] == "NG"  # busiest first


def test_pulse_pay_is_yearly_per_currency_and_never_converted(api: TestClient) -> None:
    pay = api.get("/v1/insights/pulse").json()["data"]["pay"]
    # Only yearly pay: b1's monthly naira range is left out, not annualised.
    assert pay == [
        {
            "currency": "USD",
            "period": "year",
            "roles": 3,
            # Midpoints 70,000 / 120,000 / 180,000.
            "lower": 95_000.0,
            "median": 120_000.0,
            "upper": 150_000.0,
        }
    ]


def test_pulse_sources(api: TestClient) -> None:
    sources = api.get("/v1/insights/pulse").json()["data"]["sources"]
    assert sources["platforms"] == [
        {"slug": "greenhouse", "name": "Greenhouse", "kind": "ats", "roles": 5}
    ]
    assert (sources["ats_roles"], sources["board_roles"]) == (5, 0)


def test_pulse_is_cached_for_five_minutes(api: TestClient, redis_url: str) -> None:
    first = api.get("/v1/insights/pulse").json()
    keys = Redis.from_url(redis_url).keys("erio:insights:pulse:*")
    assert len(keys) == 1
    assert 0 < Redis.from_url(redis_url).ttl(keys[0]) <= 300
    # The second answer is the stored one, even to the second it was generated.
    assert api.get("/v1/insights/pulse").json() == first


def test_company_directory(api: TestClient) -> None:
    rows = api.get("/v1/companies").json()
    assert rows["meta"] == {"total": 2, "page": 1, "per_page": 24}
    assert [(c["slug"], c["open_roles"]) for c in rows["data"]] == [
        ("cafe-acme", 3),  # busiest first
        ("beta-labs", 2),
    ]
    assert [c["slug"] for c in api.get("/v1/companies?sort=name").json()["data"]] == [
        "beta-labs",
        "cafe-acme",
    ]
    assert [c["slug"] for c in api.get("/v1/companies?q=ACME").json()["data"]] == ["cafe-acme"]
    assert api.get("/v1/companies?q=%25").json()["meta"]["total"] == 0  # % is not a wildcard
    assert [c["slug"] for c in api.get("/v1/companies?country=de").json()["data"]] == ["beta-labs"]
    page = api.get("/v1/companies?per_page=1&page=2").json()
    assert [c["slug"] for c in page["data"]] == ["beta-labs"]
    assert page["meta"]["total"] == 2


def test_company_profile(api: TestClient) -> None:
    response = api.get("/v1/companies/cafe-acme")
    assert response.status_code == 200
    c = response.json()["data"]
    assert (c["name"], c["domain"]) == ("Café Acme", "acme.example")
    assert c["open_roles"] == 3
    assert (c["added_30d"], c["removed_30d"]) == (4, 1)  # a1, a2, a3, a4 in; a4 out
    assert c["remote_pct"] == 33.3
    assert c["pay_stated_pct"] == 66.7
    assert c["last_checked_at"] is not None and c["tracked_since"] is not None
    assert len(c["flow"]["days"]) == 30
    assert counts(c["roles"]) == {"engineering": 2, "product": 1}
    assert [(p["key"], p["count"]) for p in c["countries"]] == [("NG", 2), ("GB", 1)]
    assert c["countries"][0]["label"] == "Nigeria"
    assert [(p["key"], p["count"]) for p in c["locations"]] == [("Lagos", 2)]
    assert counts(c["work_mode"]) == {"remote": 1, "hybrid": 1, "onsite": 1}
    assert counts(c["contracts"]) == {"full_time": 2, "contract": 1}
    assert counts(c["posted"]) == {"week": 1, "weeks": 1, "months": 0, "older": 0, "undated": 1}
    assert c["pay"] == [
        {
            "currency": "USD",
            "period": "year",
            "roles": 2,
            "lower": 135_000.0,
            "median": 150_000.0,
            "upper": 165_000.0,
        }
    ]
    assert c["platforms"] == [
        {"slug": "greenhouse", "name": "Greenhouse", "kind": "ats", "roles": 3}
    ]
    assert [job["canonical_id"] for job in c["latest"]] == ["a3", "a1", "a2"]


def test_company_pay_keeps_each_period_apart(api: TestClient) -> None:
    pay = api.get("/v1/companies/beta-labs").json()["data"]["pay"]
    assert {(p["currency"], p["period"]): p["median"] for p in pay} == {
        ("USD", "year"): 70_000.0,
        ("NGN", "month"): 6_000.0,
    }


def test_unknown_or_malformed_company_slug(api: TestClient) -> None:
    assert api.get("/v1/companies/nobody").status_code == 404
    assert api.get("/v1/companies/Not_A_Slug").status_code == 400


def test_slugs_are_ascii_and_unique(api: TestClient, migrated_engine: Engine) -> None:
    with Session(migrated_engine) as session, session.begin():
        session.add_all([Company(name="Cafe ACME!"), Company(name="Cafe Acme")])
    with Session(migrated_engine) as session:
        slugs = set(session.scalars(select(Company.slug)))
    assert {"cafe-acme", "cafe-acme-2", "cafe-acme-3", "beta-labs"} == slugs


def test_insights_are_rate_limited(api: TestClient) -> None:
    app.dependency_overrides[access.limits] = lambda: dict.fromkeys(
        ("internal", "pro", "free", "anonymous"), 1
    )
    paths = ["/v1/insights/pulse", "/v1/companies", "/v1/companies/cafe-acme"]
    assert [api.get(path).status_code for path in paths][1:] == [429, 429]
