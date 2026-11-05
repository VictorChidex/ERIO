import time

import pytest
from redis import Redis

from erio_ingest.ratelimit import HostRateLimiter, RateLimitTimeout


@pytest.fixture
def limiter(redis_url: str) -> HostRateLimiter:
    return HostRateLimiter(Redis.from_url(redis_url), rate_per_second=2.0)


def test_first_request_goes_straight_through(limiter: HostRateLimiter) -> None:
    assert limiter.try_acquire("a.example") == 0


def test_second_immediate_request_must_wait(limiter: HostRateLimiter) -> None:
    limiter.try_acquire("a.example")
    wait = limiter.try_acquire("a.example")
    assert 0.3 < wait <= 0.5


def test_hosts_have_separate_limits(limiter: HostRateLimiter) -> None:
    limiter.try_acquire("a.example")
    assert limiter.try_acquire("b.example") == 0


def test_acquire_paces_requests_to_the_rate(limiter: HostRateLimiter) -> None:
    start = time.monotonic()
    for _ in range(3):
        limiter.acquire("a.example")
    # Three requests at 2 per second: two waits of about half a second.
    assert 0.8 < time.monotonic() - start < 1.6


def test_acquire_gives_up_after_its_timeout(redis_url: str) -> None:
    slow = HostRateLimiter(Redis.from_url(redis_url), rate_per_second=0.1)
    slow.acquire("a.example")
    with pytest.raises(RateLimitTimeout):
        slow.acquire("a.example", timeout_s=0.5)
