"""Provider adapters, by the ``adapter`` name the routing config uses."""

import httpx

from erio_core.ai.providers.anthropic import Anthropic
from erio_core.ai.providers.gemini import Gemini
from erio_core.ai.providers.openai_compatible import OpenAICompatible
from erio_core.ai.types import Provider

ADAPTERS = ("openai", "anthropic", "gemini", "openai_compatible")


def build_provider(
    name: str, adapter: str, base_url: str, client: httpx.Client, needs_token: bool
) -> Provider:
    if adapter == "anthropic":
        return Anthropic(name, base_url, client)
    if adapter == "gemini":
        return Gemini(name, base_url, client)
    if adapter in ("openai", "openai_compatible"):
        return OpenAICompatible(name, base_url, client, needs_token=needs_token)
    raise ValueError(f"unknown adapter {adapter!r}; expected one of {ADAPTERS}")
