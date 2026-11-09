"""The anonymous workspace, saved searches, feeds and CV match on real Postgres, Redis and
OpenSearch."""

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
from defusedxml import ElementTree
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import Engine, func, select, update
from sqlalchemy.orm import Session

from erio_api import access
from erio_api.deps import engine as engine_dependency
from erio_api.deps import search_alias as alias_dependency
from erio_api.main import app
from erio_api.routes import workspace
from erio_core import saved_search
from erio_core.db.models import Company, Job
from erio_core.db.seed import sync_countries
from erio_core.db.workspace_models import (
    Application,
    SavedSearch,
    SavedSearchMatch,
    Workspace,
)
from erio_core.search.index import client
from erio_core.webhook import validate_url
from erio_ingest.indexer import sync_changed

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
HOSTS = {"hooks.example.com": ["93.184.216.34"], "private.example.com": ["10.0.0.9"]}
NURSE = "Registered nurse on a ward. RN licence and BLS. Wound care, medication administration."
DEV = "Python and SQL developer. Docker and AWS are a plus."
DRIVER = "Class A CDL required. Forklift certificate. Clean driving record."


def fake_resolver(host: str) -> list[str]:
    if host not in HOSTS:
        raise OSError("unknown host")
    return HOSTS[host]


def add_job(
    engine: Engine, job_id: str, title: str, text: str, *, status: str = "open", country: str = "NG"
) -> None:
    with Session(engine) as session, session.begin():
        company = session.scalars(select(Company).where(Company.name == "Acme")).one_or_none()
        if company is None:
            company = Company(name="Acme", domain="acme.test")
            session.add(company)
            session.flush()
        session.add(
            Job(
                canonical_id=job_id,
                title=title,
                company_id=company.id,
                role_category="healthcare",
                location_text="Lagos, Nigeria",
                country_code=country,
                remote_status="onsite",
                status=status,
                posted_at=datetime.now(UTC),
                indexed_at=datetime.now(UTC),
                apply_url=f"https://boards.example.test/{job_id}",
                description_html=f"<p>{text}</p>",
                description_text=text,
            )
        )


