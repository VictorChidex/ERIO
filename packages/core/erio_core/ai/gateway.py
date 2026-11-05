"""The one way ERIO calls an AI model (spec section 13).

``Gateway.complete(task, messages, output)`` walks the task's models in
order: the primary, then each fallback. It skips a model whose provider's
circuit is open, that has no price (so caps hold), or whose provider needs
a token the credential source does not have. A timeout, 429, 5xx or any
other provider failure moves on to the next model. Output must be JSON
that validates against the ``output`` Pydantic model; invalid output is
retried once on the same model, then the next model is tried.

Before any call the task's daily dollar and token caps are checked, and an
answer is first looked up in the cache, keyed by task and input, so the
same job is never sent twice. Every call is logged with task, provider,
model, tokens, latency, cost and outcome; prompts are not stored.

When every model fails, or AI is switched off, ``complete`` returns None
and the caller keeps its rules-engine result or review queue.
"""

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Protocol

import httpx
from pydantic import BaseModel, ValidationError

from erio_core.ai.providers import build_provider
from erio_core.ai.routing import ModelConfig, Routing
from erio_core.ai.types import CredentialSource, Message, NoCredentials, Provider, ProviderError
from erio_core.settings import get_settings

# A provider that fails this many calls in a row is skipped for the cooldown.
BREAKER_FAILURES = 5
BREAKER_COOLDOWN_S = 60.0


@dataclass(frozen=True)
class CallRecord:
    at: datetime
    task: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    cost_usd: float
    # ok, invalid_output, or a ProviderError kind.
    outcome: str


class GatewayStore(Protocol):
    """Where the gateway keeps its cache, spend and call log."""

    def cached(self, key: str) -> str | None: ...

    def save(self, key: str, task: str, model: str, text: str) -> None: ...

    def spent(self, task: str, day: date) -> tuple[float, int]:
        """Dollars and tokens the task has used on ``day`` (UTC)."""
        ...

    def log(self, record: CallRecord) -> None: ...


class MemoryStore:
    """In-process store, for tests and one-off evaluation runs."""

    def __init__(self) -> None:
        self.cache: dict[str, str] = {}
        self.calls: list[CallRecord] = []

    def cached(self, key: str) -> str | None:
        return self.cache.get(key)

    def save(self, key: str, task: str, model: str, text: str) -> None:
        self.cache[key] = text

    def spent(self, task: str, day: date) -> tuple[float, int]:
        today = [c for c in self.calls if c.task == task and c.at.date() == day]
        return (
            sum(c.cost_usd for c in today),
            sum(c.input_tokens + c.output_tokens for c in today),
        )

    def log(self, record: CallRecord) -> None:
        self.calls.append(record)


@dataclass(frozen=True)
class Answer[T: BaseModel]:
    value: T
    # Routing name of the model that answered, e.g. "local-qwen".
    model: str
    cached: bool


class CircuitBreaker:
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self.clock = clock
        self.failures: dict[str, int] = {}
        self.open_until: dict[str, float] = {}

    def allows(self, provider: str) -> bool:
        return self.clock() >= self.open_until.get(provider, 0.0)

    def record(self, provider: str, ok: bool) -> None:
        if ok:
            self.failures[provider] = 0
            return
        self.failures[provider] = self.failures.get(provider, 0) + 1
        if self.failures[provider] >= BREAKER_FAILURES:
            self.open_until[provider] = self.clock() + BREAKER_COOLDOWN_S
            self.failures[provider] = 0


def cache_key(task: str, messages: list[Message], schema: dict[str, object]) -> str:
    raw = json.dumps(
        [task, [[m.role, m.content] for m in messages], schema], sort_keys=True, ensure_ascii=False
    )
    return hashlib.sha256(raw.encode()).hexdigest()


