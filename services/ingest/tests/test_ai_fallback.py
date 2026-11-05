"""AI normalization fallback on Postgres, with a stand-in model."""

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from erio_core.ai import Gateway, MemoryStore, Message, load_routing
from erio_core.ai.types import Completion, ProviderError
from erio_core.db.models import Company, FxRate, Job
from erio_core.db.seed import sync_countries, sync_sources
from erio_ingest.ai_fallback import fill_with_ai

T0 = datetime(2026, 11, 5, 9, 0, tzinfo=UTC)
LATER = T0 + timedelta(minutes=5)
ANSWERS = {
    "RoleAnswer": {"role": "operations"},
    "LocationAnswer": {
        "countries": ["ng"],
        "city": "Lagos",
        "work_type": "hybrid",
        "worldwide": False,
    },
    "SalaryAnswer": {
        "found": True,
        "quote": "Salary: NGN 3.5M - 5M monthly.",
        "min": 3500000,
        "max": 5000000,
        "currency": "ngn",
        "period": "month",
    },
}


class Model:
    """Answers each fallback question the way a good model would, or fails."""

    def __init__(
        self, name: str, failure: str | None = None, answers: dict[str, Any] | None = None
    ):
        self.name = name
        self.needs_token = False
        self.failure = failure
        self.answers = ANSWERS | (answers or {})
        self.asked: list[str] = []

    def complete(
        self, model: str, messages: list[Message], schema: dict[str, Any], token: str | None
    ) -> Completion:
        self.asked.append(schema["title"])
        if self.failure:
            raise ProviderError(self.failure)  # type: ignore[arg-type]
        return Completion(json.dumps(self.answers[schema["title"]]), 50, 10)

    def embed(self, model: str, texts: list[str], token: str | None) -> list[list[float]]:
        return []


@pytest.fixture
def engine(migrated_engine: Engine) -> Engine:
    sync_countries(migrated_engine)
    sync_sources(migrated_engine)
    with Session(migrated_engine) as session, session.begin():
        company = Company(name="Moniepoint", domain="moniepoint.com")
        session.add(company)
        session.flush()
        session.add(
            FxRate(day=date(2026, 11, 4), currency="NGN", usd_per_unit=0.0007, source="ecb")
        )
        common = {
            "company_id": company.id,
            "remote_status": "onsite",
            "apply_url": "https://example.test/apply",
            "indexed_at": T0,
            "updated_at": T0,
            "status": "open",
        }
        session.add_all(
            [
                # Rules found a role, a place and no pay talk: nothing to ask.
                Job(canonical_id="j_done", title="Backend Engineer", role_category="engineering",
                    country_code="NG", description_text="Build services.", **common),
                Job(canonical_id="j_role", title="Chief of Staff", role_category="other",
                    country_code="NG", description_text="Run the office.", **common),
                Job(canonical_id="j_place", title="Teller", role_category="operations",
                    location_text="Head office (Ikeja)", review_reason="no country found",
                    description_text="Serve customers.", **common),
                Job(canonical_id="j_pay", title="Sales Lead", role_category="sales",
                    country_code="NG",
                    description_text="Great team. Salary: NGN 3.5M - 5M monthly. Apply now.",
                    **common),
            ]
        )  # fmt: skip
    return migrated_engine


def gateway(*models: Model, disabled: frozenset[str] = frozenset()) -> Gateway:
    route = load_routing()
    route.providers["backup"] = route.providers["local"].model_copy()
    route.models["backup-model"] = route.models["local-qwen"].model_copy(
        update={"provider": "backup"}
    )
    for task in route.tasks.values():
        task.models = ["local-qwen", "backup-model"]
    return Gateway(
        route,
        MemoryStore(),
        providers={m.name: m for m in models},
        disabled_providers=disabled,
        now=lambda: T0,
    )


def jobs(engine: Engine) -> dict[str, Job]:
    with Session(engine) as session:
        return {job.canonical_id: job for job in session.scalars(select(Job))}


def test_fills_what_the_rules_left_open(engine: Engine) -> None:
    model = Model("local")

    result = fill_with_ai(engine, gateway(model), lambda: LATER)

    assert (result.looked_at, result.checked) == (3, 3)
    assert result.filled == {"role": 1, "location": 1, "salary": 1}
    assert sorted(model.asked) == ["LocationAnswer", "RoleAnswer", "SalaryAnswer"]
    found = jobs(engine)
    assert (found["j_role"].role_category, found["j_role"].ai_filled) == ("operations", ["role"])
    place = found["j_place"]
    assert (place.country_code, place.city, place.remote_status, place.review_reason) == (
        "NG", "Lagos", "hybrid", None,
    )  # fmt: skip
    assert place.lat is not None
    pay = found["j_pay"]
    assert (pay.salary_min, pay.salary_max, pay.salary_currency, pay.salary_period) == (
        3500000, 5000000, "NGN", "month",
    )  # fmt: skip
    assert pay.salary_usd_annual_min == round(3500000 * 0.0007 * 12)
    assert all(
        found[j].ai_checked_at == LATER and found[j].updated_at == LATER
        for j in ("j_role", "j_place", "j_pay")
    )
    assert found["j_done"].ai_checked_at is None and found["j_done"].updated_at == T0
    # Nothing is asked twice.
    assert fill_with_ai(engine, gateway(model), lambda: LATER).looked_at == 0


def test_every_provider_down_fails_no_job(engine: Engine) -> None:
    result = fill_with_ai(
        engine, gateway(Model("local", "server"), Model("backup", "timeout")), lambda: LATER
    )

    assert (result.looked_at, result.checked, sum(result.filled.values())) == (3, 0, 0)
    found = jobs(engine)
    assert found["j_role"].role_category == "other"
    assert found["j_place"].review_reason == "no country found"
    assert all(job.ai_checked_at is None and job.updated_at == T0 for job in found.values())


def test_disabling_a_provider_mid_run_falls_back(engine: Engine) -> None:
    local, backup = Model("local"), Model("backup")
    result = fill_with_ai(
        engine, gateway(local, backup, disabled=frozenset({"local"})), lambda: LATER
    )
    assert result.checked == 3
    assert local.asked == [] and len(backup.asked) == 3


def test_answers_that_fail_checks_are_not_used(engine: Engine) -> None:
    model = Model(
        "local",
        answers={
            "LocationAnswer": {
                "countries": ["XX"],
                "city": None,
                "work_type": "onsite",
                "worldwide": False,
            },
            "SalaryAnswer": {
                "found": True,
                "quote": "Salary: NGN 3.5M - 5M monthly.",
                "min": 9,
                "max": 1,
                "currency": "NGN",
                "period": "year",
            },
            "RoleAnswer": {"role": "other"},
        },
    )
    result = fill_with_ai(engine, gateway(model), lambda: LATER)

    # Answered, so checked; but nothing usable, so nothing filled or reindexed.
    assert (result.checked, sum(result.filled.values())) == (3, 0)
    found = jobs(engine)
    assert found["j_place"].review_reason == "no country found"
    assert found["j_pay"].salary_min is None
    assert found["j_role"].ai_checked_at == LATER and found["j_role"].updated_at == T0
