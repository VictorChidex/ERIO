"""The only way crawl code reaches the internet (spec sections 5 and 9).

Every request:
- goes only to a host the connector declared, never to a private address;
- obeys robots.txt and sends ERIO's user agent;
- waits for the host's shared rate limit;
- is cut off at a size cap and a timeout.
"""

import ipaddress
import socket
import time
import urllib.robotparser
from collections.abc import Callable, Iterable
from urllib.parse import urlsplit

import httpx

from erio_core.connectors import FetchError, FetchResponse
from erio_core.settings import Settings
from erio_ingest.ratelimit import HostRateLimiter

Resolver = Callable[[str], Iterable[str]]

ROBOTS_TTL_S = 3600.0


def resolve(host: str) -> list[str]:
    return [str(info[4][0]) for info in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)]


def is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return ip.is_global and not ip.is_multicast


class PoliteFetcher:
    def __init__(
        self,
        allowed_hosts: Iterable[str],
        limiter: HostRateLimiter,
        settings: Settings,
        client: httpx.Client | None = None,
        resolver: Resolver = resolve,
    ):
        self.allowed_hosts = frozenset(allowed_hosts)
        self.limiter = limiter
        self.settings = settings
        self.resolver = resolver
        self.client = client or httpx.Client(
            timeout=settings.crawl_timeout_s, follow_redirects=False
        )
        self._robots: dict[str, tuple[float, urllib.robotparser.RobotFileParser]] = {}

    def get(self, url: str, etag: str | None = None) -> FetchResponse:
        host = self._check_host(url)
        robots = self._robots_for(host)
        if not robots.can_fetch(self.settings.crawler_user_agent, url):
            raise FetchError("http_error", f"robots.txt disallows {url}")
        delay = robots.crawl_delay(self.settings.crawler_user_agent)
        headers = {"If-None-Match": etag} if etag else {}
        return self._request(host, url, headers, float(delay) if delay else None)

    def _request(
        self, host: str, url: str, headers: dict[str, str], crawl_delay_s: float | None = None
    ) -> FetchResponse:
        """One request; network failures come back as FetchError, like any other."""
        try:
            return self._send(host, url, headers, crawl_delay_s)
        except httpx.TimeoutException as error:
            raise FetchError("timeout", f"{host} timed out: {error!r}") from error
        except httpx.HTTPError as error:
            raise FetchError("http_error", f"{host} failed: {error!r}") from error

    def _allowed(self, host: str) -> str | None:
        """The allow-list entry that admits ``host``: itself or a "*.domain" wildcard.

        A wildcard admits exactly one label below the domain, and every host it
        admits shares one rate limit (they are one service).
        """
        if host in self.allowed_hosts:
            return host
        wildcard = "*." + host.split(".", 1)[-1]
        return wildcard if "." in host and wildcard in self.allowed_hosts else None

    def _check_host(self, url: str) -> str:
        parts = urlsplit(url)
        host = parts.hostname or ""
        if parts.scheme != "https" or self._allowed(host) is None:
            raise FetchError("http_error", f"host not allowed: {host or url}")
        addresses = list(self.resolver(host))
        if not addresses or not all(is_public(address) for address in addresses):
            raise FetchError("http_error", f"{host} does not resolve to a public address")
        return host

    def _robots_for(self, host: str) -> urllib.robotparser.RobotFileParser:
        cached = self._robots.get(host)
        if cached is None or time.monotonic() - cached[0] > ROBOTS_TTL_S:
            parser = urllib.robotparser.RobotFileParser()
            response = self._request(host, f"https://{host}/robots.txt", {})
            if response.status >= 500:
                # Unreachable robots.txt: be cautious and skip this round.
                raise FetchError("http_error", f"robots.txt answered {response.status}")
            # A missing robots.txt (4xx) allows everything: parse it as empty.
            ok = response.status < 400
            parser.parse(response.body.decode("utf-8", "replace").splitlines() if ok else [])
            cached = (time.monotonic(), parser)
            self._robots[host] = cached
        return cached[1]

    def _send(
        self, host: str, url: str, headers: dict[str, str], crawl_delay_s: float | None
    ) -> FetchResponse:
        # A robots.txt Crawl-delay slows the host below ERIO's own limit, never above it.
        rate = min(self.limiter.rate, 1 / crawl_delay_s) if crawl_delay_s else None
        self.limiter.acquire(self._allowed(host) or host, rate=rate)
        request_headers = {"User-Agent": self.settings.crawler_user_agent, **headers}
        limit = self.settings.crawl_max_response_bytes
        with self.client.stream("GET", url, headers=request_headers) as response:
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > limit:
                    raise FetchError(
                        "http_error", f"response over {limit} bytes", response.status_code
                    )
            return FetchResponse(response.status_code, bytes(body), dict(response.headers))
