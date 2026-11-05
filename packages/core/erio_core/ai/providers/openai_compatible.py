"""The OpenAI chat-completions format: OpenAI itself, and every provider or
self-hosted server that speaks it (Mistral, Groq, Together, DeepSeek, vLLM,
Ollama).

Structured output uses ``response_format`` with a JSON schema. The token,
when the provider needs one, goes in the ``Authorization`` header.
"""

from typing import Any

import httpx

from erio_core.ai.providers._http import post_json, require
from erio_core.ai.types import Completion, Message, ProviderError


class OpenAICompatible:
    def __init__(self, name: str, base_url: str, client: httpx.Client, *, needs_token: bool = True):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.client = client
        self.needs_token = needs_token

    def _headers(self, token: str | None) -> dict[str, str]:
        if self.needs_token:
            return {"Authorization": f"Bearer {require(token, self.name)}"}
        return {}

    def complete(
        self, model: str, messages: list[Message], schema: dict[str, Any], token: str | None
    ) -> Completion:
        data = post_json(
            self.client,
            f"{self.base_url}/chat/completions",
            {
                "model": model,
                "messages": [{"role": m.role, "content": m.content} for m in messages],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "answer", "schema": schema},
                },
                "temperature": 0,
            },
            self._headers(token),
        )
        try:
            text = data["choices"][0]["message"]["content"]
            usage = data.get("usage") or {}
            return Completion(
                text=str(text),
                input_tokens=int(usage.get("prompt_tokens") or 0),
                output_tokens=int(usage.get("completion_tokens") or 0),
            )
        except (KeyError, IndexError, TypeError) as error:
            raise ProviderError("bad_response", "no message content") from error

    def embed(self, model: str, texts: list[str], token: str | None) -> list[list[float]]:
        data = post_json(
            self.client,
            f"{self.base_url}/embeddings",
            {"model": model, "input": texts},
            self._headers(token),
        )
        try:
            rows = sorted(data["data"], key=lambda row: row["index"])
            return [[float(x) for x in row["embedding"]] for row in rows]
        except (KeyError, TypeError) as error:
            raise ProviderError("bad_response", "no embeddings") from error
