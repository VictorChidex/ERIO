"""On-demand refresh: a search asks ERIO to re-read the employer boards behind its results.

The index is filled by a steady crawl; a refresh makes a user's own search the
trigger for the boards that matter to it, so a job posted a minute ago shows
up within seconds. It is bounded so the crawler stays a polite guest:

- boards are read on their own fast queue, never ahead of a source's rate limit;
- one board is refreshed at most once per ``BOARD_COOLDOWN_S``, whoever asks;
- one query shares one refresh for ``QUERY_COOLDOWN_S`` (the same search typed by
  many people costs one refresh);
- no more than ``MAX_BOARDS`` boards per refresh and ``MAX_QUEUE`` waiting.

Progress lives in Redis for ``STATE_TTL_S``: the API creates it, the live worker
counts boards as they finish, and the website polls it.
"""

import hashlib
import json
import uuid
from typing import Any

QUEUE = "live"
TASK = "erio.crawl_board_live"
MAX_BOARDS = 20
MAX_QUEUE = 200
BOARD_COOLDOWN_S = 120
QUERY_COOLDOWN_S = 30
STATE_TTL_S = 600


Redis = Any  # a redis.Redis client; core does not depend on the package itself


def state_key(refresh_id: str) -> str:
    return f"erio:live:state:{refresh_id}"


def query_key(query: dict[str, Any]) -> str:
    """The same search (text and filters) always maps to the same key."""
    digest = hashlib.sha256(json.dumps(query, sort_keys=True).encode()).hexdigest()[:24]
    return f"erio:live:query:{digest}"


def claim_board(redis: Redis, board_id: int) -> bool:
    """True for the first caller in each cooldown window; that caller refreshes the board."""
    return bool(redis.set(f"erio:live:board:{board_id}", 1, ex=BOARD_COOLDOWN_S, nx=True))


def start(redis: Redis, boards: int) -> str:
    refresh_id = uuid.uuid4().hex
    redis.hset(state_key(refresh_id), mapping={"boards": boards, "done": 0, "new": 0, "changed": 0})
    redis.expire(state_key(refresh_id), STATE_TTL_S)
    return refresh_id


def running_for(redis: Redis, query: dict[str, Any]) -> str | None:
    """The refresh id already started for this exact search, if its window is still open."""
    held = redis.get(query_key(query))
    if held is None:
        return None
    return held.decode() if isinstance(held, bytes) else str(held)


def remember(redis: Redis, query: dict[str, Any], refresh_id: str) -> None:
    redis.set(query_key(query), refresh_id, ex=QUERY_COOLDOWN_S)


def board_done(redis: Redis, refresh_id: str, new: int, changed: int) -> None:
    redis.hincrby(state_key(refresh_id), "done", 1)
    redis.hincrby(state_key(refresh_id), "new", new)
    redis.hincrby(state_key(refresh_id), "changed", changed)


def read(redis: Redis, refresh_id: str) -> dict[str, Any] | None:
    raw = redis.hgetall(state_key(refresh_id))
    if not raw:
        return None
    fields = {(k.decode() if isinstance(k, bytes) else k): int(v) for k, v in raw.items()}
    return {**fields, "finished": fields["done"] >= fields["boards"]}


def queue_is_full(redis: Redis) -> bool:
    return int(redis.llen(QUEUE) or 0) >= MAX_QUEUE
