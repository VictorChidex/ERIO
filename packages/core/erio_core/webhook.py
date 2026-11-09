"""Saved-search webhooks that cannot be aimed at ERIO's own network (SSRF-safe).

A webhook URL is typed by a stranger, so the server treats it as hostile:

- https only, on port 443 or 8443, no credentials in the URL, no IP literals, no names that
  are local by convention;
- the name is resolved here, every address must be public (not private, loopback, link-local,
  shared, reserved or an IPv6 form that embeds an IPv4 address), and the connection goes to
  that address, so a second DNS answer cannot change where the request lands;
- a redirect is followed at most 3 times and every hop passes the same checks;
- a short timeout, and the response body is never read: only the status is kept.

``validate_url`` runs when a person saves the URL; ``deliver`` runs each time, because DNS can
change between the two.
"""

import ipaddress
import socket
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx

Resolver = Callable[[str], list[str]]

ALLOWED_PORTS = (443, 8443)
MAX_URL_LENGTH = 2000
MAX_REDIRECTS = 3
MAX_ADDRESS_TRIES = 3
REDIRECTS = (301, 302, 303, 307, 308)
KEEP_METHOD = (307, 308)  # the others turn a POST into a GET, as browsers do
TIMEOUT = httpx.Timeout(5.0, connect=3.0)
MAX_PAYLOAD_BYTES = 64 * 1024
USER_AGENT = "ERIO-Webhook/1.0 (+saved-search alert; you asked for this)"
LOCAL_SUFFIXES = (".local", ".localhost", ".internal", ".lan", ".home", ".corp", ".intranet")
# Address ranges that can carry or tunnel to an IPv4 address ERIO should not reach.
_EMBEDDING_RANGES = tuple(
    ipaddress.ip_network(cidr)
    for cidr in ("64:ff9b::/96", "64:ff9b:1::/48", "2002::/16", "2001::/32")
)


class WebhookRejected(ValueError):
    """The URL is not one ERIO will send to."""


def resolve(host: str) -> list[str]:
    return [str(info[4][0]) for info in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)]


def is_public(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return is_public(str(ip.ipv4_mapped))
        if any(ip in network for network in _EMBEDDING_RANGES):
            return False
    return ip.is_global and not ip.is_multicast


def _host_is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def check_url(url: str, resolver: Resolver = resolve) -> tuple[httpx.URL, list[str]]:
    """The parsed URL and the public addresses its host resolves to, or ``WebhookRejected``."""
    if len(url) > MAX_URL_LENGTH or not url.isprintable() or " " in url:
        raise WebhookRejected("not a usable address")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as error:
        raise WebhookRejected("not a valid address") from error
    if parts.scheme != "https":
        raise WebhookRejected("only https addresses are allowed")
    if "@" in parts.netloc:
        raise WebhookRejected("addresses with a login in them are not allowed")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host or "." not in host or _host_is_ip_literal(host):
        raise WebhookRejected("use a public host name, not an IP address")
    if host == "localhost" or host.endswith(LOCAL_SUFFIXES):
        raise WebhookRejected("local host names are not allowed")
    if port is not None and port not in ALLOWED_PORTS:
        raise WebhookRejected("only ports 443 and 8443 are allowed")
    try:
        addresses = resolver(host)
    except OSError as error:
        raise WebhookRejected("the host name does not resolve") from error
    if not addresses:
        raise WebhookRejected("the host name does not resolve")
    if not all(is_public(address) for address in addresses):
        raise WebhookRejected("the host name points at a non-public address")
    return httpx.URL(url), list(dict.fromkeys(addresses))


def validate_url(url: str, resolver: Resolver = resolve) -> str:
    """The URL if ERIO would send to it now, otherwise ``WebhookRejected`` saying why."""
    check_url(url, resolver)
    return url


@dataclass(frozen=True)
class Delivery:
    ok: bool
    status: int | None = None
    error: str | None = None


def _pinned_request(
    client: httpx.Client, url: httpx.URL, address: str, method: str, body: bytes | None
) -> tuple[int, str | None]:
    """One request to ``address`` carrying the original host name.

    Returns the status and any redirect destination; the body is never read."""
    host = url.host
    port = url.port
    pinned = url.copy_with(host=address)
    headers = {
        "Host": host if port is None else f"{host}:{port}",
        "User-Agent": USER_AGENT,
        "X-ERIO-Event": "saved-search.matches",
    }
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = client.build_request(
        method,
        pinned,
        headers=headers,
        content=body,
        # TLS checks the certificate against the real name, not the pinned address.
        extensions={"sni_hostname": host},
    )
    response = client.send(request, stream=True)
    try:
        return response.status_code, response.headers.get("location")
    finally:
        response.close()


def deliver(
    url: str,
    body: bytes,
    *,
    resolver: Resolver = resolve,
    transport: httpx.BaseTransport | None = None,
) -> Delivery:
    """POST ``body`` (JSON) to ``url``. Never raises; failures come back as ``Delivery``."""
    if len(body) > MAX_PAYLOAD_BYTES:
        return Delivery(False, error="payload too large")
    method: str = "POST"
    payload: bytes | None = body
    current = url
    try:
        with httpx.Client(timeout=TIMEOUT, follow_redirects=False, transport=transport) as client:
            for _ in range(MAX_REDIRECTS + 1):
                target, addresses = check_url(current, resolver)
                answer: tuple[int, str | None] | None = None
                for address in addresses[:MAX_ADDRESS_TRIES]:
                    try:
                        answer = _pinned_request(client, target, address, method, payload)
                        break
                    except httpx.TransportError:
                        continue
                if answer is None:
                    return Delivery(False, error="could not connect")
                status, location = answer
                if status in REDIRECTS:
                    if not location:
                        return Delivery(False, status, "redirect without a destination")
                    current = urljoin(str(target), location)
                    if status not in KEEP_METHOD:
                        method, payload = "GET", None
                    continue
                return Delivery(200 <= status < 300, status)
    except WebhookRejected as error:
        return Delivery(False, error=str(error))
    except httpx.HTTPError as error:
        return Delivery(False, error=type(error).__name__)
    return Delivery(False, error="too many redirects")
