"""Shared TTL cache used to throttle calls to rate-limited external APIs.

Backend is chosen at runtime:
- ``REDIS_URL`` set  -> Redis (shared across processes/instances).
- otherwise          -> in-process dict (single process, dev).

The public interface (``get``/``set``/``delete``/``allow``) is async so the same
code works for both backends; if Redis is configured but a call fails, we fall
back to the in-process store rather than erroring a request.
"""
from __future__ import annotations

import json
import time
from typing import Any

from app.core.config import get_settings

# In-process fallback store: key -> (expires_at, value)
_store: dict[str, tuple[float, Any]] = {}
# In-process rate-limit windows: key -> (window_start, count)
_windows: dict[str, tuple[float, int]] = {}

_redis: Any = None
_redis_init = False


def _get_redis() -> Any:
    """Lazily build an async Redis client, or None if unavailable."""
    global _redis, _redis_init
    if _redis_init:
        return _redis
    _redis_init = True
    url = get_settings().redis_url
    if url:
        try:
            import redis.asyncio as aioredis

            _redis = aioredis.from_url(url, decode_responses=True)
        except Exception:  # noqa: BLE001 - any import/connection issue -> fallback
            _redis = None
    return _redis


async def get(key: str) -> Any | None:
    r = _get_redis()
    if r is not None:
        try:
            raw = await r.get(key)
            return json.loads(raw) if raw is not None else None
        except Exception:  # noqa: BLE001
            pass  # fall through to in-process
    item = _store.get(key)
    if item is None:
        return None
    expires_at, value = item
    if expires_at < time.time():
        _store.pop(key, None)
        return None
    return value


async def set(key: str, value: Any, ttl_seconds: int = 86_400) -> None:  # noqa: A001
    r = _get_redis()
    if r is not None:
        try:
            await r.set(key, json.dumps(value), ex=ttl_seconds)
            return
        except Exception:  # noqa: BLE001
            pass
    _store[key] = (time.time() + ttl_seconds, value)


async def delete(key: str) -> None:
    """Remove a key if present (used to make OTPs one-time)."""
    r = _get_redis()
    if r is not None:
        try:
            await r.delete(key)
            return
        except Exception:  # noqa: BLE001
            pass
    _store.pop(key, None)


async def allow(key: str, limit: int, window_seconds: int) -> bool:
    """Fixed-window rate limiter. Returns True if the call is under ``limit``
    within the current ``window_seconds`` window, and counts it.

    Used to respect SoilGrids' ~5 calls/min cap across all instances.
    """
    r = _get_redis()
    if r is not None:
        try:
            count = await r.incr(key)
            if count == 1:
                await r.expire(key, window_seconds)
            return count <= limit
        except Exception:  # noqa: BLE001
            pass
    now = time.time()
    start, count = _windows.get(key, (now, 0))
    if now - start >= window_seconds:
        start, count = now, 0
    count += 1
    _windows[key] = (start, count)
    return count <= limit


def geo_key(prefix: str, lat: float, lon: float, precision: int = 3) -> str:
    """Cache key bucketed to a coarse lat/lon grid.

    ``precision=3`` (~110 m) lets nearby farmers reuse the same soil/weather
    lookup instead of each hammering the upstream API.
    """
    return f"{prefix}:{round(lat, precision)}:{round(lon, precision)}"
