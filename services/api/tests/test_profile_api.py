"""CV upload, the profile, confirmed email alerts and the digest, on real Postgres, Redis and
OpenSearch (the mail provider is replaced by a recorder)."""

import io
import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import Engine, func, select, update
from sqlalchemy.orm import Session

from erio_api import access
from erio_api.deps import engine as engine_dependency
from erio_api.deps import search_alias as alias_dependency
from erio_api.main import app
from erio_api.routes import profile
from erio_core import skills
from erio_core.db.models import Company, Job
from erio_core.db.seed import sync_countries
from erio_core.db.workspace_models import WorkspaceMail, WorkspaceProfile
from erio_core.digest import MAX_BOUNCES, send_digests
from erio_core.mail import MailError, Message
from erio_core.search.index import client
from erio_ingest.indexer import sync_changed

NURSE = "Registered nurse on a ward. RN licence and BLS. Wound care, medication administration."
DEV = "Python and SQL developer. Docker and AWS are a plus."
CV = "Backend developer. Python, SQL and Docker for five years. AWS in production."


def add_job(engine: Engine, job_id: str, title: str, text: str) -> None:
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
                country_code="NG",
                remote_status="onsite",
                status="open",
                posted_at=datetime.now(UTC),
                indexed_at=datetime.now(UTC),
                apply_url=f"https://boards.example.test/{job_id}",
                description_html=f"<p>{text}</p>",
                description_text=text,
            )
        )


def refresh(engine: Engine, alias: str) -> None:
    sync_changed(engine, client(), alias, None)


@pytest.fixture
def api(migrated_engine: Engine, search_alias: str, redis_url: str) -> Iterator[TestClient]:
    sync_countries(migrated_engine)
    add_job(migrated_engine, "j_nurse", "Staff Nurse", NURSE)
    add_job(migrated_engine, "j_dev", "Backend Developer", DEV)
    refresh(migrated_engine, search_alias)
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


