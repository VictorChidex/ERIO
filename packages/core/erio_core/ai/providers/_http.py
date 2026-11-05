"""One HTTPS POST with provider failures mapped to ``ProviderError`` kinds."""

import json
from typing import Any

import httpx

from erio_core.ai.types import ProviderError


def post_json(
    client: httpx.Client, url: str, body: dict[str, Any], headers: dict[str, str]
) -> dict[str, Any]:
    try:
        response = client.post(url, json=body, headers=headers)
    except httpx.TimeoutException as error:
        raise ProviderError("timeout", type(error).__name__) from error
    except httpx.HTTPError as error:
        raise ProviderError("unavailable", type(error).__name__) from error
    if response.status_code == 429:
        raise ProviderError("rate_limited", "429")
    if response.status_code >= 500:
        raise ProviderError("server", str(response.status_code))
    if response.status_code >= 400:
        # The body says why (unknown model, bad schema); it never echoes a token.
        raise ProviderError("rejected", f"{response.status_code} {response.text[:200]}")
    try:
        data = response.json()
    except json.JSONDecodeError as error:
        raise ProviderError("bad_response", "not JSON") from error
    if not isinstance(data, dict):
        raise ProviderError("bad_response", "not a JSON object")
    return data


def require(token: str | None, provider: str) -> str:
    if not token:
        raise ProviderError("unavailable", f"no access token for {provider}")
    return token
