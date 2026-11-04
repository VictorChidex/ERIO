"""Reachability checks for the services the API depends on.

Each check returns True when the dependency answers within the configured
timeout. They are used by the readiness endpoint and the compose healthcheck.
"""

import asyncio
from collections.abc import Awaitable, Callable

import httpx
import psycopg
import redis.asyncio as aioredis

from erio_core.settings import Settings

Check = Callable[[], Awaitable[bool]]


async def check_postgres(settings: Settings) -> bool:
    try:
        conn = await psycopg.AsyncConnection.connect(
            settings.database_url, connect_timeout=max(1, int(settings.dependency_timeout_s))
        )
    except psycopg.Error:
        return False
    async with conn:
        await conn.execute("SELECT 1")
    return True


async def check_redis(settings: Settings) -> bool:
    client = aioredis.from_url(
        settings.redis_url, socket_connect_timeout=settings.dependency_timeout_s
    )
    try:
        return bool(await client.ping())
    except (aioredis.RedisError, OSError):
        return False
    finally:
        await client.aclose()


async def check_opensearch(settings: Settings) -> bool:
    try:
        async with httpx.AsyncClient(timeout=settings.dependency_timeout_s) as client:
            response = await client.get(f"{settings.opensearch_url}/_cluster/health")
    except httpx.HTTPError:
        return False
    return response.status_code == 200 and response.json().get("status") in {"green", "yellow"}


def default_checks(settings: Settings) -> dict[str, Check]:
    return {
        "postgres": lambda: check_postgres(settings),
        "redis": lambda: check_redis(settings),
        "opensearch": lambda: check_opensearch(settings),
    }


async def run_checks(checks: dict[str, Check]) -> dict[str, bool]:
    results = await asyncio.gather(*(check() for check in checks.values()))
    return dict(zip(checks, results, strict=True))
