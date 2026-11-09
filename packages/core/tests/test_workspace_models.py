"""The workspace tables on a real Postgres: one delete removes everything."""

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from erio_core.db.workspace_models import (
    Application,
    ApplicationEvent,
    SavedSearch,
    SavedSearchMatch,
    Workspace,
)


def _fill(session: Session, token_hash: str) -> Workspace:
    workspace = Workspace(token_hash=token_hash)
    session.add(workspace)
    session.flush()
    application = Application(
        workspace_id=workspace.id, job_id="j1", title="Nurse", company="Acme", stage="saved"
    )
    search = SavedSearch(
        workspace_id=workspace.id, name="nurses", params={"q": "nurse"}, feed_token=token_hash[:40]
    )
    session.add_all([application, search])
    session.flush()
    session.add_all(
        [
            ApplicationEvent(application_id=application.id, kind="created"),
            SavedSearchMatch(
                search_id=search.id,
                job_id="j1",
                title="Nurse",
                company="Acme",
                apply_url="https://x.test",
            ),
        ]
    )
    session.flush()
    return workspace


def test_deleting_a_workspace_deletes_everything_under_it(migrated_engine: Engine) -> None:
    with Session(migrated_engine) as session, session.begin():
        keep = _fill(session, "a" * 64)
        gone = _fill(session, "b" * 64)
        keep_id, gone_id = keep.id, gone.id
    with Session(migrated_engine) as session, session.begin():
        session.delete(session.get_one(Workspace, gone_id))
    with Session(migrated_engine) as session:
        for model in (Application, ApplicationEvent, SavedSearch, SavedSearchMatch):
            assert session.scalar(select(func.count()).select_from(model)) == 1, model
        assert session.scalar(select(func.count()).select_from(Workspace)) == 1
        assert session.get_one(Workspace, keep_id).token_hash == "a" * 64


def test_a_job_is_saved_once_per_workspace_and_stages_are_checked(migrated_engine: Engine) -> None:
    with Session(migrated_engine) as session, session.begin():
        workspace_id = _fill(session, "c" * 64).id
    with pytest.raises(IntegrityError), Session(migrated_engine) as session, session.begin():
        session.add(Application(workspace_id=workspace_id, job_id="j1", title="t", company="c"))
    with pytest.raises(IntegrityError), Session(migrated_engine) as session, session.begin():
        session.add(Application(workspace_id=workspace_id, title="t", company="c", stage="hired"))
