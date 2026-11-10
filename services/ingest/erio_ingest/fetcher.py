"""The only way crawl code reaches the internet (spec sections 5 and 9).

Every request:
- goes only to a host a connector declared or a board registered in the
  database (a board whose token is a full URL: a feed, a career site on the
  employer's own domain, a job board on its own domain), and never to a
  private address;
- obeys robots.txt and sends ERIO's user agent;
- waits for the host's shared rate limit;
- is cut off at a size cap and a timeout.
"""

import ipaddress
import json
import re
import socket
import time
import urllib.robotparser
from collections.abc import Callable, Iterable
from typing import Any
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

import httpx

from erio_core.connectors import FetchError, FetchResponse
from erio_core.settings import Settings
from erio_ingest.ratelimit import HostRateLimiter

Resolver = Callable[[str], Iterable[str]]

ROBOTS_TTL_S = 3600.0
# How often the hosts of registered boards are read again.
EXTRA_HOSTS_TTL_S = 300.0
# A 429 is retried this many times, waiting Retry-After (or 4 s, then 8 s) up to 20 s.
MAX_RETRIES = 2
BACKOFF_BASE_S = 4.0
MAX_BACKOFF_S = 20.0
MAX_REDIRECTS = 3
REDIRECTS = frozenset({301, 302, 303, 307, 308})


