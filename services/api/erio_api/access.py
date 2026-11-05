"""API tokens and rate limits (spec section 7, decision D-15).

Tokens are 32 random bytes shown once at creation; only their SHA-256 is
stored. Each request falls in one tier:

- internal: from a network listed in ERIO_API_INTERNAL_CIDRS (the local
  compose network, so the website needs no token locally);
- pro / free: a valid Bearer token;
- anonymous: no token, limited per client address.

Limits use a sliding 60-second window in Redis. Every response carries
X-RateLimit-Limit, X-RateLimit-Remaining and X-RateLimit-Reset; going over
returns 429 with Retry-After. The client address is the connecting peer,
never a forwarded header, so it cannot be spoofed.
"""

import base64
import hashlib
import ipaddress
import os
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Request, Response
from redis import Redis
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from erio_api.deps import engine
from erio_api.errors import ApiError
from erio_core.db.models import ApiToken
from erio_core.settings import get_settings

WINDOW_S = 60
TOKEN_PREFIX = "erio_"  # noqa: S105 (a public label so leaked tokens are recognizable)
TOUCH_EVERY = timedelta(minutes=5)

# Count requests in the last WINDOW_S seconds; record this one if allowed.
# Returns {allowed, remaining, reset_in_seconds}.
_SLIDING_WINDOW = """
local key, limit, window = KEYS[1], tonumber(ARGV[1]), tonumber(ARGV[2])
local t = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1000000
redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
local used = redis.call('ZCARD', key)
local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
local reset = window
if oldest[2] then reset = math.max(0, tonumber(oldest[2]) + window - now) end
if used >= limit then
  return {0, 0, tostring(reset)}
end
redis.call('ZADD', key, now, ARGV[3])
redis.call('EXPIRE', key, window + 1)
return {1, limit - used - 1, tostring(reset)}
"""


@dataclass(frozen=True)
class Caller:
    tier: str
    key: str
    token_id: int | None = None


def new_token() -> tuple[str, str]:
    """A fresh token and the hash to store. The token is never stored."""
    # 32 bytes from the operating system's cryptographic random source.
    token = TOKEN_PREFIX + base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
    return token, hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@lru_cache
def _internal_networks() -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    return tuple(ipaddress.ip_network(cidr) for cidr in get_settings().api_internal_cidrs)


def _is_internal(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(ip in network for network in _internal_networks())


@lru_cache
def redis_client() -> Redis:
    return Redis.from_url(get_settings().redis_url, socket_timeout=2)


def limits() -> dict[str, int]:
    s = get_settings()
    return {
        "internal": s.api_rate_internal,
        "pro": s.api_rate_pro,
        "free": s.api_rate_free,
        "anonymous": s.api_rate_anonymous,
    }


def identify(request: Request, db: Engine) -> Caller:
    address = request.client.host if request.client else "unknown"
    header = request.headers.get("authorization", "")
    if header:
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise ApiError(401, "invalid_token", "use 'Authorization: Bearer <token>'")
        with Session(db) as session:
            row = session.scalars(
                select(ApiToken).where(ApiToken.token_hash == hash_token(token.strip()))
            ).one_or_none()
            if row is None or row.revoked_at is not None:
                raise ApiError(401, "invalid_token", "token is not valid or has been revoked")
            now = datetime.now(UTC)
            if row.last_used_at is None or now - row.last_used_at > TOUCH_EVERY:
                row.last_used_at = now
                session.commit()
            return Caller(row.tier, f"token:{row.id}", row.id)
    if _is_internal(address):
        return Caller("internal", f"internal:{address}")
    return Caller("anonymous", f"ip:{address}")


def rate_limit(
    request: Request,
    response: Response,
    db: Annotated[Engine, Depends(engine)],
    redis: Annotated[Redis, Depends(redis_client)],
    tier_limits: Annotated[dict[str, int], Depends(limits)],
) -> Caller:
    """Dependency for every /v1 data route: identify the caller and count the request."""
    caller = identify(request, db)
    limit = tier_limits[caller.tier]
    script = redis.register_script(_SLIDING_WINDOW)
    allowed, remaining, reset = script(
        keys=[f"erio:rate:{caller.key}"],
        args=[limit, WINDOW_S, f"{time.time()}:{uuid.uuid4().hex}"],
    )
    reset_at = int(time.time() + float(reset)) + 1
    headers = {
        "X-RateLimit-Limit": str(limit),
        "X-RateLimit-Remaining": str(int(remaining)),
        "X-RateLimit-Reset": str(reset_at),
    }
    if not int(allowed):
        retry = max(1, int(float(reset)) + 1)
        raise ApiError(
            429,
            "rate_limited",
            f"limit of {limit} requests per minute reached for the {caller.tier} tier",
            headers | {"Retry-After": str(retry)},
        )
    response.headers.update(headers)
    return caller
