"""Contract tests for the AI provider adapters (spec section 13).

Each adapter must send its provider's documented request (endpoint, token
header, structured-output fields) and read its documented response. The
responses below follow each provider's API reference; live calls to the
cloud providers start once the credential vault exists (decision D-17).
"""

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from erio_core.ai.providers import build_provider
from erio_core.ai.types import Message, ProviderError

SCHEMA = {
    "type": "object",
    "properties": {"role": {"type": "string"}},
    "required": ["role"],
}
MESSAGES = [
    Message("system", "Classify the job title."),
    Message("user", "Senior Backend Engineer"),
]
TOKEN = "test-token-not-real"


class Recorder:
    def __init__(self, status: int, body: Any):
        self.status = status
        self.body = body
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status, json=self.body)

    @property
    def sent(self) -> dict[str, Any]:
        data: dict[str, Any] = json.loads(self.requests[-1].content)
        return data


def provider(adapter: str, recorder: Callable[[httpx.Request], httpx.Response], url: str) -> Any:
    client = httpx.Client(transport=httpx.MockTransport(recorder))
    return build_provider(adapter, adapter, url, client, needs_token=adapter != "openai_compatible")


OPENAI_REPLY = {
    "choices": [{"message": {"role": "assistant", "content": '{"role": "engineering"}'}}],
    "usage": {"prompt_tokens": 31, "completion_tokens": 7},
}


def test_openai() -> None:
    recorder = Recorder(200, OPENAI_REPLY)
    adapter = provider("openai", recorder, "https://api.openai.com/v1")

    answer = adapter.complete("gpt-test", MESSAGES, SCHEMA, TOKEN)

    request = recorder.requests[0]
    assert str(request.url) == "https://api.openai.com/v1/chat/completions"
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    assert recorder.sent["model"] == "gpt-test"
    assert recorder.sent["messages"][0] == {"role": "system", "content": "Classify the job title."}
    assert recorder.sent["response_format"]["json_schema"]["schema"] == SCHEMA
    assert (answer.text, answer.input_tokens, answer.output_tokens) == (
        '{"role": "engineering"}', 31, 7,
    )  # fmt: skip


def test_openai_compatible_self_hosted_needs_no_token() -> None:
    recorder = Recorder(200, OPENAI_REPLY)
    adapter = provider("openai_compatible", recorder, "http://ollama:11434/v1/")

    adapter.complete("qwen2.5:1.5b", MESSAGES, SCHEMA, None)

    assert str(recorder.requests[0].url) == "http://ollama:11434/v1/chat/completions"
    assert "authorization" not in recorder.requests[0].headers


def test_anthropic() -> None:
    recorder = Recorder(
        200,
        {
            "content": [
                {"type": "text", "text": "Here you go."},
                {"type": "tool_use", "name": "answer", "input": {"role": "engineering"}},
            ],
            "usage": {"input_tokens": 40, "output_tokens": 12},
        },
    )
    adapter = provider("anthropic", recorder, "https://api.anthropic.com")

    answer = adapter.complete("claude-test", MESSAGES, SCHEMA, TOKEN)

    request = recorder.requests[0]
    assert str(request.url) == "https://api.anthropic.com/v1/messages"
    assert request.headers["x-api-key"] == TOKEN
    assert request.headers["anthropic-version"] == "2023-06-01"
    sent = recorder.sent
    assert sent["system"] == "Classify the job title."
    assert sent["messages"] == [{"role": "user", "content": "Senior Backend Engineer"}]
    assert sent["tools"][0]["input_schema"] == SCHEMA
    assert sent["tool_choice"] == {"type": "tool", "name": "answer"}
    assert json.loads(answer.text) == {"role": "engineering"}
    assert (answer.input_tokens, answer.output_tokens) == (40, 12)


def test_gemini() -> None:
    recorder = Recorder(
        200,
        {
            "candidates": [{"content": {"role": "model", "parts": [{"text": '{"role": "data"}'}]}}],
            "usageMetadata": {"promptTokenCount": 22, "candidatesTokenCount": 5},
        },
    )
    adapter = provider("gemini", recorder, "https://generativelanguage.googleapis.com")

    answer = adapter.complete("gemini-test", MESSAGES, SCHEMA, TOKEN)

    request = recorder.requests[0]
    assert str(request.url) == (
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-test:generateContent"
    )
    assert request.headers["x-goog-api-key"] == TOKEN
    sent = recorder.sent
    assert sent["systemInstruction"] == {"parts": [{"text": "Classify the job title."}]}
    assert sent["contents"] == [{"role": "user", "parts": [{"text": "Senior Backend Engineer"}]}]
    assert sent["generationConfig"]["responseJsonSchema"] == SCHEMA
    assert (answer.text, answer.input_tokens, answer.output_tokens) == ('{"role": "data"}', 22, 5)


def test_embeddings() -> None:
    openai = Recorder(
        200, {"data": [{"index": 1, "embedding": [3, 4]}, {"index": 0, "embedding": [1, 2]}]}
    )
    vectors = provider("openai", openai, "https://api.openai.com/v1").embed("e", ["a", "b"], TOKEN)
    assert vectors == [[1.0, 2.0], [3.0, 4.0]]
    gemini = Recorder(200, {"embeddings": [{"values": [0.5]}, {"values": [0.25]}]})
    adapter = provider("gemini", gemini, "https://generativelanguage.googleapis.com")
    assert adapter.embed("e", ["a", "b"], TOKEN) == [[0.5], [0.25]]
    assert gemini.sent["requests"][0]["model"] == "models/e"
    with pytest.raises(ProviderError):
        provider("anthropic", Recorder(200, {}), "https://api.anthropic.com").embed(
            "e", ["a"], TOKEN
        )


@pytest.mark.parametrize(
    ("status", "kind"), [(429, "rate_limited"), (503, "server"), (400, "rejected")]
)
@pytest.mark.parametrize("adapter", ["openai", "anthropic", "gemini", "openai_compatible"])
def test_failures_map_to_kinds(adapter: str, status: int, kind: str) -> None:
    with pytest.raises(ProviderError) as error:
        provider(adapter, Recorder(status, {"error": "x"}), "https://x.test").complete(
            "m", MESSAGES, SCHEMA, TOKEN
        )
    assert error.value.kind == kind


@pytest.mark.parametrize("adapter", ["openai", "anthropic", "gemini", "openai_compatible"])
def test_timeouts_and_odd_responses(adapter: str) -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(ProviderError) as error:
        provider(adapter, timeout, "https://x.test").complete("m", MESSAGES, SCHEMA, TOKEN)
    assert error.value.kind == "timeout"
    with pytest.raises(ProviderError) as error:
        provider(adapter, Recorder(200, {"unexpected": True}), "https://x.test").complete(
            "m", MESSAGES, SCHEMA, TOKEN
        )
    assert error.value.kind == "bad_response"


@pytest.mark.parametrize("adapter", ["openai", "anthropic", "gemini"])
def test_cloud_providers_refuse_to_call_without_a_token(adapter: str) -> None:
    recorder = Recorder(200, OPENAI_REPLY)
    with pytest.raises(ProviderError) as error:
        provider(adapter, recorder, "https://x.test").complete("m", MESSAGES, SCHEMA, None)
    assert error.value.kind == "unavailable"
    assert recorder.requests == []
