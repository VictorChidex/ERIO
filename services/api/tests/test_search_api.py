"""API v1 tests on real Postgres and OpenSearch with a small known set of jobs."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from opensearchpy import OpenSearch
from redis import Redis
from sqlalchemy import Engine, func, or_, select, update
from sqlalchemy.orm import Session

from erio_api import access
from erio_api.deps import engine as engine_dependency
from erio_api.deps import search_alias as alias_dependency
from erio_api.main import app
from erio_api.routes.live import get_enqueue
from erio_core import live
from erio_core.db.models import Company, CompanyBoard, Job, JobSource, RawPosting
from erio_core.db.seed import sync_countries, sync_sources
from erio_core.search.index import client
from erio_ingest.dedup import merge
from erio_ingest.indexer import rebuild, sync_changed

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)

# (id, title, country, eligible, work type, scope, role, salary USD, status, review, days ago)
JOBS: list[tuple[Any, ...]] = [
    ("j_ng_lagos", "Backend Engineer", "NG", [], "onsite", None, "engineering", 30_000, "open", None, 1),
    ("j_ng_remote", "Data Analyst", "NG", ["NG"], "remote", "country", "data", 20_000, "open", None, 2),
    ("j_world", "Support Engineer", None, [], "remote", "worldwide", "operations", None, "open", None, 3),
    ("j_gb_london", "Product Manager", "GB", [], "hybrid", None, "product", 150_000, "open", None, 4),
    ("j_eu_remote", "Frontend Engineer", None, ["DE", "NL"], "remote", "region", "engineering", 90_000, "open", None, 5),
    ("j_unknown", "Designer", "KE", [], "onsite", None, "design", None, "unknown", None, 6),
    ("j_closed", "Closed Role", "NG", [], "onsite", None, "sales", None, "closed", None, 7),
    ("j_review", "Mystery Role", None, [], "onsite", None, "other", None, "open", "no country", 8),
]  # fmt: skip


@pytest.fixture
def api(migrated_engine: Engine, search_alias: str, redis_url: str) -> Iterator[TestClient]:
    sync_countries(migrated_engine)
    sync_sources(migrated_engine)
    with Session(migrated_engine) as session, session.begin():
        company = Company(name="Paystack", domain="paystack.com")
        session.add(company)
        session.flush()
        board = CompanyBoard(
            company_id=company.id, source_slug="greenhouse", board_token="paystack"
        )
        session.add(board)
        session.flush()
        for n, (
            cid,
            title,
            cc,
            eligible,
            work,
            scope,
            role,
            usd,
            status,
            review,
            days,
        ) in enumerate(JOBS):
            session.add(
                Job(
                    canonical_id=cid,
                    title=title,
                    company_id=company.id,
                    role_category=role,
                    location_text="Lagos, Nigeria" if cc == "NG" else None,
                    city="Lagos" if cid == "j_ng_lagos" else None,
                    country_code=cc,
                    lat=6.45 if cc == "NG" else None,
                    lon=3.39 if cc == "NG" else None,
                    remote_status=work,
                    remote_scope=scope,
                    eligible_country_codes=eligible,
                    salary_usd_annual_min=usd,
                    status=status,
                    review_reason=review,
                    posted_at=NOW - timedelta(days=days),
                    indexed_at=NOW,
                    apply_url=f"https://boards.greenhouse.io/paystack/jobs/{n}",
                    description_html=f"<p>{title} at Paystack</p>",
                    description_text=f"{title} at Paystack",
                )
            )
            posting = RawPosting(
                source_slug="greenhouse",
                board_id=board.id,
                external_id=str(n),
                content_hash="0" * 64,
                first_seen_at=NOW,
                last_seen_at=NOW,
            )
            session.add(posting)
            session.flush()
            session.add(JobSource(job_id=cid, raw_posting_id=posting.id, is_primary=True))

    search = client()
    sync_changed(migrated_engine, search, search_alias, None)
    app.dependency_overrides[engine_dependency] = lambda: migrated_engine
    app.dependency_overrides[alias_dependency] = lambda: search_alias
    # Rate limits are tested in test_access.py; here they must not get in the way.
    app.dependency_overrides[access.redis_client] = lambda: Redis.from_url(redis_url)
    app.dependency_overrides[access.limits] = lambda: dict.fromkeys(
        ("internal", "pro", "free", "anonymous"), 10_000
    )
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def ids(response: Any) -> set[str]:
    return {job["canonical_id"] for job in response.json()["data"]}


def test_lists_only_open_resolved_jobs(api: TestClient) -> None:
    response = api.get("/v1/jobs")
    assert response.status_code == 200
    assert ids(response) == {"j_ng_lagos", "j_ng_remote", "j_world", "j_gb_london", "j_eu_remote"}
    assert response.json()["meta"]["total"] == 5


def test_unknown_jobs_only_when_asked(api: TestClient) -> None:
    assert ids(api.get("/v1/jobs?status=unknown")) == {"j_unknown"}


def test_country_filter_includes_remote_roles_open_to_it(api: TestClient) -> None:
    # Spec step 9: Nigerian jobs, remote roles open to Nigeria, and worldwide ones.
    assert ids(api.get("/v1/jobs?country=NG")) == {"j_ng_lagos", "j_ng_remote", "j_world"}
    assert ids(api.get("/v1/jobs?country=NG&include_worldwide=false")) == {
        "j_ng_lagos",
        "j_ng_remote",
    }
    assert ids(api.get("/v1/jobs?country=DE&include_worldwide=false")) == {"j_eu_remote"}
    assert ids(api.get("/v1/jobs?country=ng,gb&include_worldwide=false")) == {
        "j_ng_lagos", "j_ng_remote", "j_gb_london",
    }  # fmt: skip


def test_country_facets_match_a_direct_database_count(
    api: TestClient, migrated_engine: Engine
) -> None:
    facets = api.get("/v1/jobs").json()["meta"]["facets"]["country"]
    with Session(migrated_engine) as session:
        for code in ("NG", "GB", "DE", "NL", "KE"):
            expected = session.scalar(
                select(func.count())
                .select_from(Job)
                .where(
                    Job.status == "open",
                    Job.review_reason.is_(None),
                    or_(Job.country_code == code, Job.eligible_country_codes.any(code)),
                )
            )
            assert facets.get(code, 0) == expected, code


def test_facets_count_every_filter_except_their_own(api: TestClient) -> None:
    meta = api.get("/v1/jobs?remote_status=remote&role=engineering").json()["meta"]
    assert meta["total"] == 1  # j_eu_remote
    # Work-type facet ignores the work-type filter: engineering jobs by type.
    assert meta["facets"]["remote_status"] == {"onsite": 1, "remote": 1}
    # Role facet ignores the role filter: remote jobs by role.
    assert meta["facets"]["role"] == {"data": 1, "engineering": 1, "operations": 1}


def test_text_salary_and_platform_filters(api: TestClient) -> None:
    assert ids(api.get("/v1/jobs?q=engineer")) == {"j_ng_lagos", "j_world", "j_eu_remote"}
    assert ids(api.get("/v1/jobs?q=backend engineer")) == {"j_ng_lagos"}
    assert ids(api.get("/v1/jobs?salary_min_usd=90000")) == {"j_gb_london", "j_eu_remote"}
    assert ids(api.get("/v1/jobs?platform=greenhouse")) == ids(api.get("/v1/jobs"))
    assert ids(api.get("/v1/jobs?platform=lever")) == set()


def test_company_location_and_employment_type_filters(api: TestClient) -> None:
    every = ids(api.get("/v1/jobs"))
    assert ids(api.get("/v1/jobs?company=paystack")) == every
    assert ids(api.get("/v1/jobs?company=paystack.com")) == every
    assert ids(api.get("/v1/jobs?company=stripe")) == set()
    lagos = ids(api.get("/v1/jobs?location=lagos"))
    assert lagos and lagos <= ids(api.get("/v1/jobs?country=NG&include_worldwide=false"))
    assert ids(api.get("/v1/jobs?employment_type=contract")) == set()
    assert api.get("/v1/jobs?employment_type=gig").status_code == 400


def test_sorting(api: TestClient) -> None:
    recent = [j["canonical_id"] for j in api.get("/v1/jobs").json()["data"]]
    assert recent == ["j_ng_lagos", "j_ng_remote", "j_world", "j_gb_london", "j_eu_remote"]
    top_paid = api.get("/v1/jobs?sort=salary").json()["data"][0]["canonical_id"]
    assert top_paid == "j_gb_london"


def test_cursor_pagination_visits_every_job_once(api: TestClient) -> None:
    seen: list[str] = []
    url = "/v1/jobs?per_page=2"
    while url:
        body = api.get(url).json()
        seen += [job["canonical_id"] for job in body["data"]]
        cursor = body["meta"]["next_cursor"]
        url = f"/v1/jobs?per_page=2&cursor={cursor}" if cursor else ""
    assert sorted(seen) == sorted(set(seen)) and len(seen) == 5


def test_list_items_follow_the_job_record_shape(api: TestClient) -> None:
    job = api.get("/v1/jobs?country=NG&include_worldwide=false&q=backend").json()["data"][0]
    assert job["company"] == {"name": "Paystack", "domain": "paystack.com", "logo_url": None}
    assert (job["country_code"], job["city"], job["remote_status"]) == ("NG", "Lagos", "onsite")
    assert job["sources"] == ["greenhouse"]
    assert job["description_html"] is None  # full text comes from /v1/jobs/{id}


def test_single_job_has_its_full_description(api: TestClient) -> None:
    job = api.get("/v1/jobs/j_ng_lagos").json()["data"]
    assert job["description_html"] == "<p>Backend Engineer at Paystack</p>"
    assert job["sources"] == ["greenhouse"]
    assert api.get("/v1/jobs/j_review").status_code == 404


@pytest.mark.parametrize(
    ("url", "code"),
    [
        ("/v1/jobs?country=Nigeria", "invalid_parameter"),
        ("/v1/jobs?role=astronaut", "invalid_parameter"),
        ("/v1/jobs?per_page=500", "invalid_parameter"),
        ("/v1/jobs?cursor=not-a-cursor", "invalid_cursor"),
        ("/v1/jobs/j_missing", "not_found"),
        ("/v1/nope", "not_found"),
    ],
)
def test_errors_use_one_shape(api: TestClient, url: str, code: str) -> None:
    response = api.get(url)
    error = response.json()["error"]
    assert response.status_code in (400, 404)
    assert error["code"] == code and error["message"] and error["request_id"]
    assert response.headers["X-Request-ID"] == error["request_id"]


def test_countries_feed_the_globe(api: TestClient) -> None:
    body = api.get("/v1/countries").json()
    assert body["meta"]["countries"] == 233
    by_code = {c["code"]: c for c in body["data"]}
    assert (by_code["NG"]["job_count"], by_code["NG"]["local_job_count"]) == (2, 2)
    assert by_code["DE"]["job_count"] == 1 and by_code["DE"]["local_job_count"] == 0
    assert by_code["NG"]["cities"][0]["name"] == "Lagos"
    assert body["meta"]["worldwide_remote_jobs"] == 1


def test_coverage_lists_the_78_platforms_with_their_status(api: TestClient) -> None:
    rows = api.get("/v1/coverage").json()["data"]
    assert len(rows) == 78
    assert sum(r["kind"] == "ats" for r in rows) == 58
    assert sum(r["kind"] == "board" for r in rows) == 20
    by_slug = {r["slug"]: r for r in rows}
    assert by_slug["greenhouse"]["status"] == "Verified"
    assert by_slug["paycom"]["status"] == "Blocked" and by_slug["paycom"]["note"]


def test_platforms_and_stats(api: TestClient) -> None:
    platforms = {p["slug"]: p for p in api.get("/v1/platforms").json()["data"]}
    assert platforms["greenhouse"]["job_count"] == 5 and platforms["greenhouse"]["boards"] == 1
    assert platforms["lever"]["status"] == "indexing"  # connector ready, not yet fetched
    assert platforms["smartrecruiters"]["status"] == "paused"
    stats = api.get("/v1/stats").json()
    assert (stats["total_jobs"], stats["remote_jobs"], stats["worldwide_remote_jobs"]) == (5, 3, 1)
    assert stats["countries_with_jobs"] == 2


def test_indexer_removes_closed_jobs_and_rebuild_swaps_the_alias(
    api: TestClient, migrated_engine: Engine, search_alias: str
) -> None:
    with Session(migrated_engine) as session, session.begin():
        session.get_one(Job, "j_gb_london").status = "closed"
    sync_changed(migrated_engine, client(), search_alias, NOW - timedelta(days=1))
    assert "j_gb_london" not in ids(api.get("/v1/jobs"))

    search: OpenSearch = client()
    before = set(search.indices.get_alias(name=search_alias))
    name, count = rebuild(migrated_engine, search, search_alias)
    after = set(search.indices.get_alias(name=search_alias))
    # Searchable: the four open jobs plus j_unknown (findable with status=unknown).
    assert after == {name} and not before & after and count == 5
    assert ids(api.get("/v1/jobs")) == {"j_ng_lagos", "j_ng_remote", "j_world", "j_eu_remote"}


def test_sync_reads_each_change_once(
    api: TestClient, migrated_engine: Engine, search_alias: str
) -> None:
    with Session(migrated_engine) as session, session.begin():
        # Written a minute ago: well before the clock margin.
        session.execute(update(Job).values(updated_at=func.now() - timedelta(minutes=1)))
    first = sync_changed(migrated_engine, client(), search_alias, None)
    assert first.indexed + first.removed == 8
    with Session(migrated_engine) as session:
        stamped = session.scalars(select(Job.canonical_id).where(Job.searchable_at.is_not(None)))
        assert len(stamped.all()) == first.indexed
    # Nothing changed since: the next sync reads nothing, however often it runs.
    again = sync_changed(migrated_engine, client(), search_alias, first.watermark)
    assert (again.indexed, again.removed) == (0, 0)
    with Session(migrated_engine) as session, session.begin():
        session.get_one(Job, "j_gb_london").status = "closed"
    changed = sync_changed(migrated_engine, client(), search_alias, again.watermark)
    assert (changed.indexed, changed.removed) == (0, 1)
    assert "j_gb_london" not in ids(api.get("/v1/jobs"))


def test_merged_job_leaves_search_and_its_id_redirects(
    api: TestClient, migrated_engine: Engine, search_alias: str
) -> None:
    with Session(migrated_engine) as session, session.begin():
        # The London posting came from Ashby; Lagos (Greenhouse) stays primary.
        posting = session.scalars(
            select(RawPosting)
            .join(JobSource, JobSource.raw_posting_id == RawPosting.id)
            .where(JobSource.job_id == "j_gb_london")
        ).one()
        posting.source_slug = "ashby"
        session.flush()
        merge(session, "j_gb_london", "j_ng_lagos", "exact_key", NOW)
    sync_changed(migrated_engine, client(), search_alias, NOW - timedelta(days=1))

    listed = {job["canonical_id"]: job for job in api.get("/v1/jobs").json()["data"]}
    assert "j_gb_london" not in listed
    # The primary posting's source comes first: it is where apply_url leads.
    assert listed["j_ng_lagos"]["sources"] == ["greenhouse", "ashby"]
    response = api.get("/v1/jobs/j_gb_london", follow_redirects=False)
    assert (response.status_code, response.headers["location"]) == (301, "/v1/jobs/j_ng_lagos")
    job = api.get("/v1/jobs/j_gb_london").json()["data"]
    assert (job["canonical_id"], job["dedup_method"]) == ("j_ng_lagos", "exact_key")
    assert job["sources"] == ["greenhouse", "ashby"]


@pytest.fixture
def refreshes(api: TestClient, redis_url: str) -> Iterator[tuple[list[tuple[int, str]], Redis]]:
    """The boards a refresh queues, with the cooldown keys of earlier tests cleared."""
    redis = Redis.from_url(redis_url)
    for key in redis.scan_iter("erio:live:*"):
        redis.delete(key)
    queued: list[tuple[int, str]] = []
    app.dependency_overrides[get_enqueue] = lambda: (
        lambda board, refresh: queued.append((board, refresh))
    )
    yield queued, redis
    for key in redis.scan_iter("erio:live:*"):
        redis.delete(key)


def test_a_refresh_queues_the_boards_behind_the_search(
    api: TestClient, migrated_engine: Engine, refreshes: Any
) -> None:
    queued, redis = refreshes
    with Session(migrated_engine) as session:
        board_id = session.scalars(select(CompanyBoard.id)).one()

    started = api.post("/v1/search/refresh", params={"q": "engineer"})

    assert started.status_code == 202
    body = started.json()
    assert (body["boards"], body["done"], body["finished"], body["shared"]) == (1, 0, False, False)
    assert queued == [(board_id, body["id"])]

    waiting = api.get(f"/v1/search/refresh/{body['id']}").json()
    assert (waiting["done"], waiting["finished"]) == (0, False)
    live.board_done(redis, body["id"], new=3, changed=1)  # what the live worker does
    done = api.get(f"/v1/search/refresh/{body['id']}").json()
    assert (done["done"], done["new_postings"], done["changed_postings"], done["finished"]) == (
        1,
        3,
        1,
        True,
    )


def test_the_same_search_shares_one_refresh(api: TestClient, refreshes: Any) -> None:
    queued, _ = refreshes

    first = api.post("/v1/search/refresh", params={"q": "engineer"}).json()
    second = api.post("/v1/search/refresh", params={"q": "engineer"}).json()

    assert (second["id"], second["shared"]) == (first["id"], True)
    assert len(queued) == 1


def test_a_board_just_refreshed_is_left_alone_for_another_search(
    api: TestClient, refreshes: Any
) -> None:
    queued, _ = refreshes
    api.post("/v1/search/refresh", params={"q": "engineer"})

    other = api.post("/v1/search/refresh", params={"q": "analyst"}).json()

    assert (other["boards"], other["finished"]) == (0, True)
    assert len(queued) == 1


def test_a_refresh_needs_a_search(api: TestClient, refreshes: Any) -> None:
    response = api.post("/v1/search/refresh")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_parameter"


def test_a_busy_queue_turns_a_refresh_away(
    api: TestClient, refreshes: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(live, "queue_is_full", lambda redis: True)

    response = api.post("/v1/search/refresh", params={"q": "engineer"})

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "15"


def test_an_unknown_refresh_is_not_found(api: TestClient, refreshes: Any) -> None:
    assert api.get("/v1/search/refresh/" + "0" * 32).status_code == 404
    assert api.get("/v1/search/refresh/not-an-id").status_code == 400