@pytest.fixture
def api(
    migrated_engine: Engine, search_alias: str, redis_url: str, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    sync_countries(migrated_engine)
    add_job(migrated_engine, "j_nurse", "Staff Nurse", NURSE)
    add_job(migrated_engine, "j_dev", "Backend Developer", DEV)
    add_job(migrated_engine, "j_driver", "Delivery Driver", DRIVER)
    sync_changed(migrated_engine, client(), search_alias, None)
    monkeypatch.setattr(workspace, "validate_url", lambda url: validate_url(url, fake_resolver))
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


def make(api: TestClient) -> dict[str, str]:
    response = api.post("/v1/workspace")
    assert response.status_code == 201
    return {"X-Workspace-Token": response.json()["token"]}


def refresh(engine: Engine, alias: str) -> None:
    sync_changed(engine, client(), alias, None)


# --- the workspace itself ---------------------------------------------------------------------


def test_only_the_hash_of_the_token_is_stored(api: TestClient, migrated_engine: Engine) -> None:
    token = make(api)["X-Workspace-Token"]
    assert token.startswith("erw_") and len(token) == 47  # 256 bits, URL-safe
    with Session(migrated_engine) as session:
        stored = session.scalars(select(Workspace.token_hash)).all()
    assert stored == [access.hash_token(token)] and token not in stored[0]
    assert make(api)["X-Workspace-Token"] != token


def test_requests_need_a_valid_token_and_workspaces_are_separate(api: TestClient) -> None:
    assert api.get("/v1/workspace").status_code == 401
    assert (
        api.get("/v1/workspace", headers={"X-Workspace-Token": "erw_" + "a" * 43}).status_code
        == 401
    )
    assert api.get("/v1/workspace", headers={"X-Workspace-Token": "short"}).status_code == 401
    mine, other = make(api), make(api)
    saved = api.post("/v1/workspace/applications", json={"job_id": "j_nurse"}, headers=mine).json()
    assert api.get(f"/v1/workspace/applications/{saved['id']}", headers=other).status_code == 404
    assert api.delete(f"/v1/workspace/applications/{saved['id']}", headers=other).status_code == 404
    assert api.get("/v1/workspace/applications", headers=other).json()["data"] == []


def test_workspace_creation_and_use_are_rate_limited(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(workspace, "CREATE_PER_MINUTE", 2)
    assert api.post("/v1/workspace").status_code == 201
    assert api.post("/v1/workspace").status_code == 201
    assert api.post("/v1/workspace").status_code == 429
    monkeypatch.setattr(workspace, "WORKSPACE_PER_MINUTE", 3)
    monkeypatch.setattr(workspace, "CREATE_PER_MINUTE", 100)
    headers = make(api)
    statuses = [api.get("/v1/workspace", headers=headers).status_code for _ in range(4)]
    assert statuses == [200, 200, 200, 429]


def test_deleting_the_workspace_deletes_everything(
    api: TestClient, migrated_engine: Engine
) -> None:
    headers = make(api)
    api.post("/v1/workspace/applications", json={"job_id": "j_nurse"}, headers=headers)
    api.post(
        "/v1/workspace/searches", json={"name": "nurses", "params": {"q": "nurse"}}, headers=headers
    )
    assert api.delete("/v1/workspace", headers=headers).status_code == 204
    with Session(migrated_engine) as session:
        for model in (Workspace, Application, SavedSearch, SavedSearchMatch):
            assert session.scalar(select(func.count()).select_from(model)) == 0, model
    assert api.get("/v1/workspace", headers=headers).status_code == 401


def test_workspaces_unused_for_a_year_are_deleted(api: TestClient, migrated_engine: Engine) -> None:
    old, fresh = make(api), make(api)
    api.post("/v1/workspace/applications", json={"job_id": "j_nurse"}, headers=old)
    with Session(migrated_engine) as session, session.begin():
        session.execute(
            update(Workspace)
            .where(Workspace.token_hash == access.hash_token(old["X-Workspace-Token"]))
            .values(last_used_at=datetime.now(UTC) - timedelta(days=366))
        )
    with Session(migrated_engine) as session, session.begin():
        assert saved_search.delete_unused_workspaces(session, datetime.now(UTC)) == 1
    with Session(migrated_engine) as session:
        assert session.scalar(select(func.count()).select_from(Workspace)) == 1
        assert session.scalar(select(func.count()).select_from(Application)) == 0
    assert api.get("/v1/workspace", headers=fresh).status_code == 200


# --- saved jobs and the tracker ---------------------------------------------------------------


def test_saving_a_job_copies_its_facts_and_is_idempotent(api: TestClient) -> None:
    headers = make(api)
    first = api.post("/v1/workspace/applications", json={"job_id": "j_nurse"}, headers=headers)
    again = api.post("/v1/workspace/applications", json={"job_id": "j_nurse"}, headers=headers)
    body = first.json()
    assert body["title"] == "Staff Nurse" and body["company"] == "Acme"
    assert body["stage"] == "saved" and body["job"]["status"] == "open"
    assert again.json()["id"] == body["id"]
    assert api.get("/v1/workspace/saved-ids", headers=headers).json() == {"job_ids": ["j_nurse"]}
    assert (
        api.post("/v1/workspace/applications", json={"job_id": "nope"}, headers=headers).status_code
        == 404
    )


def test_stages_notes_dates_and_timeline(api: TestClient) -> None:
    headers = make(api)
    app_id = api.post(
        "/v1/workspace/applications", json={"job_id": "j_dev"}, headers=headers
    ).json()["id"]
    url = f"/v1/workspace/applications/{app_id}"
    moved = api.patch(
        url, json={"stage": "applied", "notes": "Sent CV via the site"}, headers=headers
    )
    assert (
        moved.json()["stage"] == "applied"
        and moved.json()["applied_on"] == date.today().isoformat()
    )
    api.patch(url, json={"follow_up_on": "2030-01-01"}, headers=headers)
    api.post(f"{url}/events", json={"text": "Recruiter called"}, headers=headers)
    detail = api.get(url, headers=headers).json()
    assert detail["notes"] == "Sent CV via the site"
    kinds = [e["kind"] for e in detail["events"]]
    assert kinds == ["note", "reminder", "stage", "created"]  # newest first
    assert api.patch(url, json={"stage": "hired"}, headers=headers).status_code == 400
    assert (
        api.get("/v1/workspace/applications?stage=applied", headers=headers).json()["data"][0]["id"]
        == app_id
    )
    summary = api.get("/v1/workspace", headers=headers).json()
    assert summary["counts"]["applied"] == 1 and summary["counts"]["saved"] == 0


def test_manual_applications_and_validation(api: TestClient) -> None:
    headers = make(api)
    made = api.post(
        "/v1/workspace/applications",
        json={
            "title": "Chef",
            "company": "Cafe",
            "stage": "interviewing",
            "url": "https://cafe.test/j",
        },
        headers=headers,
    )
    assert made.status_code == 201 and made.json()["job"] is None
    assert (
        api.post("/v1/workspace/applications", json={"title": "x"}, headers=headers).status_code
        == 400
    )
    bad_url = {"title": "x", "company": "y", "url": "javascript:alert(1)"}
    assert api.post("/v1/workspace/applications", json=bad_url, headers=headers).status_code == 400


def test_nudges_for_stalled_applications_and_due_follow_ups(
    api: TestClient, migrated_engine: Engine
) -> None:
    headers = make(api)
    a = api.post(
        "/v1/workspace/applications", json={"job_id": "j_dev", "stage": "applied"}, headers=headers
    ).json()
    b = api.post("/v1/workspace/applications", json={"job_id": "j_nurse"}, headers=headers).json()
    assert a["nudge"] is None
    with Session(migrated_engine) as session, session.begin():
        session.execute(
            update(Application)
            .where(Application.id == a["id"])
            .values(updated_at=datetime.now(UTC) - timedelta(days=20))
        )
    api.patch(
        f"/v1/workspace/applications/{b['id']}",
        json={"follow_up_on": "2020-01-01"},
        headers=headers,
    )
    rows = {
        r["id"]: r for r in api.get("/v1/workspace/applications", headers=headers).json()["data"]
    }
    assert rows[a["id"]]["nudge"] == "No movement for 20 days"
    assert "Follow-up was due" in rows[b["id"]]["nudge"]


def test_a_closed_job_shows_up_and_can_be_acknowledged(
    api: TestClient, migrated_engine: Engine
) -> None:
    headers = make(api)
    saved = api.post(
        "/v1/workspace/applications", json={"job_id": "j_driver"}, headers=headers
    ).json()
    with Session(migrated_engine) as session, session.begin():
        session.execute(
            update(Job)
            .where(Job.canonical_id == "j_driver")
            .values(status="closed", closed_at=datetime.now(UTC))
        )
    row = api.get("/v1/workspace/applications", headers=headers).json()["data"][0]
    assert row["job"]["status"] == "closed" and row["job"]["changes"] == ["closed"]
    api.post(f"/v1/workspace/applications/{saved['id']}/ack", headers=headers)
    row = api.get("/v1/workspace/applications", headers=headers).json()["data"][0]
    assert row["job"]["changes"] == []
    events = api.get(f"/v1/workspace/applications/{saved['id']}", headers=headers).json()["events"]
    assert events[0]["kind"] == "job_closed"


def test_caps_and_size_limits(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    headers = make(api)
    monkeypatch.setattr(workspace, "MAX_SAVED", 1)
    assert (
        api.post(
            "/v1/workspace/applications", json={"job_id": "j_dev"}, headers=headers
        ).status_code
        == 201
    )
    over = api.post("/v1/workspace/applications", json={"job_id": "j_nurse"}, headers=headers)
    assert over.status_code == 409 and over.json()["error"]["code"] == "limit_reached"
    monkeypatch.setattr(workspace, "MAX_APPLICATIONS", 1)
    assert (
        api.post(
            "/v1/workspace/applications",
            json={"title": "a", "company": "b", "stage": "applied"},
            headers=headers,
        ).status_code
        == 409
    )
    app_id = api.get("/v1/workspace/applications", headers=headers).json()["data"][0]["id"]
    url = f"/v1/workspace/applications/{app_id}"
    assert api.patch(url, json={"notes": "x" * (64 * 1024)}, headers=headers).status_code == 200
    assert api.patch(url, json={"notes": "x" * (64 * 1024 + 1)}, headers=headers).status_code == 400
    huge = api.post(
        "/v1/workspace/applications",
        content=b"{" + b" " * (130 * 1024) + b"}",
        headers=headers | {"content-type": "application/json"},
    )
    assert huge.status_code == 413
    monkeypatch.setattr(workspace, "MAX_NOTES_TOTAL_BYTES", 70 * 1024)
    api.post("/v1/workspace/applications", json={"title": "a", "company": "b"}, headers=headers)
    monkeypatch.setattr(workspace, "MAX_APPLICATIONS", 100)
    monkeypatch.setattr(workspace, "MAX_SAVED", 100)
    full = api.post(
        "/v1/workspace/applications",
        json={"title": "c", "company": "d", "notes": "y" * (10 * 1024)},
        headers=headers,
    )
    assert full.status_code == 409


# --- saved searches, feeds and webhooks ---------------------------------------------------------


def test_saved_search_counts_new_matches_and_serves_an_atom_feed(
    api: TestClient, migrated_engine: Engine, search_alias: str
) -> None:
    headers = make(api)
    created = api.post(
        "/v1/workspace/searches",
        json={"name": "Nurses", "params": {"q": "nurse", "country": ["NG"]}},
        headers=headers,
    )
    assert created.status_code == 201
    search = created.json()
    assert search["new_count"] == 0  # the first look counts nothing as new
    feed_url = f"/v1/feeds/{search['feed_token']}.atom"
    assert len(search["feed_token"]) >= 30
    root = ElementTree.fromstring(api.get(feed_url).content)
    atom = "{http://www.w3.org/2005/Atom}"
    assert root.findtext(f"{atom}title") == "ERIO: Nurses"
    assert [e.findtext(f"{atom}title") for e in root.findall(f"{atom}entry")] == [
        "Staff Nurse at Acme (Lagos, Nigeria)"
    ]

    add_job(migrated_engine, "j_nurse2", "Night Nurse <script>", "Night nurse role")
    refresh(migrated_engine, search_alias)
    with Session(migrated_engine) as session, session.begin():
        result = saved_search.run_all(
            session, client(), search_alias, "https://erio.test", datetime.now(UTC)
        )
    assert (result.searches, result.new_matches) == (1, 1)
    listed = api.get("/v1/workspace/searches", headers=headers).json()
    assert listed[0]["new_count"] == 1
    matches = api.get(f"/v1/workspace/searches/{search['id']}/matches", headers=headers).json()
    assert [(m["job_id"], m["is_new"]) for m in matches] == [("j_nurse2", True), ("j_nurse", False)]
    # A second run finds nothing new, and the job is not counted twice.
    with Session(migrated_engine) as session, session.begin():
        again = saved_search.run_all(
            session, client(), search_alias, "https://erio.test", datetime.now(UTC)
        )
    assert again.new_matches == 0
    root = ElementTree.fromstring(api.get(feed_url).content)  # hostile text stays escaped data
    titles = [e.findtext(f"{atom}title") for e in root.findall(f"{atom}entry")]
    assert titles[0] == "Night Nurse <script> at Acme (Lagos, Nigeria)"
    link = root.find(f"{atom}entry/{atom}link")
    assert link is not None and link.get("href", "").endswith("/jobs/j_nurse2")
    seen = api.post(f"/v1/workspace/searches/{search['id']}/seen", headers=headers).json()
    assert seen["new_count"] == 0
    assert api.get("/v1/feeds/" + "z" * 30 + ".atom").status_code == 404


def test_search_filters_are_validated_and_capped(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = make(api)
    bad = api.post(
        "/v1/workspace/searches",
        json={"name": "x", "params": {"role": ["wizard"]}},
        headers=headers,
    )
    assert bad.status_code == 400
    monkeypatch.setattr(workspace, "MAX_SEARCHES", 1)
    ok = {"name": "a", "params": {"q": "nurse"}}
    assert api.post("/v1/workspace/searches", json=ok, headers=headers).status_code == 201
    assert api.post("/v1/workspace/searches", json=ok, headers=headers).status_code == 409


def test_webhook_addresses_are_checked_when_saved(api: TestClient) -> None:
    headers = make(api)
    for url in (
        "http://hooks.example.com/in",
        "https://private.example.com/in",
        "https://127.0.0.1/in",
        "https://unknown.example.com/in",
    ):
        response = api.post(
            "/v1/workspace/searches",
            json={"name": "a", "params": {"q": "x"}, "webhook_url": url},
            headers=headers,
        )
        assert response.status_code == 400, url
        assert response.json()["error"]["code"] == "invalid_webhook"
    good = api.post(
        "/v1/workspace/searches",
        json={"name": "a", "params": {"q": "x"}, "webhook_url": "https://hooks.example.com/in"},
        headers=headers,
    )
    assert good.status_code == 201


def test_webhook_gets_new_matches_and_is_switched_off_after_repeated_failures(
    api: TestClient, migrated_engine: Engine, search_alias: str
) -> None:
    headers = make(api)
    search = api.post(
        "/v1/workspace/searches",
        json={
            "name": "Devs",
            "params": {"q": "developer"},
            "webhook_url": "https://hooks.example.com/in",
        },
        headers=headers,
    ).json()
    add_job(migrated_engine, "j_dev2", "Frontend Developer", "JavaScript developer")
    refresh(migrated_engine, search_alias)
    seen: list[httpx.Request] = []
    replies = [httpx.Response(200)]

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return replies.pop(0) if replies else httpx.Response(500)

    def run() -> saved_search.RunResult:
        with Session(migrated_engine) as session, session.begin():
            return saved_search.run_all(
                session,
                client(),
                search_alias,
                "https://erio.test",
                datetime.now(UTC),
                resolver=fake_resolver,
                transport=httpx.MockTransport(handler),
            )

    assert run().webhooks_sent == 1
    import json

    payload = json.loads(seen[0].content)
    assert payload["event"] == "saved_search.matches" and payload["search"] == {"name": "Devs"}
    assert [m["id"] for m in payload["matches"]] == ["j_dev2"]
    assert payload["matches"][0]["url"] == "https://erio.test/jobs/j_dev2"
    assert "workspace" not in seen[0].content.decode()  # nothing about who the owner is
    assert run().webhooks_sent == 0 and len(seen) == 1  # nothing new, nothing sent

    add_job(migrated_engine, "j_dev3", "Data Developer", "SQL developer")
    refresh(migrated_engine, search_alias)
    for _ in range(saved_search.MAX_WEBHOOK_FAILURES):
        run()
    with Session(migrated_engine) as session:
        row = session.get_one(SavedSearch, search["id"])
        assert row.webhook_disabled and row.webhook_failures == saved_search.MAX_WEBHOOK_FAILURES
    calls = len(seen)
    run()
    assert len(seen) == calls  # a disabled webhook is left alone
    shown = api.get("/v1/workspace/searches", headers=headers).json()[0]
    assert shown["webhook_disabled"] is True


# --- export and import -----------------------------------------------------------------------


def test_export_and_import_move_a_workspace(api: TestClient) -> None:
    source, target = make(api), make(api)
    app_id = api.post(
        "/v1/workspace/applications", json={"job_id": "j_nurse"}, headers=source
    ).json()["id"]
    api.patch(
        f"/v1/workspace/applications/{app_id}",
        json={"stage": "interviewing", "notes": "Panel on Friday"},
        headers=source,
    )
    api.post(
        "/v1/workspace/searches", json={"name": "Nurses", "params": {"q": "nurse"}}, headers=source
    )
    exported = api.get("/v1/workspace/export", headers=source).json()
    assert exported["format"] == "erio-workspace"
    assert "token" not in str(exported) and "feed_token" not in str(exported)
    result = api.post("/v1/workspace/import", json=exported, headers=target).json()
    assert (result["applications_added"], result["searches_added"]) == (1, 1)
    again = api.post("/v1/workspace/import", json=exported, headers=target).json()
    assert again["applications_added"] == 0 and again["applications_skipped"] == 1
    moved = api.get("/v1/workspace/applications", headers=target).json()["data"][0]
    assert moved["stage"] == "interviewing" and moved["notes"] == "Panel on Friday"
    assert (
        api.post("/v1/workspace/import", json={"applications": "x"}, headers=target).status_code
        == 400
    )
    junk = api.post("/v1/workspace/import", content=b"not json", headers=target)
    assert junk.status_code == 400


def test_import_drops_unsafe_webhooks(api: TestClient) -> None:
    headers = make(api)
    doc = {
        "format": "erio-workspace",
        "version": 1,
        "searches": [
            {"name": "a", "params": {"q": "x"}, "webhook_url": "https://private.example.com/x"}
        ],
    }
    result = api.post("/v1/workspace/import", json=doc, headers=headers).json()
    assert result["searches_added"] == 1 and "dropped" in result["notes"][0]
    assert api.get("/v1/workspace/searches", headers=headers).json()[0]["webhook_url"] is None


# --- CV match --------------------------------------------------------------------------------


def test_match_ranks_jobs_and_explains_without_storing_the_cv(
    api: TestClient, migrated_engine: Engine
) -> None:
    cv = "Registered Nurse (RN), BLS certified. Experienced in wound care. Also know Python."
    response = api.post("/v1/match", json={"cv_text": cv})
    assert response.status_code == 200
    body = response.json()
    ranked = [(row["job"]["canonical_id"], row["score"]) for row in body["data"]]
    assert ranked[0][0] == "j_nurse" and ranked[0][1] > ranked[1][1] > 0
    top = body["data"][0]
    assert {s["id"] for s in top["matched"]} >= {"rn", "bls", "wound_care"}
    assert top["explanation"].startswith("matched:")
    assert "job also asks for" in top["explanation"]
    assert "description_text" not in top["job"] or top["job"]["description_text"] is None
    # Nothing about the CV is stored anywhere.
    with Session(migrated_engine) as session:
        for model in (Workspace, Application, SavedSearch):
            assert session.scalar(select(func.count()).select_from(model)) == 0


def test_match_by_skill_ids_filters_and_errors(api: TestClient) -> None:
    by_ids = api.post("/v1/match", json={"skills": ["cdl", "forklift"]}).json()
    assert by_ids["data"][0]["job"]["canonical_id"] == "j_driver"
    assert (
        api.post(
            "/v1/match",
            json={"skills": ["cdl"], "filters": {"country": ["KE"], "include_worldwide": False}},
        ).json()["data"]
        == []
    )
    assert api.post("/v1/match", json={}).status_code == 400
    assert api.post("/v1/match", json={"cv_text": "I like walking"}).status_code == 422
    assert api.post("/v1/match", json={"cv_text": "x" * 30_001}).status_code == 400
    skills = api.post("/v1/match/skills", json={"cv_text": "Python, SQL and Docker"}).json()[
        "skills"
    ]
    assert [s["id"] for s in skills] == ["python", "sql", "docker"]


def test_match_for_one_job_gives_requirements_and_an_apply_kit(api: TestClient) -> None:
    body = api.post("/v1/match/job/j_nurse", json={"skills": ["rn", "python"]}).json()
    assert {s["id"] for s in body["required"]} >= {"rn", "bls", "wound_care", "medication"}
    assert [s["id"] for s in body["matched"]] == ["rn"]
    assert "Staff Nurse at Acme" in body["kit"] and "never applies" in body["kit"]
    assert api.post("/v1/match/job/none", json={"skills": ["rn"]}).status_code == 404


def test_match_is_rate_limited(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from erio_api.routes import match

    monkeypatch.setattr(match, "MATCH_PER_MINUTE", 2)
    codes = [api.post("/v1/match/skills", json={"skills": ["rn"]}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_response_shapes_hold_nothing_personal(api: TestClient) -> None:
    created: dict[str, Any] = api.post("/v1/workspace").json()
    assert set(created) == {"token", "limits"}
