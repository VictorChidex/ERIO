"""A job whose pay failed the sanity check shows no pay in search results or on its page."""

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from erio_api import access
from erio_api.deps import engine as engine_dependency
from erio_api.deps import search_alias as alias_dependency
from erio_api.main import app
from erio_core.db.models import Company, Job
from erio_core.db.seed import sync_countries
from erio_core.search.index import client
from erio_ingest.indexer import sync_changed


@pytest.fixture
def api(migrated_engine: Engine, search_alias: str, redis_url: str) -> Iterator[TestClient]:
    sync_countries(migrated_engine)
    with Session(migrated_engine) as session, session.begin():
        company = Company(name="Acme", domain="acme.test")
        session.add(company)
        session.flush()
        for job_id, unreliable in (("j_ok", False), ("j_bad", True)):
            session.add(
                Job(
                    canonical_id=job_id,
                    title=f"Nurse {job_id}",
                    company_id=company.id,
                    role_category="healthcare",
                    location_text="Lagos, Nigeria",
                    country_code="NG",
                    remote_status="onsite",
                    status="open",
                    salary_min=45,
                    salary_max=60,
                    salary_currency="INR",
                    salary_period="year",
                    salary_unreliable=unreliable,
                    posted_at=datetime.now(UTC),
                    indexed_at=datetime.now(UTC),
                    apply_url=f"https://boards.example.test/{job_id}",
                    description_text="Ward nurse.",
                )
            )
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


def test_search_results_and_the_job_page_hide_unreliable_pay(api: TestClient) -> None:
    results = {j["canonical_id"]: j for j in api.get("/v1/jobs").json()["data"]}
    assert results["j_ok"]["salary_min"] == 45 and results["j_ok"]["salary_currency"] == "INR"
    assert results["j_bad"]["salary_min"] is None and results["j_bad"]["salary_period"] is None
    page = api.get("/v1/jobs/j_bad").json()["data"]
    assert (page["salary_min"], page["salary_max"], page["salary_currency"]) == (None, None, None)
    assert api.get("/v1/jobs/j_ok").json()["data"]["salary_min"] == 45
