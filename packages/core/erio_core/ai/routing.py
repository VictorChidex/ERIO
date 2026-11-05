"""Which model does which task (spec section 13): config, not code.

``routing.json`` (or the file named by ``ERIO_AI_ROUTING``) lists providers,
the models each offers with their prices, and for every task an ordered
list of models: the first is primary, the rest are fallbacks. Switching a
task to another provider, or adding a model, is an edit to this file.

Prices are US dollars per million tokens. A model with no price set is
never called for a capped task, so a budget can never be bypassed by a
missing number.
"""

import json
from functools import lru_cache
from importlib.resources import files
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

from erio_core.ai.providers import ADAPTERS
from erio_core.settings import get_settings


class ProviderConfig(BaseModel):
    adapter: str
    base_url: str
    # Name of the provider's token in the credential vault; None when the
    # provider needs no token (a self-hosted model).
    credential: str | None = None

    @model_validator(mode="after")
    def known_adapter(self) -> "ProviderConfig":
        if self.adapter not in ADAPTERS:
            raise ValueError(f"unknown adapter {self.adapter!r}")
        return self


class ModelConfig(BaseModel):
    provider: str
    model: str
    usd_per_mtok_in: float | None = None
    usd_per_mtok_out: float | None = None

    @property
    def priced(self) -> bool:
        return self.usd_per_mtok_in is not None and self.usd_per_mtok_out is not None

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens * (self.usd_per_mtok_in or 0)
            + output_tokens * (self.usd_per_mtok_out or 0)
        ) / 1_000_000


class TaskConfig(BaseModel):
    models: list[str] = Field(min_length=1)
    daily_usd_cap: float = Field(ge=0)
    daily_token_cap: int = Field(ge=0)


class Routing(BaseModel):
    providers: dict[str, ProviderConfig]
    models: dict[str, ModelConfig]
    tasks: dict[str, TaskConfig]

    @model_validator(mode="after")
    def references_resolve(self) -> "Routing":
        for name, model in self.models.items():
            if model.provider not in self.providers:
                raise ValueError(f"model {name}: unknown provider {model.provider!r}")
        for name, task in self.tasks.items():
            for model_name in task.models:
                if model_name not in self.models:
                    raise ValueError(f"task {name}: unknown model {model_name!r}")
        return self


def load_routing(path: str | None = None) -> Routing:
    settings = get_settings()
    path = path or settings.ai_routing_path
    raw = (
        Path(path).read_text(encoding="utf-8")
        if path
        else files("erio_core.ai").joinpath("routing.json").read_text(encoding="utf-8")
    )
    routing = Routing.model_validate(json.loads(raw))
    # Where a provider lives can differ per environment (the compose network
    # locally); the routing file holds the public address.
    for name, url in settings.ai_provider_urls.items():
        if name in routing.providers:
            routing.providers[name].base_url = url
    return routing


@lru_cache
def default_routing() -> Routing:
    return load_routing()
