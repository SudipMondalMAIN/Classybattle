"""
Lightweight async cache layer on top of Redis, used to shave repeated
read-heavy DB hits off hot paths: tournament listing/detail, payment
settings (min/max deposit & withdrawal), and user profile lookups.

Design goals
------------
- Uses the SAME `REDIS_URL` already configured for rate limiting (see
  app/middleware/rate_limiter.py), so no new infra is required. If
  REDIS_URL is unset, every call becomes a safe no-op (get -> miss,
  set/delete -> ignored) so local/dev without Redis keeps working
  exactly as before -- caching is purely an optimization, never a
  correctness dependency.
- Fails open: any Redis error (connection drop, timeout) is caught and
  logged, and treated as a cache miss / no-op. A Redis outage must
  degrade to "hits the DB every time", never break the API.
- JSON-only values. Callers are responsible for passing
  JSON-serializable dicts/lists (typically a `.model_dump(mode="json")`
  of a Pydantic schema, NOT raw SQLAlchemy ORM instances -- ORM objects
  are never cached directly to avoid detached-instance / lazy-load
  issues on a cache hit).

Usage
-----
    from app.core.cache import cache_get, cache_set, cache_delete_prefix

    cached = await cache_get("tournament:detail:<id>")
    if cached is not None:
        return TournamentRead.model_validate(cached)

    tournament = await service.get_by_id(tournament_id)
    data = TournamentRead.model_validate(tournament).model_dump(mode="json")
    await cache_set("tournament:detail:<id>", data, ttl=60)

Invalidation is prefix-based (`cache_delete_prefix("tournament:")`) so a
single mutation doesn't need to know every cached variant (list pages,
filters, slug/id/short_id lookups) -- it just wipes the whole namespace.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config.settings import settings
from app.core.logging import get_logger

logger = get_logger("cache")

_redis: Optional[Redis] = None
_redis_init_attempted = False


def _get_redis() -> Optional[Redis]:
    """Lazily creates a single shared async Redis client. Returns None
    (disabling caching) if REDIS_URL isn't configured."""
    global _redis, _redis_init_attempted
    if _redis_init_attempted:
        return _redis
    _redis_init_attempted = True

    if not settings.REDIS_URL:
        logger.info("cache_disabled", reason="REDIS_URL not configured")
        return None

    try:
        _redis = Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("cache_init_failed", error=str(exc))
        _redis = None

    return _redis


async def cache_get(key: str) -> Optional[Any]:
    """Returns the deserialized cached value, or None on a miss/error."""
    client = _get_redis()
    if client is None:
        return None
    try:
        raw = await client.get(key)
    except RedisError as exc:
        logger.warning("cache_get_failed", key=key, error=str(exc))
        return None
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


async def cache_set(key: str, value: Any, ttl: int) -> None:
    """Stores `value` (JSON-serializable) under `key` with a TTL in
    seconds. Best-effort -- failures are logged, never raised."""
    client = _get_redis()
    if client is None:
        return
    try:
        await client.set(key, json.dumps(value, default=str), ex=ttl)
    except RedisError as exc:
        logger.warning("cache_set_failed", key=key, error=str(exc))


async def cache_delete(key: str) -> None:
    client = _get_redis()
    if client is None:
        return
    try:
        await client.delete(key)
    except RedisError as exc:
        logger.warning("cache_delete_failed", key=key, error=str(exc))


async def cache_delete_prefix(prefix: str) -> None:
    """Deletes every key starting with `prefix` -- used to invalidate an
    entire namespace (e.g. all cached tournament list pages/filters) on
    any mutation, without tracking each individual cached variant."""
    client = _get_redis()
    if client is None:
        return
    try:
        cursor = 0
        while True:
            cursor, keys = await client.scan(cursor=cursor, match=f"{prefix}*", count=200)
            if keys:
                await client.delete(*keys)
            if cursor == 0:
                break
    except RedisError as exc:
        logger.warning("cache_delete_prefix_failed", prefix=prefix, error=str(exc))
