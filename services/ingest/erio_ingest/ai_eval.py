"""Score AI models on the normalizer's labeled sets (spec section 13: quality).

For each task (role, location, salary) and each model the gateway could use
right now, every sampled labeled row is asked through a gateway routed to
that model alone, with a fresh cache, and the answers are scored the way
the rules gates score the rules engine. The rules engine is scored on the
same rows for comparison. Results are saved in ``ai_evals`` and printed. A
model serves a task in the normalizer fallback only while its latest score
reaches the task's ``min_accuracy`` (``approved_models``):

    python -m erio_ingest.ai_eval                     # every task, every usable model
    python -m erio_ingest.ai_eval --task role --model local-qwen --limit 100
"""

import argparse
import csv
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from erio_core.ai.gateway import Gateway, MemoryStore
from erio_core.ai.routing import Routing
from erio_core.ai.tasks import ai_location, ai_role, ai_salary
from erio_core.db.models import AiEval
from erio_core.normalize.gazetteer import gazetteer
from erio_core.normalize.location import LocationResult, resolve_location
from erio_core.normalize.roles import classify_role
from erio_core.normalize.salary import parse_salary
from erio_core.schemas import SalaryHint
from erio_core.settings import get_settings

TASKS = ("role", "location", "salary")


@dataclass(frozen=True)
class Score:
    task: str
    model: str
    rows: int
    answered: int
    accuracy: float
    cost_usd: float


def _rows(name: str) -> list[list[str]]:
    path = Path(get_settings().labeled_dir) / name
    lines = [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]
    return list(csv.reader(lines[1:], delimiter="\t", quoting=csv.QUOTE_NONE))


def sample(rows: list[list[str]], limit: int | None) -> list[list[str]]:
    """Evenly spread rows, so a short run still sees real and written ones."""
    if not limit or limit >= len(rows):
        return rows
    step = len(rows) / limit
    return [rows[int(i * step)] for i in range(limit)]


def _places(result: LocationResult | None) -> frozenset[str]:
    if result is None or result.review_reason:
        return frozenset({"REVIEW"})
    if result.remote_scope == "worldwide":
        return frozenset({"WORLDWIDE"})
    return frozenset({*result.eligible_country_codes, *filter(None, [result.country_code])})


def _expected_places(label: str) -> frozenset[str]:
    if label.startswith("@"):
        return frozenset(
            code for code, c in gazetteer().countries.items() if label[1:] in c.region_groups
        )
    return frozenset(label.split(","))


def _salary(got: SalaryHint | None) -> tuple[Any, ...] | None:
    return None if got is None else (got.min, got.max, got.currency, got.period)


def _expected_salary(row: list[str]) -> tuple[Any, ...] | None:
    if row[1] == "NONE":
        return None
    return (round(float(row[1])), round(float(row[2])), row[3], row[4])


def _departments(row: list[str]) -> list[str]:
    return [d.strip() for d in row[1].split(";") if d.strip()]


def _ask_role(gate: Gateway, row: list[str]) -> tuple[bool, Any]:
    outcome = ai_role(gate, row[0], _departments(row))
    return outcome.answered, outcome.value


def _ask_location(gate: Gateway, row: list[str]) -> tuple[bool, Any]:
    outcome = ai_location(gate, row[0], "")
    return outcome.answered, _places(outcome.value)


def _ask_salary(gate: Gateway, row: list[str]) -> tuple[bool, Any]:
    outcome = ai_salary(gate, row[0])
    return outcome.answered, _salary(outcome.value)


@dataclass(frozen=True)
class TaskSet:
    """A task's labeled file and how to answer and check one of its rows."""

    file: str
    rules: Callable[[list[str]], Any]
    ask: Callable[[Gateway, list[str]], tuple[bool, Any]]
    expected: Callable[[list[str]], Any]


TASK_SETS = {
    "role": TaskSet(
        "roles.tsv", lambda row: classify_role(row[0], _departments(row)), _ask_role,
        lambda row: row[2],
    ),
    "location": TaskSet(
        "locations.tsv", lambda row: _places(resolve_location(row[0])), _ask_location,
        lambda row: _expected_places(row[1]),
    ),
    "salary": TaskSet(
        "salaries.tsv", lambda row: _salary(parse_salary(row[0])), _ask_salary, _expected_salary
    ),
}  # fmt: skip


def routed_to(routing: Routing, task: str, model: str) -> Routing:
    """A copy of the routing where ``task`` uses only ``model``."""
    copy = routing.model_copy(deep=True)
    copy.tasks[task].models = [model]
    return copy


def evaluate(task: str, model: str, gateway: Gateway, rows: list[list[str]]) -> Score:
    task_set = TASK_SETS[task]
    store = MemoryStore()
    gate = gateway.rerouted(routed_to(gateway.routing, task, model), store)
    answered = correct = 0
    for row in rows:
        did_answer, value = task_set.ask(gate, row)
        answered += did_answer
        correct += did_answer and value == task_set.expected(row)
    return Score(
        task, model, len(rows), answered, correct / len(rows), sum(c.cost_usd for c in store.calls)
    )


def evaluate_rules(task: str, rows: list[list[str]]) -> Score:
    task_set = TASK_SETS[task]
    correct = sum(task_set.rules(row) == task_set.expected(row) for row in rows)
    return Score(task, "rules", len(rows), len(rows), correct / len(rows), 0.0)


def run(
    engine: Engine,
    gateway: Gateway,
    tasks: Iterable[str] = TASKS,
    models: list[str] | None = None,
    limit: int | None = None,
) -> list[Score]:
    """Score the rules and each usable model per task; save and return the scores."""
    now = datetime.now(UTC)
    scores = []
    for task in tasks:
        rows = sample(_rows(TASK_SETS[task].file), limit)
        scores.append(evaluate_rules(task, rows))
        for model in models or gateway.routing.tasks[task].models:
            if gateway.can_use(model):
                scores.append(evaluate(task, model, gateway, rows))
    with Session(engine) as session, session.begin():
        session.add_all(AiEval(at=now, **vars(score)) for score in scores)
    return scores


def approved_models(engine: Engine, routing: Routing) -> dict[str, set[str]]:
    """Per task, the models whose latest evaluation reached the task's gate."""
    latest = (
        select(AiEval.task, AiEval.model, func.max(AiEval.at).label("at"))
        .group_by(AiEval.task, AiEval.model)
        .subquery()
    )
    with Session(engine) as session:
        rows = session.execute(
            select(AiEval.task, AiEval.model, AiEval.accuracy).join(
                latest,
                (AiEval.task == latest.c.task)
                & (AiEval.model == latest.c.model)
                & (AiEval.at == latest.c.at),
            )
        ).all()
    approved: dict[str, set[str]] = {task: set() for task in routing.tasks}
    for task, model, accuracy in rows:
        if task in routing.tasks and model in routing.models:
            if accuracy >= routing.tasks[task].min_accuracy:
                approved[task].add(model)
    return approved


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--task", choices=TASKS, action="append")
    parser.add_argument("--model", action="append", help="routing model name")
    parser.add_argument("--limit", type=int, help="rows per task, spread evenly")
    args = parser.parse_args()

    from erio_ingest.worker import engine, gateway

    print(f"{'task':9} {'model':14} {'rows':>5} {'answered':>9} {'accuracy':>9} {'cost':>9}")
    for s in run(engine(), gateway(), args.task or TASKS, args.model, args.limit):
        print(
            f"{s.task:9} {s.model:14} {s.rows:5d} {s.answered:9d} "
            f"{s.accuracy:9.1%} {s.cost_usd:9.4f}"
        )


if __name__ == "__main__":
    main()