class Robots(urllib.robotparser.RobotFileParser):
    """robots.txt rules as RFC 9309 reads them: ``*`` and a closing ``$`` in a path
    pattern work, the longest matching rule wins, and an Allow beats a Disallow of the
    same length. The standard library takes the first literal prefix match, which
    refuses paths a site explicitly allows (``Disallow: /`` then ``Allow: /api``)."""

    disallow_all: bool
    allow_all: bool
    entries: list[Any]
    default_entry: Any

    @staticmethod
    def _pattern(rule_path: str) -> re.Pattern[str]:
        # The stdlib percent-encodes the rule's path, wildcard characters included.
        text = rule_path.replace("%2A", "*").replace("%24", "$")
        anchored = text.endswith("$")
        body = ".*".join(re.escape(part) for part in text.removesuffix("$").split("*"))
        return re.compile(body + ("$" if anchored else ""))

    def can_fetch(self, useragent: str, url: str) -> bool:
        if self.disallow_all:
            return False
        if self.allow_all:
            return True
        parts = urlsplit(url)
        path = quote(urlunsplit(("", "", parts.path, parts.query, ""))) or "/"
        entry = next((e for e in self.entries if e.applies_to(useragent)), self.default_entry)
        rules = [r for r in entry.rulelines if self._pattern(r.path).match(path)] if entry else []
        if not rules:
            return True
        best = max(rules, key=lambda r: (len(r.path.replace("%2A", "*")), r.allowance))
        return bool(best.allowance)


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
        extra_hosts: Callable[[], Iterable[str]] | None = None,
    ):
        self.allowed_hosts = frozenset(allowed_hosts)
        self.extra_hosts = extra_hosts
        self._extra: tuple[float, frozenset[str]] = (float("-inf"), frozenset())
        self.limiter = limiter
        self.settings = settings
        self.resolver = resolver
        self.client = client or httpx.Client(
            timeout=settings.crawl_timeout_s, follow_redirects=False
        )
        self._robots: dict[str, tuple[float, urllib.robotparser.RobotFileParser]] = {}
        self._sleep: Callable[[float], None] = time.sleep

    def get(self, url: str, etag: str | None = None) -> FetchResponse:
        return self._get(url, {"If-None-Match": etag} if etag else {})

    def get_with(self, url: str, headers: dict[str, str]) -> FetchResponse:
        """GET with extra request headers, under exactly the same rules as ``get``."""
        return self._get(url, dict(headers))

    def _get(self, url: str, headers: dict[str, str]) -> FetchResponse:
        """GET, following up to ``MAX_REDIRECTS`` redirects. Every hop is checked like
        the first request: https only, an allowed host that resolves to a public
        address, and robots.txt, so a redirect can never lead anywhere the
        crawler was not already allowed to go."""
        for hop in range(MAX_REDIRECTS + 1):
            host = self._check_host(url)
            robots = self._robots_for(host)
            if not robots.can_fetch(self.settings.crawler_user_agent, url):
                raise FetchError("http_error", f"robots.txt disallows {url}")
            delay = robots.crawl_delay(self.settings.crawler_user_agent)
            response = self._request(host, url, headers, float(delay) if delay else None)
            location = {k.lower(): v for k, v in response.headers.items()}.get("location")
            if response.status in REDIRECTS and location and hop < MAX_REDIRECTS:
                url = urljoin(url, location)
                continue
            return response
        raise AssertionError("unreachable")

    def post_json(self, url: str, payload: Any) -> FetchResponse:
        """POST a JSON body, under exactly the same rules as ``get``."""
        return self.post_json_with(url, payload, {})

    def post_json_with(self, url: str, payload: Any, headers: dict[str, str]) -> FetchResponse:
        """POST a JSON body with extra request headers, under the same rules as ``get``."""
        host = self._check_host(url)
        robots = self._robots_for(host)
        if not robots.can_fetch(self.settings.crawler_user_agent, url):
            raise FetchError("http_error", f"robots.txt disallows {url}")
        delay = robots.crawl_delay(self.settings.crawler_user_agent)
        merged = {"Content-Type": "application/json", "Accept": "application/json", **headers}
        content = json.dumps(payload).encode()
        return self._request(host, url, merged, float(delay) if delay else None, "POST", content)

    def _request(
        self,
        host: str,
        url: str,
        headers: dict[str, str],
        crawl_delay_s: float | None = None,
        method: str = "GET",
        content: bytes | None = None,
    ) -> FetchResponse:
        """One request; network failures come back as FetchError, like any other.

        A site that answers 429 is asked for time, not hammered: the request waits (as the
        site's Retry-After says, within ``MAX_BACKOFF_S``) and tries again, at most
        ``MAX_RETRIES`` times; a host still refusing then reports its 429.
        """
        try:
            for attempt in range(MAX_RETRIES + 1):
                response = self._send(host, url, headers, crawl_delay_s, method, content)
                if response.status != 429 or attempt == MAX_RETRIES:
                    return response
                self._sleep(self._backoff(response, attempt))
            raise AssertionError("unreachable")
        except httpx.TimeoutException as error:
            raise FetchError("timeout", f"{host} timed out: {error!r}") from error
        except httpx.HTTPError as error:
            raise FetchError("http_error", f"{host} failed: {error!r}") from error

    @staticmethod
    def _backoff(response: FetchResponse, attempt: int) -> float:
        header = {k.lower(): v for k, v in response.headers.items()}.get("retry-after", "")
        wait = float(header) if header.isdigit() else BACKOFF_BASE_S * 2**attempt
        return min(wait, MAX_BACKOFF_S)

    def _allowed(self, host: str) -> str | None:
        """The allow-list entry that admits ``host``: itself or a "*.domain" wildcard.

        A wildcard admits exactly one label below the domain, and every host it
        admits shares one rate limit (they are one service).
        """
        if host in self.allowed_hosts:
            return host
        wildcard = "*." + host.split(".", 1)[-1]
        if "." in host and wildcard in self.allowed_hosts:
            return wildcard
        return host if host in self._registered_hosts() else None

    def _registered_hosts(self) -> frozenset[str]:
        if self.extra_hosts is None:
            return frozenset()
        read_at, hosts = self._extra
        if time.monotonic() - read_at > EXTRA_HOSTS_TTL_S:
            hosts = frozenset(h.lower() for h in self.extra_hosts())
            self._extra = (time.monotonic(), hosts)
        return hosts

    def _check_host(self, url: str) -> str:
        parts = urlsplit(url)
        host = parts.hostname or ""
        if parts.scheme != "https" or self._allowed(host) is None:
            raise FetchError("http_error", f"host not allowed: {host or url}")
        addresses = list(self.resolver(host))
        if not addresses or not all(is_public(address) for address in addresses):
            raise FetchError("http_error", f"{host} does not resolve to a public address")
        return host

    @staticmethod
    def _rule_lines(text: str) -> list[str]:
        """robots.txt lines, with a rule's closing ``?`` ("Disallow: /*?": any URL with a
        query string) kept: the standard library parses the path as a URL and drops a bare
        ``?``, which would turn that rule into "Disallow: /*" and refuse the whole site."""
        lines = []
        for line in text.splitlines():
            field, colon, value = line.partition(":")
            if (
                colon
                and field.strip().lower() in ("allow", "disallow")
                and value.rstrip().endswith("?")
            ):
                line = line.rstrip() + "*"
            lines.append(line)
        return lines

    def _robots_for(self, host: str) -> urllib.robotparser.RobotFileParser:
        cached = self._robots.get(host)
        if cached is None or time.monotonic() - cached[0] > ROBOTS_TTL_S:
            parser = Robots()
            response = self._request(host, f"https://{host}/robots.txt", {})
            if response.status >= 500:
                # Unreachable robots.txt: be cautious and skip this round.
                raise FetchError("http_error", f"robots.txt answered {response.status}")
            # A missing robots.txt (4xx) allows everything: parse it as empty.
            ok = response.status < 400
            parser.parse(self._rule_lines(response.body.decode("utf-8", "replace")) if ok else [])
            cached = (time.monotonic(), parser)
            self._robots[host] = cached
        return cached[1]

    def _send(
        self,
        host: str,
        url: str,
        headers: dict[str, str],
        crawl_delay_s: float | None,
        method: str = "GET",
        content: bytes | None = None,
    ) -> FetchResponse:
        # A robots.txt Crawl-delay slows the host below ERIO's own limit, never above it.
        rate = min(self.limiter.rate, 1 / crawl_delay_s) if crawl_delay_s else None
        self.limiter.acquire(self._allowed(host) or host, rate=rate)
        request_headers = {"User-Agent": self.settings.crawler_user_agent, **headers}
        limit = self.settings.crawl_max_response_bytes
        with self.client.stream(method, url, headers=request_headers, content=content) as response:
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > limit:
                    raise FetchError(
                        "http_error", f"response over {limit} bytes", response.status_code
                    )
            return FetchResponse(response.status_code, bytes(body), dict(response.headers))
