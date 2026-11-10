"""Scheduled workspace work: registered on the beat schedule, and the cleanup rule."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from erio_core.db.workspace_models import Application, SavedSearch, Workspace
from erio_ingest.saved_searches import cleanup_workspaces, evaluate_saved_searches
from erio_ingest.worker import app


def test_tasks_are_scheduled_and_routed() -> None:
    beat = app.conf.beat_schedule
    assert beat["evaluate-saved-searches"]["task"] == "erio.evaluate_saved_searches"
    assert beat["evaluate-saved-searches"]["schedule"] == 600.0
    assert beat["cleanup-workspaces"]["task"] == "erio.cleanup_workspaces"
    for task in ("erio.evaluate_saved_searches", "erio.cleanup_workspaces"):
        assert task in app.tasks
        assert app.amqp.router.route({}, task)["queue"].name == "pipeline"


def _workspace(session: Session, name: str, last_used: datetime) -> None:
    workspace = Workspace(token_hash=name * 64, last_used_at=last_used)
    session.add(workspace)
    session.flush()
    session.add(Application(workspace_id=workspace.id, title="t", company="c"))
    session.add(SavedSearch(workspace_id=workspace.id, name="s", params={}, feed_token=name * 30))


def test_workspaces_unused_for_twelve_months_are_removed_with_their_data(
    migrated_engine: Engine,
) -> None:
    now = datetime(2026, 11, 9, tzinfo=UTC)
    with Session(migrated_engine) as session, session.begin():
        _workspace(session, "a", now - timedelta(days=400))
        _workspace(session, "b", now - timedelta(days=364))
        _workspace(session, "c", now - timedelta(days=1))
    assert cleanup_workspaces(migrated_engine, now) == 1
    with Session(migrated_engine) as session:
        assert session.scalars(select(Workspace.token_hash).order_by(Workspace.id)).all() == [
            "b" * 64,
            "c" * 64,
        ]
        assert session.scalar(select(func.count()).select_from(Application)) == 2
        assert session.scalar(select(func.count()).select_from(SavedSearch)) == 2
    assert cleanup_workspaces(migrated_engine, now) == 0


def test_evaluating_with_no_saved_searches_does_nothing(
    migrated_engine: Engine, search_alias: str
) -> None:
    from erio_core.search.index import client

    result = evaluate_saved_searches(
        migrated_engine, client(), search_alias, "https://erio.test", datetime.now(UTC)
    )
    assert (result.searches, result.new_matches, result.errors) == (0, 0, 0)
