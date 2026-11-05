"""The AI gateway's Postgres store: cache, daily spend and call log."""

from datetime import UTC, datetime, timedelta

from pydantic import BaseModel
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from erio_core.ai import Gateway, Message, load_routing
from erio_core.ai.gateway import CallRecord
from erio_core.ai.store import PostgresStore
from erio_core.ai.types import Completion
from erio_core.db.models import AiCall

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


def record(at: datetime, task: str = "role", cost: float = 0.25) -> CallRecord:
    return CallRecord(at, task, "local", "local-qwen", 300, 100, 850, cost, "ok")


def test_spend_counts_only_that_task_on_that_day(migrated_engine: Engine) -> None:
    store = PostgresStore(migrated_engine)
    store.log(record(NOW))
    store.log(record(NOW + timedelta(hours=11)))
    store.log(record(NOW - timedelta(days=1)))
    store.log(record(NOW, task="salary"))

    assert store.spent("role", NOW.date()) == (0.5, 800)
    assert store.spent("location", NOW.date()) == (0.0, 0)


def test_cache_keeps_the_first_answer(migrated_engine: Engine) -> None:
    store = PostgresStore(migrated_engine)
    assert store.cached("k" * 64) is None
    store.save("k" * 64, "role", "local-qwen", '{"role": "data"}')
    store.save("k" * 64, "role", "local-llama", '{"role": "other"}')
    assert store.cached("k" * 64) == '{"role": "data"}'


class Role(BaseModel):
    role: str


class Local:
    name = "local"
    needs_token = False

    def complete(self, model, messages, schema, token):  # type: ignore[no-untyped-def]
        return Completion('{"role": "engineering"}', 40, 6)

    def embed(self, model, texts, token):  # type: ignore[no-untyped-def]
        return []


def test_gateway_on_postgres(migrated_engine: Engine) -> None:
    gate = Gateway(
        load_routing(),
        PostgresStore(migrated_engine),
        providers={"local": Local()},
        now=lambda: NOW,
    )
    first = gate.complete("role", [Message("user", "Backend Engineer")], Role)
    second = gate.complete("role", [Message("user", "Backend Engineer")], Role)

    assert first is not None and first.model == "local-qwen" and not first.cached
    assert second is not None and second.cached
    with Session(migrated_engine) as session:
        assert session.scalar(select(func.count()).select_from(AiCall)) == 1