class Gateway:
    def __init__(
        self,
        routing: Routing,
        store: GatewayStore,
        *,
        credentials: CredentialSource | None = None,
        client: httpx.Client | None = None,
        enabled: bool = True,
        disabled_providers: frozenset[str] = frozenset(),
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        breaker: CircuitBreaker | None = None,
        providers: dict[str, Provider] | None = None,
        approved: dict[str, set[str]] | None = None,
    ):
        self.routing = routing
        self.store = store
        self.credentials = credentials or NoCredentials()
        self.client = client or httpx.Client(timeout=get_settings().ai_timeout_s)
        self.enabled = enabled
        # Providers switched off by an operator, e.g. during an outage.
        self.disabled_providers = disabled_providers
        # Per task, the models whose labeled-set score reached the task's
        # gate; None means every model may serve (tests and evaluation runs).
        self.approved = approved
        self.now = now
        self.breaker = breaker or CircuitBreaker()
        # Built from the routing on first use; tests may pass their own.
        self._providers: dict[str, Provider] = dict(providers or {})

    def provider(self, name: str) -> Provider:
        if name not in self._providers:
            config = self.routing.providers[name]
            self._providers[name] = build_provider(
                name, config.adapter, config.base_url, self.client, config.credential is not None
            )
        return self._providers[name]

    def rerouted(self, routing: Routing, store: GatewayStore) -> "Gateway":
        """The same gateway (providers, credentials, switches) with other routing."""
        return Gateway(
            routing,
            store,
            credentials=self.credentials,
            client=self.client,
            enabled=self.enabled,
            disabled_providers=self.disabled_providers,
            now=self.now,
            providers=self._providers,
        )

    def can_use(self, model: str) -> bool:
        """Whether ``model`` (a routing name) would be called right now."""
        return self._usable(self.routing.models[model]) is not None

    def _usable(self, model: ModelConfig) -> tuple[Provider, str | None] | None:
        """The provider and token for ``model``, or None when it must be skipped."""
        if model.provider in self.disabled_providers or not model.priced:
            return None
        if not self.breaker.allows(model.provider):
            return None
        provider = self.provider(model.provider)
        credential = self.routing.providers[model.provider].credential
        token = self.credentials.token(credential) if credential else None
        if provider.needs_token and not token:
            return None
        return provider, token

    def _within_budget(self, task: str) -> bool:
        config = self.routing.tasks[task]
        usd, tokens = self.store.spent(task, self.now().date())
        return usd < config.daily_usd_cap and tokens < config.daily_token_cap

    def complete[T: BaseModel](
        self, task: str, messages: list[Message], output: type[T]
    ) -> Answer[T] | None:
        if not self.enabled:
            return None
        schema = output.model_json_schema()
        key = cache_key(task, messages, schema)
        hit = self.store.cached(key)
        if hit is not None:
            try:
                return Answer(output.model_validate_json(hit), "cache", cached=True)
            except ValidationError:
                pass  # the output model changed since; ask again
        for name in self.routing.tasks[task].models:
            if self.approved is not None and name not in self.approved.get(task, set()):
                continue
            model = self.routing.models[name]
            usable = self._usable(model)
            if usable is None:
                continue
            provider, token = usable
            for _attempt in range(2):
                if not self._within_budget(task):
                    return None
                value, retry = self._call(
                    task, name, model, provider, token, messages, schema, output
                )
                if value is not None:
                    self.store.save(key, task, name, value.model_dump_json())
                    return Answer(value, name, cached=False)
                if not retry:
                    break
        return None

    def _call[T: BaseModel](
        self,
        task: str,
        name: str,
        model: ModelConfig,
        provider: Provider,
        token: str | None,
        messages: list[Message],
        schema: dict[str, object],
        output: type[T],
    ) -> tuple[T | None, bool]:
        """One call: the validated answer, or None and whether to retry this model."""
        started = time.perf_counter()
        tokens = (0, 0)
        value: T | None = None
        retry = False
        try:
            completion = provider.complete(model.model, messages, dict(schema), token)
            tokens = (completion.input_tokens, completion.output_tokens)
            value = output.model_validate_json(completion.text)
            outcome = "ok"
        except ProviderError as error:
            outcome = error.kind
        except ValidationError:
            outcome, retry = "invalid_output", True
        # A wrong answer shape is the model's fault, not the provider's.
        self.breaker.record(model.provider, outcome in ("ok", "invalid_output"))
        self.store.log(
            CallRecord(
                at=self.now(),
                task=task,
                provider=model.provider,
                model=name,
                input_tokens=tokens[0],
                output_tokens=tokens[1],
                latency_ms=round((time.perf_counter() - started) * 1000),
                cost_usd=model.cost(*tokens),
                outcome=outcome,
            )
        )
        return value, retry
