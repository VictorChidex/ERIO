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


def test_company_directory_can_add_a_30_day_trend(api: TestClient) -> None:
    plain = api.get("/v1/companies").json()["data"][0]
    assert plain["trend"] is None and plain["added_30d"] is None

    rows = {c["slug"]: c for c in api.get("/v1/companies?trend=true").json()["data"]}
    acme = rows["cafe-acme"]
    assert len(acme["trend"]) == 30
    # a1 two days ago, a2 ten days ago, a4 twenty days ago, a3 (no date) today.
    assert acme["added_30d"] == 4 == sum(acme["trend"])
    assert (acme["trend"][-1], acme["trend"][-3], acme["trend"][-11], acme["trend"][-21]) == (
        1,
        1,
        1,
        1,
    )
    assert rows["beta-labs"]["added_30d"] == 1  # b2; b1 was posted 100 days ago


# --- pay explorer and role pages: sets big enough to pass the 10-job rule ---

BULK = "Bulk Co"
OTHER = "Other Co"


def _bulk_jobs() -> list[dict[str, Any]]:
    """Twelve USD engineering jobs (midpoints 10k..120k) and others that test the rules."""
    jobs: list[dict[str, Any]] = []

    def add(key: str, n: int, **fields: Any) -> None:
        for i in range(n):
            jobs.append({"id": f"{key}{i}", "i": i} | fields)

    add("eu", 12, co=BULK, title="Engineer", role="engineering", cc="NG",
        pay=lambda i: ((i + 1) * 10_000, (i + 1) * 10_000, "USD", "year"), posted=lambda i: i,
        city=lambda i: "Lagos" if i < 8 else "Abuja",
        work=lambda i: "remote" if i < 3 else "onsite")  # fmt: skip
    # Monthly pay is never mixed into yearly figures.
    add("en", 12, co=BULK, title="Engineer", role="engineering", cc="NG",
        pay=lambda i: (500_000, 500_000, "NGN", "month"), posted=lambda i: 5,
        city=lambda i: "Lagos", work=lambda i: "onsite")  # fmt: skip
    # Exactly ten jobs: shown.
    add("dd", 10, co=OTHER, title="Data analyst", role="data", cc="DE",
        pay=lambda i: (50_000 + 1000 * i, 50_000 + 1000 * i, "EUR", "year"), posted=lambda i: 3,
        city=lambda i: "Berlin", work=lambda i: "remote" if i % 2 == 0 else "hybrid")  # fmt: skip
    # Nine jobs: hidden, and counted as hidden.
    add("sg", 9, co=OTHER, title="Sales rep", role="sales", cc="GB",
        pay=lambda i: (40_000, 40_000, "GBP", "year"), posted=lambda i: 3,
        city=lambda i: "London", work=lambda i: "onsite")  # fmt: skip
    # Two roles that closed 3 days ago.
    add("ec", 2, co=BULK, title="Engineer", role="engineering", cc="NG", pay=lambda i: None,
        posted=lambda i: 20, city=lambda i: "Lagos", work=lambda i: "onsite", closed=3)  # fmt: skip
    return jobs


@pytest.fixture
def pay_api(migrated_engine: Engine, search_alias: str, redis_url: str) -> Iterator[TestClient]:
    sync_countries(migrated_engine)
    sync_sources(migrated_engine)
    with Session(migrated_engine) as session, session.begin():
        companies = {name: Company(name=name) for name in (BULK, OTHER)}
        for company in companies.values():
            session.add(company)
            session.flush()
        boards = {
            name: CompanyBoard(
                company_id=company.id, source_slug="greenhouse", board_token=name[:4].lower()
            )
            for name, company in companies.items()
        }
        session.add_all(boards.values())
        session.flush()
        for n, job in enumerate(_bulk_jobs()):
            i = job["i"]
            low, high, currency, period = job["pay"](i) or (None, None, None, None)
            closed = job.get("closed")
            session.add(
                Job(
                    canonical_id=job["id"],
                    title=f"{job['title']} {job['id']}",
                    company_id=companies[job["co"]].id,
                    role_category=job["role"],
                    city=job["city"](i),
                    country_code=job["cc"],
                    remote_status=job["work"](i),
                    salary_min=low,
                    salary_max=high,
                    salary_currency=currency,
                    salary_period=period,
                    status="closed" if closed else "open",
                    posted_at=NOW - timedelta(days=job["posted"](i)),
                    indexed_at=NOW,
                    closed_at=NOW - timedelta(days=closed) if closed else None,
                    apply_url=f"https://example.com/{job['id']}",
                    description_text=f"{job['title']} {job['id']}",
                )
            )
            posting = RawPosting(
                source_slug="greenhouse",
                board_id=boards[job["co"]].id,
                external_id=str(n),
                content_hash="0" * 64,
                first_seen_at=NOW,
                last_seen_at=NOW,
            )
            session.add(posting)
            session.flush()
            session.add(JobSource(job_id=job["id"], raw_posting_id=posting.id, is_primary=True))
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


