"""Anthropic's Messages API (Claude).

Structured output: the model must call one tool whose input schema is the
output schema, and the tool input is the answer. System messages go in the
top-level ``system`` field. The token goes in the ``x-api-key`` header.
Anthropic has no embeddings endpoint.
"""

import json
from typing import Any

import httpx

from erio_core.ai.providers._http import post_json, require
from erio_core.ai.types import Completion, Message, ProviderError

VERSION = "2023-06-01"
MAX_TOKENS = 1024


class Anthropic:
    needs_token = True

    def __init__(self, name: str, base_url: str, client: httpx.Client):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.client = client

    def complete(
        self, model: str, messages: list[Message], schema: dict[str, Any], token: str | None
    ) -> Completion:
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        body: dict[str, Any] = {
            "model": model,
            "max_tokens": MAX_TOKENS,
            "temperature": 0,
            "messages": [
                {"role": m.role, "content": m.content} for m in messages if m.role != "system"
            ],
            "tools": [
                {"name": "answer", "description": "Give the answer.", "input_schema": schema}
            ],
            "tool_choice": {"type": "tool", "name": "answer"},
        }
        if system:
            body["system"] = system
        data = post_json(
            self.client,
            f"{self.base_url}/v1/messages",
            body,
            {"x-api-key": require(token, self.name), "anthropic-version": VERSION},
        )
        answer = next(
            (
                block.get("input")
                for block in data.get("content") or []
                if block.get("type") == "tool_use" and block.get("name") == "answer"
            ),
            None,
        )
        if answer is None:
            raise ProviderError("bad_response", "no answer tool call")
        usage = data.get("usage") or {}
        return Completion(
            text=json.dumps(answer),
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
        )

    def embed(self, model: str, texts: list[str], token: str | None) -> list[list[float]]:
        raise ProviderError("rejected", "Anthropic has no embeddings endpoint")
