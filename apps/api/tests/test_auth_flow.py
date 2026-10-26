"""Field + plan persistence on an isolated SQLite DB.

Authentication itself (verifying a Supabase token) is covered in
test_supabase_auth.py; here we override the current-user dependency so the
persistence paths can be tested without minting a token per request.
"""
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.db.models  # noqa: F401 - register tables
from app.auth.deps import get_current_user
from app.core.db import Base, get_session
from app.db.models import User
from app.main import app

GEOM = {"type": "Polygon", "coordinates": [[[80.60, 16.50], [80.607, 16.50],
        [80.607, 16.507], [80.60, 16.507], [80.60, 16.50]]]}

TEST_USER_ID = "11111111-1111-1111-1111-111111111111"


@pytest_asyncio.fixture
async def api(tmp_path, monkeypatch):
    # avoid the Nominatim network call in field creation
    async def _fake_geocode(lat, lon):
        return {"state": "Andhra Pradesh", "district": "Krishna"}
    monkeypatch.setattr("app.fields.crud.reverse_geocode", _fake_geocode)

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'t.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)

    # Seed the signed-in user so saved fields have a real owner row.
    async with sm() as s:
        s.add(User(id=TEST_USER_ID, email="f@farm.com", name="Ravi"))
        await s.commit()

    async def _override_session():
        async with sm() as s:
            yield s

    async def _override_user():
        return User(id=TEST_USER_ID, email="f@farm.com", name="Ravi")

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = _override_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()
    await engine.dispose()


async def test_me_returns_authenticated_user(api):
    me = await api.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "f@farm.com"


async def test_field_and_plan_persist(api):
    created = await api.post("/fields", json={"name": "North plot", "geometry": GEOM})
    assert created.status_code == 201
    fid = created.json()["id"]
    assert created.json()["geometry"]["type"] == "Polygon"
    assert created.json()["area"]["acres"] > 0

    listed = await api.get("/fields")
    assert listed.status_code == 200 and len(listed.json()) == 1

    saved = await api.post(f"/fields/{fid}/plans",
                           json={"name": "p1", "data": {"crop": "tomato"}})
    assert saved.status_code == 201
