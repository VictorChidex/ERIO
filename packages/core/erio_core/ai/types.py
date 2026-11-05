"""What every AI provider adapter speaks (spec section 13).

Adapters call each provider's documented HTTPS API with httpx, not its SDK,
so the access token travels only in a request header and the repo-wide
credential-word check needs no exceptions (decision D-17). Adapters never
read a token from the environment: the gateway hands them one from a
``CredentialSource``, which is the cloud vault in production and nothing
locally, where only a self-hosted model that needs no token is used.
"""

from dataclasses import dataclass
from typing import Any, Literal, Protocol

Role = Literal["system", "user", "assistant"]
# Why a call failed. timeout, rate_limited and server are the spec's
# fallback triggers; the gateway falls back on every kind, since a request
# one provider rejects may still suit another.
FailureKind = Literal[
    "timeout", "rate_limited", "server", "rejected", "unavailable", "bad_response"
]


@dataclass(frozen=True)
class Message:
    role: Role
    content: str


@dataclass(frozen=True)
class Completion:
    """A provider's answer: JSON text that should match the output schema."""

    text: str
    input_tokens: int
    output_tokens: int


class ProviderError(Exception):
    def __init__(self, kind: FailureKind, detail: str = ""):
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind = kind


class Provider(Protocol):
    """One provider's HTTPS API."""

    name: str
    # Whether a call needs an access token from the credential source.
    needs_token: bool

    def complete(
        self,
        model: str,
        messages: list[Message],
        schema: dict[str, Any],
        token: str | None,
    ) -> Completion:
        """Ask ``model`` for JSON matching ``schema``; raise ProviderError on failure."""
        ...

    def embed(self, model: str, texts: list[str], token: str | None) -> list[list[float]]:
        """One vector per text; providers without embeddings raise ProviderError."""
        ...


class CredentialSource(Protocol):
    def token(self, name: str) -> str | None:
        """The access token stored under ``name``, or None when there is none."""
        ...


class NoCredentials:
    """The local stack: no provider token anywhere (decision D-08)."""

    def token(self, name: str) -> str | None:
        return None
