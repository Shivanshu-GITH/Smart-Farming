"""Shared cache + rate limiter behaviour (in-process fallback, no Redis)."""


async def test_cache_roundtrip_and_delete():
    from app.core import cache
    await cache.set("k1", {"a": 1}, ttl_seconds=30)
    assert await cache.get("k1") == {"a": 1}
    await cache.delete("k1")
    assert await cache.get("k1") is None


async def test_rate_limiter_allows_then_blocks():
    from app.core import cache
    key = "rl:test-unit"
    results = [await cache.allow(key, limit=3, window_seconds=60) for _ in range(5)]
    assert results == [True, True, True, False, False]
