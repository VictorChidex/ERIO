"""The nightly AI evaluation: models and rules scored on the same labeled rows."""

import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from erio_core.ai import Gateway, MemoryStore, Message, load_routing
from erio_core.ai.types import Completion
from erio_core.db.models import AiEval
from erio_core.settings import get_settings
from erio_ingest.ai_eval import approved_models, run, sample

LABELED = Path(__file__).resolve().parents[3] / "fixtures" / "labeled"


class Always:
    """A model that always gives the same answers."""

    name = "local"
    needs_token = False

    def complete(
        self, model: str, messages: list[Message], schema: dict[str, Any], token: str | None
    ) -> Completion:
        answers = {
            "RoleAnswer": {"role": "engineering"},
            "LocationAnswer": {"countries": ["US"], "work_type": "onsite", "worldwide": False},
            "SalaryAnswer": {"found": False},
        }
        return Completion(json.dumps(answers[schema["title"]]), 10, 2)

    def embed(self, model: str, texts: list[str], token: str | None) -> list[list[float]]:
        return []


@pytest.fixture(autouse=True)
def labeled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "labeled_dir", str(LABELED))


def test_sample_spreads_rows() -> None:
    rows = [[str(n)] for n in range(10)]
    assert sample(rows, 5) == [["0"], ["2"], ["4"], ["6"], ["8"]]
    assert sample(rows, None) == rows


def test_scores_rules_and_each_usable_model(migrated_engine: Engine) -> None:
    gate = Gateway(load_routing(), MemoryStore(), providers={"local": Always()})

    scores = {(s.task, s.model): s for s in run(migrated_engine, gate, limit=40)}

    # Only the local models are usable: cloud models have no price or token.
    assert set(scores) == {
        (task, model)
        for task in ("role", "location", "salary")
        for model in ("rules", "local-qwen", "local-llama")
    }
    role = scores[("role", "local-qwen")]
    assert (role.rows, role.answered) == (40, 40)
    # Always "engineering" is right only on engineering rows; the rules do far better.
    assert 0.05 < role.accuracy < scores[("role", "rules")].accuracy
    assert scores[("role", "rules")].accuracy > 0.85
    salary = scores[("salary", "local-qwen")]
    assert 0 < salary.accuracy < 0.5  # right only where no salary is stated
    with Session(migrated_engine) as session:
        assert len(session.scalars(select(AiEval)).all()) == 9


def test_switching_a_task_to_another_model_is_scored_too(migrated_engine: Engine) -> None:
    gate = Gateway(load_routing(), MemoryStore(), providers={"local": Always()})
    scores = run(
        migrated_engine, gate, tasks=["role"], models=["local-llama", "claude-haiku"], limit=10
    )
    assert [(s.model, s.rows) for s in scores] == [("rules", 10), ("local-llama", 10)]


def test_only_models_whose_latest_score_passes_are_approved(migrated_engine: Engine) -> None:
    from datetime import UTC, datetime, timedelta

    now = datetime(2026, 11, 5, tzinfo=UTC)
    with Session(migrated_engine) as session, session.begin():
        for task, model, accuracy, days_ago in [
            ("role", "local-qwen", 0.95, 1),  # passed, then fell below 0.90
            ("role", "local-qwen", 0.80, 0),
            ("role", "local-llama", 0.91, 0),
            ("location", "local-qwen", 0.99, 0),
            ("salary", "local-qwen", 0.50, 0),
            ("role", "rules", 0.99, 0),
        ]:
            session.add(
                AiEval(
                    at=now - timedelta(days=days_ago), task=task, model=model, rows=10,
                    answered=10, accuracy=accuracy, cost_usd=0.0,
                )
            )  # fmt: skip

    assert approved_models(migrated_engine, load_routing()) == {
        "role": {"local-llama"},
        "location": {"local-qwen"},
        "salary": set(),
    }
