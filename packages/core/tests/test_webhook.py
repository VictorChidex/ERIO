"""Webhook delivery cannot be aimed at private networks, even through redirects."""

import json

import httpx
import pytest

from erio_core.webhook import (
    Delivery,
    WebhookRejected,
    check_url,
    deliver,
    is_public,
    validate_url,
)

PUBLIC = "93.184.216.34"
HOSTS = {
    "hooks.example.com": [PUBLIC],
    "other.example.org": ["1.1.1.1"],
    "internal.example.com": ["10.0.0.5"],
    "mixed.example.com": [PUBLIC, "192.168.1.10"],
    "metadata.example.com": ["169.254.169.254"],
    "v6.example.com": ["2606:4700:4700::1111"],
    "mapped.example.com": ["::ffff:127.0.0.1"],
    "nat64.example.com": ["64:ff9b::a00:1"],
}


def resolver(host: str) -> list[str]:
    if host not in HOSTS:
        raise OSError("no such host")
    return HOSTS[host]


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.1.2.3",
        "172.16.0.1",
        "192.168.0.1",
        "169.254.169.254",
        "100.64.0.1",
        "0.0.0.0",  # noqa: S104 (asserting that it is rejected)
        "224.0.0.1",
        "::1",
        "fe80::1",
        "fc00::1",
        "::ffff:10.0.0.1",
        "64:ff9b::a00:1",
        "2002:0a00:0001::",
        "not an address",
    ],
)
def test_non_public_addresses_are_refused(address: str) -> None:
    assert not is_public(address)


def test_public_addresses_pass() -> None:
    assert is_public("93.184.216.34") and is_public("2606:4700:4700::1111")


@pytest.mark.parametrize(
    ("url", "why"),
    [
        ("http://hooks.example.com/x", "https"),
        ("ftp://hooks.example.com/x", "https"),
        ("https://user:pw@hooks.example.com/x", "login"),
        ("https://127.0.0.1/x", "IP address"),
        ("https://[::1]/x", "IP address"),
        ("https://localhost/x", "host name"),
        ("https://printer.local/x", "local"),
        ("https://hooks.example.com:8080/x", "ports"),
        ("https://internal.example.com/x", "non-public"),
        ("https://mixed.example.com/x", "non-public"),
        ("https://metadata.example.com/x", "non-public"),
        ("https://mapped.example.com/x", "non-public"),
        ("https://nat64.example.com/x", "non-public"),
        ("https://nope.example.com/x", "resolve"),
        ("https://hooks.example.com/" + "a" * 2100, "usable"),
        ("https://hooks.example.com/has space", "usable"),
        ("", "https"),
    ],
)
def test_bad_urls_are_rejected_with_a_reason(url: str, why: str) -> None:
    with pytest.raises(WebhookRejected, match=why):
        check_url(url, resolver)


def test_good_urls_validate() -> None:
    assert validate_url("https://hooks.example.com/in?x=1", resolver)
    assert validate_url("https://v6.example.com:8443/in", resolver)


class Recorder:
    def __init__(self, replies: list[httpx.Response]) -> None:
        self.replies = replies
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.replies.pop(0)


def send(url: str, recorder: Recorder) -> Delivery:
    return deliver(
        url,
        b'{"matches": []}',
        resolver=resolver,
        transport=httpx.MockTransport(recorder),
    )


def test_delivery_pins_the_resolved_address_and_keeps_the_host_name() -> None:
    recorder = Recorder([httpx.Response(204)])
    result = send("https://hooks.example.com/in", recorder)
    assert result == Delivery(True, 204)
    request = recorder.requests[0]
    assert request.method == "POST"
    assert request.url.host == PUBLIC  # the connection goes to the checked address
    assert request.headers["host"] == "hooks.example.com"
    assert request.extensions["sni_hostname"] == "hooks.example.com"
    assert json.loads(request.content) == {"matches": []}
    assert request.headers["content-type"] == "application/json"


def test_failures_are_reported_never_raised() -> None:
    assert send("https://hooks.example.com/in", Recorder([httpx.Response(500)])) == Delivery(
        False, 500
    )
    assert not send("https://internal.example.com/in", Recorder([])).ok

    def refuse(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    result = deliver(
        "https://hooks.example.com/in",
        b"{}",
        resolver=resolver,
        transport=httpx.MockTransport(refuse),
    )
    assert result == Delivery(False, error="could not connect")


def test_a_redirect_to_a_private_host_is_never_followed() -> None:
    recorder = Recorder(
        [
            httpx.Response(302, headers={"location": "https://internal.example.com/admin"}),
            httpx.Response(200),
        ]
    )
    result = send("https://hooks.example.com/in", recorder)
    assert not result.ok and "non-public" in (result.error or "")
    assert len(recorder.requests) == 1  # the private hop was never requested


@pytest.mark.parametrize(
    "destination",
    ["http://hooks.example.com/x", "https://127.0.0.1/x", "https://metadata.example.com/x"],
)
def test_every_redirect_hop_is_rechecked(destination: str) -> None:
    recorder = Recorder([httpx.Response(301, headers={"location": destination})])
    assert not send("https://hooks.example.com/in", recorder).ok
    assert len(recorder.requests) == 1


def test_a_safe_redirect_is_followed_and_post_becomes_get_after_302() -> None:
    recorder = Recorder(
        [
            httpx.Response(302, headers={"location": "https://other.example.org/new"}),
            httpx.Response(200),
        ]
    )
    assert send("https://hooks.example.com/in", recorder) == Delivery(True, 200)
    second = recorder.requests[1]
    assert second.url.host == "1.1.1.1" and second.headers["host"] == "other.example.org"
    assert second.method == "GET" and second.content == b""


def test_307_keeps_the_post() -> None:
    recorder = Recorder([httpx.Response(307, headers={"location": "/again"}), httpx.Response(200)])
    assert send("https://hooks.example.com/in", recorder).ok
    assert recorder.requests[1].method == "POST"
    assert recorder.requests[1].url.path == "/again"


def test_redirect_loops_stop() -> None:
    replies = [httpx.Response(302, headers={"location": "/loop"}) for _ in range(10)]
    result = send("https://hooks.example.com/in", Recorder(replies))
    assert result == Delivery(False, error="too many redirects")


def test_oversized_payloads_are_not_sent() -> None:
    recorder = Recorder([])
    result = deliver(
        "https://hooks.example.com/in",
        b"x" * (64 * 1024 + 1),
        resolver=resolver,
        transport=httpx.MockTransport(recorder),
    )
    assert not result.ok and recorder.requests == []
