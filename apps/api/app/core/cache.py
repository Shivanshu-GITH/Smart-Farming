"""Tiny TTL cache used to throttle calls to rate-limited external APIs.

In dev this is an in-process dict. In production swap the backend for Redis
(see ``REDIS_URL``); the public ``get``/``set`` interface stays the same.
"""
from __future__ import annotations

import time
from typing import Any

_store: dict[str, tuple[float, Any]] = {}


def get(key: str) -> Any | None:
    item = _store.get(key)
    if item is None:
        return None
    expires_at, value = item
    if expires_at < time.time():
        _store.pop(key, None)
        return None
    return value


def set(key: str, value: Any, ttl_seconds: int = 86_400) -> None:  # noqa: A001
    _store[key] = (time.time() + ttl_seconds, value)


def geo_key(prefix: str, lat: float, lon: float, precision: int = 3) -> str:
    """Cache key bucketed to a coarse lat/lon grid.

    ``precision=3`` (~110 m) lets nearby farmers reuse the same soil/weather
    lookup instead of each hammering the upstream API.
    """
    return f"{prefix}:{round(lat, precision)}:{round(lon, precision)}"