def test_salary_cells_are_yearly_per_currency_and_hide_small_samples(pay_api: TestClient) -> None:
    data = pay_api.get("/v1/insights/salary").json()["data"]
    assert data["min_sample"] == 10
    # Twelve USD jobs; midpoints 10k..120k. The monthly naira pay is left out, and the
    # nine British sales jobs are too few to show.
    assert data["cells"] == [
        {
            "role": "engineering",
            "country": "NG",
            "currency": "USD",
            "roles": 12,
            "lower": 37_500.0,
            "median": 65_000.0,
            "upper": 92_500.0,
        },
        {
            "role": "data",
            "country": "DE",
            "currency": "EUR",
            "roles": 10,  # exactly the minimum
            "lower": 52_250.0,
            "median": 54_500.0,
            "upper": 56_750.0,
        },
    ]
    assert data["hidden_cells"] == 1
    assert [(c["role"], c["currency"]) for c in data["by_role"]] == [
        ("engineering", "USD"),
        ("data", "EUR"),
    ]
    assert [(c["country"], c["currency"]) for c in data["by_country"]] == [
        ("NG", "USD"),
        ("DE", "EUR"),
    ]
    assert all(c["roles"] >= 10 for c in data["cells"] + data["by_role"] + data["by_country"])


def test_salary_filters_by_role_and_country(pay_api: TestClient) -> None:
    by_role = pay_api.get("/v1/insights/salary?role=data").json()["data"]
    assert [(c["role"], c["country"]) for c in by_role["cells"]] == [("data", "DE")]
    assert by_role["role"] == "data"
    by_country = pay_api.get("/v1/insights/salary?country=ng").json()["data"]
    assert by_country["country"] == "NG"
    assert [(c["role"], c["currency"]) for c in by_country["cells"]] == [("engineering", "USD")]
    both = pay_api.get("/v1/insights/salary?role=sales&country=GB").json()["data"]
    assert both["cells"] == [] and both["hidden_cells"] == 1  # nine jobs: hidden


def test_salary_rejects_unknown_filters_and_is_cached(pay_api: TestClient, redis_url: str) -> None:
    assert pay_api.get("/v1/insights/salary?role=astronaut").status_code == 400
    assert pay_api.get("/v1/insights/salary?country=nigeria").status_code == 400
    first = pay_api.get("/v1/insights/salary?role=data").json()
    key = Redis.from_url(redis_url).keys("erio:insights:salary:*")[0]
    assert 0 < Redis.from_url(redis_url).ttl(key) <= 600
    assert pay_api.get("/v1/insights/salary?role=data").json() == first


def test_role_page_figures(pay_api: TestClient) -> None:
    response = pay_api.get("/v1/insights/role/engineering")
    assert response.status_code == 200
    r = response.json()["data"]
    assert (r["slug"], r["q"]) == ("engineering", None)
    assert r["open_roles"] == 24  # the two closed ones are not open
    assert (r["remote_roles"], r["remote_pct"]) == (3, 12.5)
    assert (r["pay_stated_roles"], r["pay_stated_pct"]) == (24, 100.0)
    assert [(p["code"], p["name"], p["roles"]) for p in r["countries"]] == [("NG", "Nigeria", 24)]
    assert [(c["city"], c["country_code"], c["roles"]) for c in r["cities"]] == [
        ("Lagos", "NG", 20),
        ("Abuja", "NG", 4),
    ]
    assert r["employers"] == [{"name": BULK, "slug": "bulk-co", "roles": 24}]
    # Yearly pay only, and only where 10 or more jobs state it.
    assert r["pay"] == [
        {
            "currency": "USD",
            "period": "year",
            "roles": 12,
            "lower": 37_500.0,
            "median": 65_000.0,
            "upper": 92_500.0,
        }
    ]
    assert r["pay_sampled"] is False
    # 26 engineering roles were added within 30 days (24 open, 2 closed); 2 closed.
    assert (r["added_30d"], r["removed_30d"], r["net_30d"]) == (26, 2, 24)
    assert len(r["flow"]["days"]) == 30
    assert counts(r["roles"]) == {"engineering": 24}


def test_role_page_for_a_title(pay_api: TestClient) -> None:
    r = pay_api.get("/v1/insights/role/all?q=analyst").json()["data"]
    assert (r["slug"], r["q"], r["open_roles"]) == ("all", "analyst", 10)
    assert r["remote_roles"] == 5
    assert r["employers"][0]["slug"] == "other-co"
    assert (r["added_30d"], r["removed_30d"]) == (10, 0)
    assert [p["roles"] for p in r["pay"]] == [10]
    # Nine sales jobs state pay but are too few to give quartiles.
    sales = pay_api.get("/v1/insights/role/sales").json()["data"]
    assert (sales["open_roles"], sales["pay"]) == (9, [])


def test_role_page_rejects_unknown_roles_and_is_cached(pay_api: TestClient, redis_url: str) -> None:
    assert pay_api.get("/v1/insights/role/astronaut").status_code == 404
    assert pay_api.get("/v1/insights/role/Not_A_Slug").status_code == 400
    first = pay_api.get("/v1/insights/role/data").json()
    key = Redis.from_url(redis_url).keys("erio:insights:role:*")[0]
    assert 0 < Redis.from_url(redis_url).ttl(key) <= 600
    assert pay_api.get("/v1/insights/role/data").json() == first
