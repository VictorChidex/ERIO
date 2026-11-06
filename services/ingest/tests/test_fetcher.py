from collections.abc import Callable

import httpx
import pytest

from erio_core.connectors import FetchError
from erio_core.settings import Settings
from erio_ingest.fetcher import PoliteFetcher, is_public

HOST = "boards-api.greenhouse.io"
URL = f"https://{HOST}/v1/boards/acme/jobs"


class NoLimit:
    rate = 2.0

    def __init__(self) -> None:
        self.hosts: list[str] = []
        self.rates: list[float | None] = []

    def acquire(self, host: str, timeout_s: float = 60.0, rate: float | None = None) -> None:
        self.hosts.append(host)
        self.rates.append(rate)


def make_fetcher(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    addresses: list[str] | None = None,
    settings: Settings | None = None,
    hosts: frozenset[str] = frozenset({HOST}),
) -> tuple[PoliteFetcher, NoLimit, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    limiter = NoLimit()
    fetcher = PoliteFetcher(
        allowed_hosts=hosts,
        limiter=limiter,  # type: ignore[arg-type]
        settings=settings or Settings(),
        client=httpx.Client(transport=httpx.MockTransport(record)),
        resolver=lambda host: addresses if addresses is not None else ["104.18.0.1"],
    )
    return fetcher, limiter, seen


def site(robots: tuple[int, str] = (404, ""), page: tuple[int, bytes] = (200, b"{}")):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(robots[0], text=robots[1])
        return httpx.Response(page[0], content=page[1], headers={"ETag": 'W/"v1"'})

    return handler


def test_sends_the_crawler_user_agent_and_respects_the_rate_limit() -> None:
    fetcher, limiter, seen = make_fetcher(site())

    response = fetcher.get(URL)

    assert response.status == 200
    assert {r.headers["User-Agent"] for r in seen} == {Settings().crawler_user_agent}
    assert limiter.hosts == [HOST, HOST]  # robots.txt, then the page


def test_robots_txt_is_fetched_once_per_host() -> None:
    fetcher, _, seen = make_fetcher(site())
    fetcher.get(URL)
    fetcher.get(URL)
    assert [r.url.path for r in seen].count("/robots.txt") == 1


def test_sends_the_previous_etag() -> None:
    fetcher, _, seen = make_fetcher(site())
    fetcher.get(URL, etag='W/"v1"')
    assert seen[-1].headers["If-None-Match"] == 'W/"v1"'


@pytest.mark.parametrize(
    "url",
    ["https://evil.example/jobs", "http://boards-api.greenhouse.io/v1/boards/acme/jobs"],
)
def test_refuses_other_hosts_and_plain_http(url: str) -> None:
    fetcher, _, seen = make_fetcher(site())
    with pytest.raises(FetchError, match="not allowed"):
        fetcher.get(url)
    assert seen == []


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.5", "169.254.169.254", "::1"])
def test_refuses_hosts_that_resolve_to_private_addresses(address: str) -> None:
    fetcher, _, seen = make_fetcher(site(), addresses=[address])
    with pytest.raises(FetchError, match="public address"):
        fetcher.get(URL)
    assert seen == []


def test_a_wildcard_admits_one_subdomain_level_under_one_rate_limit() -> None:
    fetcher, limiter, _ = make_fetcher(site(), hosts=frozenset({"*.recruitee.com"}))

    fetcher.get("https://acme.recruitee.com/api/offers/")
    fetcher.get("https://globex.recruitee.com/api/offers/")

    assert set(limiter.hosts) == {"*.recruitee.com"}
    for url in (
        "https://recruitee.com/api/offers/",
        "https://a.b.recruitee.com/api/offers/",
        "https://acme.recruitee.com.evil.example/",
    ):
        with pytest.raises(FetchError, match="not allowed"):
            fetcher.get(url)


def test_a_robots_crawl_delay_slows_the_host() -> None:
    robots = (200, "User-agent: *\nAllow: /\nCrawl-delay: 4\n")
    fetcher, limiter, _ = make_fetcher(site(robots=robots))

    fetcher.get(URL)

    assert limiter.rates == [None, 0.25]  # robots.txt itself, then the page at 1 per 4 s


def test_a_crawl_delay_never_speeds_a_host_up() -> None:
    robots = (200, "User-agent: *\nCrawl-delay: 1\n")
    fetcher, limiter, _ = make_fetcher(site(robots=robots))
    limiter.rate = 0.5  # ERIO's own limit is already slower than 1 per second

    fetcher.get(URL)

    assert limiter.rates[-1] == 0.5


@pytest.mark.parametrize(
    ("failure", "outcome"),
    [(httpx.ReadTimeout("slow"), "timeout"), (httpx.ConnectError("refused"), "http_error")],
)
def test_network_failures_are_fetch_errors(failure: httpx.HTTPError, outcome: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        raise failure

    fetcher, _, _ = make_fetcher(handler)
    with pytest.raises(FetchError) as error:
        fetcher.get(URL)
    assert error.value.outcome == outcome


def test_obeys_robots_txt() -> None:
    robots = (200, "User-agent: *\nDisallow: /v1/\n")
    fetcher, _, seen = make_fetcher(site(robots=robots))
    with pytest.raises(FetchError, match=r"robots\.txt disallows"):
        fetcher.get(URL)
    assert [r.url.path for r in seen] == ["/robots.txt"]


def test_skips_the_round_when_robots_txt_is_unreachable() -> None:
    fetcher, _, _ = make_fetcher(site(robots=(503, "")))
    with pytest.raises(FetchError, match=r"robots\.txt answered 503"):
        fetcher.get(URL)


def test_cuts_off_oversized_responses() -> None:
    settings = Settings(crawl_max_response_bytes=1000)
    fetcher, _, _ = make_fetcher(site(page=(200, b"x" * 5000)), settings=settings)
    with pytest.raises(FetchError, match="over 1000 bytes"):
        fetcher.get(URL)


def test_public_address_check() -> None:
    assert is_public("104.18.0.1")
    assert not is_public("192.168.1.10")
    assert not is_public("fd00::1")


def test_post_json_follows_the_same_rules() -> None:
    fetcher, limiter, seen = make_fetcher(site(page=(200, b'{"jobPostings": []}')))

    response = fetcher.post_json(URL, {"limit": 20, "offset": 0})

    request = seen[-1]
    assert (response.status, request.method) == (200, "POST")
    assert request.headers["Content-Type"] == "application/json"
    assert request.content == b'{"limit": 20, "offset": 0}'
    assert limiter.hosts == [HOST, HOST]
    blocked, _, _ = make_fetcher(site(robots=(200, "User-agent: *\nDisallow: /v1/")))
    with pytest.raises(FetchError, match=r"robots.txt disallows"):
        blocked.post_json(URL, {})


def test_hosts_of_registered_boards_are_allowed() -> None:
    reads: list[int] = []

    def registered() -> list[str]:
        reads.append(1)
        return ["Jobs.Example.org"]

    fetcher, _, _ = make_fetcher(site())
    fetcher.extra_hosts = registered
    assert fetcher.get("https://jobs.example.org/jobs.rss").status == 200
    fetcher.get("https://jobs.example.org/jobs.rss")
    assert len(reads) == 1  # read again only every few minutes
    with pytest.raises(FetchError, match="host not allowed"):
        fetcher.get("https://elsewhere.example.org/jobs.rss")
    # A registered host still has to resolve to a public address.
    private, _, _ = make_fetcher(site(), addresses=["10.0.0.5"])
    private.extra_hosts = registered
    with pytest.raises(FetchError, match="public address"):
        private.get("https://jobs.example.org/jobs.rss")


def redirecting(chain: dict[str, str]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        target = chain.get(str(request.url))
        if target:
            return httpx.Response(302, headers={"Location": target})
        return httpx.Response(200, content=b"done")

    return handler


def test_redirects_are_followed_within_the_allow_list() -> None:
    fetcher, _, seen = make_fetcher(
        redirecting({URL: f"https://{HOST}/v1/boards/acme/jobs/apps/new"})
    )
    response = fetcher.get(URL)
    assert (response.status, response.body) == (200, b"done")
    assert str(seen[-1].url).endswith("/apps/new")
    # A relative Location is resolved against the URL that redirected.
    relative, _, _ = make_fetcher(redirecting({URL: "/v1/other"}))
    assert relative.get(URL).body == b"done"


def test_a_redirect_to_a_host_that_is_not_allowed_is_refused() -> None:
    fetcher, _, seen = make_fetcher(redirecting({URL: "https://evil.example.org/x"}))
    with pytest.raises(FetchError, match="host not allowed"):
        fetcher.get(URL)
    assert all(r.url.host == HOST for r in seen)


def test_a_redirect_to_plain_http_is_refused() -> None:
    fetcher, _, _ = make_fetcher(redirecting({URL: f"http://{HOST}/v1"}))
    with pytest.raises(FetchError, match="host not allowed"):
        fetcher.get(URL)


def test_redirect_loops_stop_after_a_few_hops() -> None:
    a, b = f"https://{HOST}/a", f"https://{HOST}/b"
    fetcher, _, seen = make_fetcher(redirecting({a: b, b: a}))
    response = fetcher.get(a)
    assert response.status == 302  # the last hop is returned, not followed forever
    assert len([r for r in seen if r.url.path != "/robots.txt"]) == 4
