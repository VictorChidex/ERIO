"""AI gateway: routing, fallback, retries, circuit breaker, caps, cache and logging."""

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import BaseModel

from erio_core.ai import Gateway, MemoryStore, Message, load_routing
from erio_core.ai.gateway import BREAKER_FAILURES, CircuitBreaker
from erio_core.ai.routing import Routing
from erio_core.ai.types import Completion, ProviderError

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
ASK = [Message("user", "Senior Backend Engineer")]


class Role(BaseModel):
    role: str


class Fake:
    """A provider that answers from a script: text, or a ProviderError kind."""

    def __init__(self, name: str, *replies: str, needs_token: bool = False):
        self.name = name
        self.needs_token = needs_token
        self.replies = list(replies)
        self.calls: list[str] = []

    def complete(
        self, model: str, messages: list[Message], schema: dict[str, Any], token: str | None
    ) -> Completion:
        self.calls.append(model)
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if reply.startswith("!"):
            raise ProviderError(reply[1:])  # type: ignore[arg-type]
        return Completion(reply, 100, 20)

    def embed(self, model: str, texts: list[str], token: str | None) -> list[list[float]]:
        return [[1.0] for _ in texts]


def routing(models: list[str], **task: Any) -> Routing:
    return Routing.model_validate(
        {
            "providers": {
                "a": {"adapter": "openai_compatible", "base_url": "http://a.test"},
                "b": {"adapter": "anthropic", "base_url": "http://b.test", "credential": "erio/b"},
            },
            "models": {
                "a1": {
                    "provider": "a",
                    "model": "a-1",
                    "usd_per_mtok_in": 1,
                    "usd_per_mtok_out": 5,
                },
                "b1": {
                    "provider": "b",
                    "model": "b-1",
                    "usd_per_mtok_in": 2,
                    "usd_per_mtok_out": 10,
                },
                "unpriced": {"provider": "a", "model": "a-x"},
            },
            "tasks": {
                "role": {"models": models, "daily_usd_cap": 1, "daily_token_cap": 10_000} | task
            },
        }
    )


class Vault:
    def token(self, name: str) -> str | None:
        return "token-for-tests" if name == "erio/b" else None


def gateway(route: Routing, *providers: Fake, **options: Any) -> Gateway:
    return Gateway(
        route,
        options.pop("store", MemoryStore()),
        credentials=Vault(),
        providers={p.name: p for p in providers},
        now=lambda: NOW,
        **options,
    )


GOOD = '{"role": "engineering"}'


def test_primary_answers_and_the_call_is_logged() -> None:
    store = MemoryStore()
    a = Fake("a", GOOD)
    answer = gateway(routing(["a1", "b1"]), a, Fake("b", GOOD), store=store).complete(
        "role", ASK, Role
    )

    assert answer is not None and (answer.value.role, answer.model, answer.cached) == (
        "engineering", "a1", False,
    )  # fmt: skip
    [call] = store.calls
    assert (call.task, call.provider, call.model, call.outcome) == ("role", "a", "a1", "ok")
    assert (call.input_tokens, call.output_tokens) == (100, 20)
    assert call.cost_usd == pytest.approx((100 * 1 + 20 * 5) / 1_000_000)


@pytest.mark.parametrize("kind", ["timeout", "rate_limited", "server", "rejected", "unavailable"])
def test_provider_failure_falls_back(kind: str) -> None:
    store = MemoryStore()
    answer = gateway(
        routing(["a1", "b1"]), Fake("a", f"!{kind}"), Fake("b", GOOD), store=store
    ).complete("role", ASK, Role)
    assert answer is not None and answer.model == "b1"
    assert [c.outcome for c in store.calls] == [kind, "ok"]


def test_invalid_output_is_retried_once_then_falls_back() -> None:
    a = Fake("a", "not json", '{"wrong": 1}')
    b = Fake("b", GOOD)
    store = MemoryStore()
    answer = gateway(routing(["a1", "b1"]), a, b, store=store).complete("role", ASK, Role)
    assert answer is not None and answer.model == "b1"
    assert len(a.calls) == 2
    assert [c.outcome for c in store.calls] == ["invalid_output", "invalid_output", "ok"]

    retried = gateway(routing(["a1"]), Fake("a", "nope", GOOD)).complete("role", ASK, Role)
    assert retried is not None and retried.model == "a1"


def test_every_model_failing_returns_none_for_the_rules_engine() -> None:
    assert (
        gateway(routing(["a1", "b1"]), Fake("a", "!server"), Fake("b", "!timeout")).complete(
            "role", ASK, Role
        )
        is None
    )


