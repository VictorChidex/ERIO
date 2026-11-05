"""Google's Gemini API (generativelanguage.googleapis.com).

Structured output: ``responseMimeType`` application/json with the output
schema as ``responseJsonSchema``. Assistant turns are role ``model``, and
system messages go in ``systemInstruction``. The token goes in the
``x-goog-api-key`` header.
"""

from typing import Any

import httpx

from erio_core.ai.providers._http import post_json, require
from erio_core.ai.types import Completion, Message, ProviderError


class Gemini:
    needs_token = True

    def __init__(self, name: str, base_url: str, client: httpx.Client):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.client = client

    def _headers(self, token: str | None) -> dict[str, str]:
        return {"x-goog-api-key": require(token, self.name)}

    def complete(
        self, model: str, messages: list[Message], schema: dict[str, Any], token: str | None
    ) -> Completion:
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        body: dict[str, Any] = {
            "contents": [
                {
                    "role": "model" if m.role == "assistant" else "user",
                    "parts": [{"text": m.content}],
                }
                for m in messages
                if m.role != "system"
            ],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseJsonSchema": schema,
                "temperature": 0,
            },
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        data = post_json(
            self.client,
            f"{self.base_url}/v1beta/models/{model}:generateContent",
            body,
            self._headers(token),
        )
        try:
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(str(part.get("text") or "") for part in parts)
        except (KeyError, IndexError, TypeError) as error:
            raise ProviderError("bad_response", "no candidate text") from error
        usage = data.get("usageMetadata") or {}
        return Completion(
            text=text,
            input_tokens=int(usage.get("promptTokenCount") or 0),
            output_tokens=int(usage.get("candidatesTokenCount") or 0),
        )

    def embed(self, model: str, texts: list[str], token: str | None) -> list[list[float]]:
        data = post_json(
            self.client,
            f"{self.base_url}/v1beta/models/{model}:batchEmbedContents",
            {
                "requests": [
                    {"model": f"models/{model}", "content": {"parts": [{"text": text}]}}
                    for text in texts
                ]
            },
            self._headers(token),
        )
        try:
            return [[float(x) for x in row["values"]] for row in data["embeddings"]]
        except (KeyError, TypeError) as error:
            raise ProviderError("bad_response", "no embeddings") from error
