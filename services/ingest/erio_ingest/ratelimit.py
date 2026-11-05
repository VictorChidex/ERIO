"""Per-host token bucket shared by every worker through Redis (spec section 5)."""

import time

from redis import Redis

# Refill by elapsed time, then take one token if there is one. Uses Redis's
# own clock so workers with drifting clocks still share one limit.
_REFILL_AND_TAKE = """
local rate = tonumber(ARGV[1])
local burst = tonumber(ARGV[2])
local t = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1000000
local state = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens = tonumber(state[1]) or burst
local ts = tonumber(state[2]) or now
tokens = math.min(burst, tokens + math.max(0, now - ts) * rate)
local wait = 0
if tokens >= 1 then
  tokens = tokens - 1
else
  wait = (1 - tokens) / rate
end
redis.call('HSET', KEYS[1], 'tokens', tokens, 'ts', now)
redis.call('EXPIRE', KEYS[1], 120)
return tostring(wait)
"""


class RateLimitTimeout(Exception):
    pass


class HostRateLimiter:
    def __init__(self, redis: Redis, rate_per_second: float, burst: float = 1.0):
        self.redis = redis
        self.rate = rate_per_second
        self.burst = burst
        self._take = redis.register_script(_REFILL_AND_TAKE)

    def try_acquire(self, host: str) -> float:
        """Take a token for ``host``; return 0 on success or seconds to wait."""
        wait = self._take(keys=[f"erio:ratelimit:{host}"], args=[self.rate, self.burst])
        return float(wait.decode() if isinstance(wait, bytes) else wait)

    def acquire(self, host: str, timeout_s: float = 60.0) -> None:
        """Block until a request to ``host`` is allowed."""
        deadline = time.monotonic() + timeout_s
        while (wait := self.try_acquire(host)) > 0:
            if time.monotonic() + wait > deadline:
                raise RateLimitTimeout(f"no request slot for {host} within {timeout_s}s")
            time.sleep(wait)