def test_switching_provider_is_a_config_change() -> None:
    a, b = Fake("a", GOOD), Fake("b", GOOD)
    assert gateway(routing(["b1", "a1"]), a, b).complete("role", ASK, Role).model == "b1"  # type: ignore[union-attr]
    assert (a.calls, b.calls) == ([], ["b-1"])


def test_disabled_provider_is_skipped_mid_run() -> None:
    a, b = Fake("a", GOOD), Fake("b", GOOD)
    route = routing(["a1", "b1"])
    store = MemoryStore()
    first = gateway(route, a, b, store=store).complete("role", ASK, Role)
    off = gateway(route, a, b, disabled_providers=frozenset({"a"})).complete(
        "role", [Message("user", "Data Analyst")], Role
    )
    assert (first.model, off.model) == ("a1", "b1")  # type: ignore[union-attr]


def test_only_approved_models_serve_when_approvals_are_set() -> None:
    a, b = Fake("a", GOOD), Fake("b", GOOD)
    route = routing(["a1", "b1"])
    assert gateway(route, a, b, approved={"role": {"b1"}}).complete("role", ASK, Role).model == "b1"  # type: ignore[union-attr]
    assert gateway(route, a, b, approved={}).complete("role", ASK, Role) is None
    assert a.calls == []


def test_skips_unpriced_models_and_providers_without_a_token() -> None:
    a = Fake("a", GOOD)
    b = Fake("b", GOOD, needs_token=True)

    class Empty:
        def token(self, name: str) -> str | None:
            return None

    route = routing(["unpriced", "b1", "a1"])
    gate = Gateway(
        route, MemoryStore(), credentials=Empty(), providers={"a": a, "b": b}, now=lambda: NOW
    )
    assert gate.complete("role", ASK, Role).model == "a1"  # type: ignore[union-attr]
    assert (a.calls, b.calls) == (["a-1"], [])


def test_daily_caps_stop_calls() -> None:
    store = MemoryStore()
    a = Fake("a", GOOD)
    gate = gateway(routing(["a1"], daily_token_cap=200), a, store=store)
    assert gate.complete("role", [Message("user", "one")], Role) is not None
    assert gate.complete("role", [Message("user", "two")], Role) is not None
    # 240 tokens used: over the 200 cap, so the third question is not sent.
    assert gate.complete("role", [Message("user", "three")], Role) is None
    assert len(a.calls) == 2

    pricey = gateway(routing(["b1"], daily_usd_cap=0.0001), Fake("b", GOOD))
    assert pricey.complete("role", ASK, Role) is not None
    assert pricey.complete("role", [Message("user", "again")], Role) is None


def test_cache_answers_the_same_input_without_a_call() -> None:
    store = MemoryStore()
    a = Fake("a", GOOD)
    gate = gateway(routing(["a1"]), a, store=store)
    gate.complete("role", ASK, Role)
    again = gate.complete("role", ASK, Role)
    assert again is not None and again.cached and again.value.role == "engineering"
    assert len(a.calls) == 1
    # Another task with the same input is a different question.
    other = Routing.model_validate(
        routing(["a1"]).model_dump()
        | {"tasks": {"role": routing(["a1"]).tasks["role"], "x": routing(["a1"]).tasks["role"]}}
    )
    gateway(other, a, store=store).complete("x", ASK, Role)
    assert len(a.calls) == 2


def test_switched_off_makes_no_calls() -> None:
    a = Fake("a", GOOD)
    assert gateway(routing(["a1"]), a, enabled=False).complete("role", ASK, Role) is None
    assert a.calls == []


def test_circuit_breaker_opens_after_repeated_failures() -> None:
    clock = [0.0]
    breaker = CircuitBreaker(clock=lambda: clock[0])
    a, b = Fake("a", "!server"), Fake("b", GOOD)
    gate = gateway(routing(["a1", "b1"]), a, b, breaker=breaker)
    for n in range(BREAKER_FAILURES):
        gate.complete("role", [Message("user", str(n))], Role)
    assert len(a.calls) == BREAKER_FAILURES
    gate.complete("role", [Message("user", "skips a")], Role)
    assert len(a.calls) == BREAKER_FAILURES
    clock[0] += 61
    gate.complete("role", [Message("user", "tries a again")], Role)
    assert len(a.calls) == BREAKER_FAILURES + 1


def test_shipped_routing_is_valid_and_local_first() -> None:
    route = load_routing()
    for task in ("role", "location", "salary"):
        first = route.models[route.tasks[task].models[0]]
        assert route.providers[first.provider].credential is None
    assert {p.adapter for p in route.providers.values()} == {
        "openai", "anthropic", "gemini", "openai_compatible",
    }  # fmt: skip


def test_routing_rejects_unknown_references() -> None:
    with pytest.raises(ValueError, match="unknown model"):
        routing(["missing"])