def word_file(text: str) -> bytes:
    xml = (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", xml)
    return buffer.getvalue()


@pytest.fixture
def outbox(monkeypatch: pytest.MonkeyPatch) -> list[Message]:
    sent: list[Message] = []
    monkeypatch.setattr(profile, "send", lambda message: sent.append(message) or True)
    return sent


def upload(api: TestClient, headers: dict[str, str], name: str, data: bytes):
    return api.post(
        "/v1/workspace/profile/resume", content=data, headers={**headers, "X-Filename": name}
    )


def with_cv(api: TestClient) -> dict[str, str]:
    headers = make(api)
    assert upload(api, headers, "cv.docx", word_file(CV)).status_code == 200
    return headers


def token_from(message: Message) -> str:
    return message.text.split("token=")[1].split()[0]


# --- the CV file ------------------------------------------------------------------------------


def test_a_cv_file_gives_its_skills_and_is_not_kept(
    api: TestClient, migrated_engine: Engine
) -> None:
    headers = make(api)
    for name, data in (("cv.docx", word_file(CV)), ("cv.txt", CV.encode())):
        body = upload(api, headers, name, data).json()
        labels = {s["label"].lower() for s in body["skills"]}
        assert {"python", "sql", "docker"} <= labels and body["kept"] is False
    stored = api.get("/v1/workspace/profile", headers=headers).json()
    assert {s["id"] for s in stored["skills"]} >= set(skills.extract_skills(CV))
    with Session(migrated_engine) as session:
        row = session.scalars(select(WorkspaceProfile)).one()
    assert "five years" not in str(row.__dict__)  # only skill ids, never the text


def test_unreadable_or_oversized_files_are_refused(api: TestClient) -> None:
    headers = make(api)
    assert upload(api, headers, "cv.exe", b"MZ\x00\x01").status_code == 415
    assert upload(api, headers, "cv.pdf", b"%PDF-broken").status_code == 422
    assert upload(api, headers, "cv.docx", b"PKnot a zip").status_code == 422
    assert upload(api, headers, "cv.txt", b" ").status_code == 422
    assert upload(api, headers, "cv.txt", b"x" * (2 * 1024 * 1024 + 1)).status_code == 413
    assert (
        upload(api, headers, "cv.txt", b"I enjoy long walks").json()["error"]["code"]
        == "no_skills_found"
    )
    assert api.post("/v1/workspace/profile/resume", content=b"x").status_code == 401


def test_the_profile_can_be_edited_and_styled(api: TestClient) -> None:
    headers = with_cv(api)
    body = api.put(
        "/v1/workspace/profile",
        json={
            "titles": ["Backend Developer", "Backend Developer", "Data Engineer"],
            "countries": ["NG", "GB"],
            "remote_only": True,
            "skills": ["python", "not-a-skill"],
            "prefs": {"accent": "teal", "density": "compact", "hidden_cards": ["stats"]},
        },
        headers=headers,
    ).json()
    assert body["titles"] == ["Backend Developer", "Data Engineer"]
    assert [s["id"] for s in body["skills"]] == ["python"]
    assert body["remote_only"] and body["prefs"]["accent"] == "teal"
    bad = api.put(
        "/v1/workspace/profile", json={"prefs": {"accent": "javascript:1"}}, headers=headers
    )
    assert bad.status_code == 400
    assert api.put("/v1/workspace/profile", json={"nope": 1}, headers=headers).status_code == 400


def test_jobs_are_found_for_the_profile(api: TestClient) -> None:
    headers = make(api)
    assert (
        api.get("/v1/workspace/profile/jobs", headers=headers).json()["error"]["code"]
        == "no_profile"
    )
    upload(api, headers, "cv.txt", CV.encode())
    found = api.get("/v1/workspace/profile/jobs", headers=headers).json()
    assert [job["job_id"] for job in found] == ["j_dev"]  # the nurse and driver jobs do not fit
    assert found[0]["score"] >= 40 and "matched" in found[0]["why"]


# --- email alerts -----------------------------------------------------------------------------


def test_nothing_is_sent_until_the_address_is_confirmed(
    api: TestClient, migrated_engine: Engine, search_alias: str, outbox: list[Message]
) -> None:
    headers = make(api)
    no_cv = api.put("/v1/workspace/mail", json={"email": "ada@example.com"}, headers=headers)
    assert no_cv.status_code == 409 and outbox == []
    upload(api, headers, "cv.txt", CV.encode())
    assert (
        api.put("/v1/workspace/mail", json={"email": "not an email"}, headers=headers).status_code
        == 400
    )
    state = api.put("/v1/workspace/mail", json={"email": "Ada@Example.com"}, headers=headers).json()
    assert state["confirmed"] is False and state["email"] == "ada@example.com"
    assert len(outbox) == 1 and outbox[0].subject == "Confirm your ERIO job alerts"
    with Session(migrated_engine) as session, session.begin():
        session.execute(
            update(WorkspaceMail).values(last_checked_at=datetime.now(UTC) - timedelta(days=3))
        )
        result = send_digests(
            session, client(), search_alias, "http://site", datetime.now(UTC), mailer=outbox.append
        )
    assert result.checked == 0 and len(outbox) == 1  # still only the confirmation


def test_confirming_then_the_digest_lists_new_matches_once(
    api: TestClient, migrated_engine: Engine, search_alias: str, outbox: list[Message]
) -> None:
    headers = with_cv(api)
    api.put("/v1/workspace/mail", json={"email": "ada@example.com"}, headers=headers)
    token = token_from(outbox[0])
    assert api.post("/v1/alerts/confirm", json={"token": "x" * 30}).status_code == 404
    assert api.post("/v1/alerts/confirm", json={"token": token}).json()["confirmed"] is True
    assert api.post("/v1/alerts/confirm", json={"token": token}).status_code == 404  # single use
    with Session(migrated_engine) as session, session.begin():
        session.execute(
            update(WorkspaceMail).values(last_checked_at=datetime.now(UTC) - timedelta(days=3))
        )
    digests: list[Message] = []
    later = datetime.now(UTC)
    with Session(migrated_engine) as session, session.begin():
        first = send_digests(
            session, client(), search_alias, "http://site", later, mailer=digests.append
        )
    assert (first.sent, first.jobs) == (1, 1)
    assert "Backend Developer" in digests[0].text and "Staff Nurse" not in digests[0].text
    assert "/jobs/j_dev" in digests[0].text and "/alerts/" in digests[0].text
    assert digests[0].unsubscribe_url and digests[0].unsubscribe_url.startswith(
        "http://site/alerts/"
    )
    with Session(migrated_engine) as session, session.begin():
        again = send_digests(
            session,
            client(),
            search_alias,
            "http://site",
            later + timedelta(days=2),
            mailer=digests.append,
        )
    assert again.sent == 0 and len(digests) == 1  # not due, and never the same job twice
    with Session(migrated_engine) as session, session.begin():
        session.execute(update(WorkspaceMail).values(last_checked_at=later - timedelta(days=3)))
        repeat = send_digests(
            session,
            client(),
            search_alias,
            "http://site",
            later + timedelta(days=3),
            mailer=digests.append,
        )
    assert repeat.sent == 0 and len(digests) == 1


def test_a_new_job_is_sent_after_the_first_digest(
    api: TestClient, migrated_engine: Engine, search_alias: str, outbox: list[Message]
) -> None:
    headers = with_cv(api)
    api.put("/v1/workspace/mail", json={"email": "ada@example.com"}, headers=headers)
    api.post("/v1/alerts/confirm", json={"token": token_from(outbox[0])})
    add_job(migrated_engine, "j_dev2", "Python Engineer", DEV)
    refresh(migrated_engine, search_alias)
    digests: list[Message] = []
    with Session(migrated_engine) as session, session.begin():
        session.execute(
            update(WorkspaceMail).values(last_checked_at=datetime.now(UTC) - timedelta(days=2))
        )
        send_digests(
            session, client(), search_alias, "http://site", datetime.now(UTC), mailer=digests.append
        )
    assert "Python Engineer" in digests[0].text and "Backend Developer" in digests[0].text


def test_a_confirmation_link_expires_and_confirmations_are_limited(
    api: TestClient, migrated_engine: Engine, outbox: list[Message], monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = with_cv(api)
    api.put("/v1/workspace/mail", json={"email": "ada@example.com"}, headers=headers)
    with Session(migrated_engine) as session, session.begin():
        session.execute(
            update(WorkspaceMail).values(confirm_sent_at=datetime.now(UTC) - timedelta(hours=49))
        )
    assert api.post("/v1/alerts/confirm", json={"token": token_from(outbox[0])}).status_code == 410
    statuses = [
        api.put(
            "/v1/workspace/mail", json={"email": f"x{n}@example.com"}, headers=headers
        ).status_code
        for n in range(4)
    ]
    assert statuses == [200, 200, 429, 429]  # three a window per workspace, one already used


def test_the_email_link_pauses_changes_and_deletes(
    api: TestClient, migrated_engine: Engine, outbox: list[Message]
) -> None:
    headers = with_cv(api)
    api.put("/v1/workspace/mail", json={"email": "ada@example.com"}, headers=headers)
    manage = outbox[0].unsubscribe_url.rsplit("/", 1)[1]
    state = api.get(f"/v1/alerts/{manage}").json()
    assert state["email"] == "a**@example.com"  # masked: the link alone does not reveal it
    patched = api.patch(f"/v1/alerts/{manage}", json={"paused": True, "frequency": "weekly"})
    assert patched.status_code == 200
    shown = api.get(f"/v1/alerts/{manage}").json()
    assert shown["paused"] is True and shown["frequency"] == "weekly"
    assert api.get("/v1/alerts/" + "z" * 24).status_code == 404
    assert api.delete(f"/v1/alerts/{manage}").status_code == 204
    assert api.get(f"/v1/alerts/{manage}").status_code == 404
    assert api.get("/v1/workspace/profile", headers=headers).json()["mail"] is None


def test_deleting_the_workspace_deletes_the_address(
    api: TestClient, migrated_engine: Engine, outbox: list[Message]
) -> None:
    headers = with_cv(api)
    api.put("/v1/workspace/mail", json={"email": "ada@example.com"}, headers=headers)
    assert api.delete("/v1/workspace", headers=headers).status_code == 204
    with Session(migrated_engine) as session:
        for model in (WorkspaceMail, WorkspaceProfile):
            assert session.scalar(select(func.count()).select_from(model)) == 0


def test_a_failing_provider_pauses_alerts_after_repeated_failures(
    api: TestClient, migrated_engine: Engine, search_alias: str, outbox: list[Message]
) -> None:
    headers = with_cv(api)
    api.put("/v1/workspace/mail", json={"email": "ada@example.com"}, headers=headers)
    api.post("/v1/alerts/confirm", json={"token": token_from(outbox[0])})

    def broken(message: Message) -> bool:
        raise MailError("provider answered 500")

    for _ in range(MAX_BOUNCES):
        with Session(migrated_engine) as session, session.begin():
            session.execute(
                update(WorkspaceMail).values(last_checked_at=datetime.now(UTC) - timedelta(days=2))
            )
            send_digests(
                session, client(), search_alias, "http://site", datetime.now(UTC), mailer=broken
            )
    with Session(migrated_engine) as session:
        mail = session.scalars(select(WorkspaceMail)).one()
    assert mail.paused is True and mail.bounces == MAX_BOUNCES and mail.sent_job_ids == []


def test_the_same_opening_listed_twice_is_one_line(
    api: TestClient, migrated_engine: Engine, search_alias: str
) -> None:
    add_job(migrated_engine, "j_dev_copy", "Backend Developer", DEV)
    refresh(migrated_engine, search_alias)
    headers = with_cv(api)
    found = api.get("/v1/workspace/profile/jobs", headers=headers).json()
    assert [job["title"] for job in found] == ["Backend Developer"]
