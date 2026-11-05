"""The gateway's cache, spend and call log in Postgres."""

from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import Engine, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from erio_core.ai.gateway import CallRecord
from erio_core.db.models import AiCacheEntry, AiCall


class PostgresStore:
    def __init__(self, engine: Engine):
        self.engine = engine

    def cached(self, key: str) -> str | None:
        with Session(self.engine) as session:
            return session.scalar(select(AiCacheEntry.answer).where(AiCacheEntry.key == key))

    def save(self, key: str, task: str, model: str, text: str) -> None:
        with Session(self.engine) as session, session.begin():
            session.execute(
                insert(AiCacheEntry)
                .values(key=key, task=task, model=model, answer=text)
                .on_conflict_do_nothing()
            )

    def spent(self, task: str, day: date) -> tuple[float, int]:
        start = datetime.combine(day, time(), tzinfo=UTC)
        with Session(self.engine) as session:
            usd, tokens = session.execute(
                select(
                    func.coalesce(func.sum(AiCall.cost_usd), 0.0),
                    func.coalesce(func.sum(AiCall.input_tokens + AiCall.output_tokens), 0),
                ).where(
                    AiCall.task == task, AiCall.at >= start, AiCall.at < start + timedelta(days=1)
                )
            ).one()
        return float(usd), int(tokens)

    def log(self, record: CallRecord) -> None:
        with Session(self.engine) as session, session.begin():
            session.add(AiCall(**vars(record)))
