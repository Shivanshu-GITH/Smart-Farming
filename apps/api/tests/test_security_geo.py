"""Security hardening + offline village-directory behaviour.

Covers: the bundled district-bbox path (no geocoding call at all), security /
cache-control headers on /auth, and cache isolation between tests.
"""
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.db.models  # noqa: F401 - register tables
from app.core import cache
from app.core.db import Base, get_session
from app.main import app


@pytest.fixture(autouse=True)
def _fresh_cache():
    """Rate-limit windows and cached payloads must not leak between tests."""
    cache._store.clear()
    cache._windows.clear()
    yield
    cache._store.clear()
    cache._windows.clear()


@pytest_asyncio.fixture
async def api(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'t.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)

    async def _override():
        async with sm() as s:
            yield s
    app.dependency_overrides[get_session] = _override

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()
    await engine.dispose()


# ---- offline village directory ----

async def test_villages_served_from_bundled_bbox_without_network(api, monkeypatch):
    pool = [["Alpha", 16.50, 80.60, "v"], ["Beta", 16.52, 80.62, "t"],
            ["Outside", 20.0, 85.0, "v"]]
    monkeypatch.setattr("app.geo.router._state_villages", lambda state: pool)
    monkeypatch.setattr("app.geo.router._bundled_bbox",
                        lambda s, d: [16.4, 16.6, 80.5, 80.7])

    async def _no_network(q):  # the offline path must never geocode
        raise AssertionError("_resolve_admin called on the offline path")
    monkeypatch.setattr("app.geo.router._resolve_admin", _no_network)

    r = await api.get("/geo/villages",
                      params={"state": "Testland", "district": "Middle"})
    assert r.status_code == 200
    body = r.json()
    assert [v["name"] for v in body["villages"]] == ["Alpha", "Beta"]
    assert body["villages"][1]["kind"] == "town"
    assert "error" not in body


async def test_states_and_villages_get_cache_control(api):
    r = await api.get("/geo/states")
    assert r.status_code == 200
    assert "max-age" in r.headers.get("cache-control", "")
    assert len(r.json()["states"]) == 36


# ---- auth response headers ----

async def test_auth_responses_are_not_cacheable(api):
    # Identity/token responses must never land in a shared cache. The middleware
    # sets no-store on every /auth path, including the 403 for a missing token.
    r = await api.get("/auth/me")
    assert r.headers.get("cache-control") == "no-store"


async def test_security_headers_present(api):
    r = await api.get("/health")
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("x-frame-options") == "DENY"
