"""Request rate limiting built on the shared TTL cache (in-process or Redis).

Two flavours:
- ``limiter(scope, limit, window)`` — a FastAPI dependency keyed on client IP.
- ``enforce(scope, identity, limit, window)`` — awaited inside a handler for
  identity-keyed limits (per email / per phone), which is what stops targeted
  brute force even when the attacker rotates IPs.

Both answer HTTP 429 with a Retry-After header. With Redis configured the
window is shared across workers; without it, per-process — still enough to
blunt scripted abuse in the single-process dev/small deployments this app
defaults to.
"""
from __future__ import annotations

from fastapi import HTTPException, Request

from app.core import cache


def client_ip(request: Request) -> str:
    # Behind a reverse proxy the peer address is the proxy; the first
    # X-Forwarded-For hop is the real client. (If the API is ever exposed
    # without a proxy, a client could spoof this header — the per-identity
    # limits below don't rely on it.)
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _reject(window_seconds: int) -> HTTPException:
    return HTTPException(
        status_code=429,
        detail="Too many requests — please wait a moment and try again.",
        headers={"Retry-After": str(window_seconds)},
    )


def limiter(scope: str, limit: int, window_seconds: int):
    """Dependency: at most ``limit`` calls per ``window_seconds`` per client IP."""

    async def dependency(request: Request) -> None:
        key = f"rl:{scope}:{client_ip(request)}"
        if not await cache.allow(key, limit, window_seconds):
            raise _reject(window_seconds)

    return dependency


async def enforce(scope: str, identity: str, limit: int, window_seconds: int) -> None:
    """Handler-side limit keyed on a caller-supplied identity (email, phone)."""
    key = f"rl:{scope}:{identity.strip().lower()}"
    if not await cache.allow(key, limit, window_seconds):
        raise _reject(window_seconds)
