"""End-to-end auth + persistence on an isolated SQLite DB.

Proves email register/login, phone OTP, and field/plan persistence work without
any external infrastructure. Uses a temp SQLite file and overrides get_session;
reverse_geocode is stubbed so no network is touched.
"""
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.db.models  # noqa: F401 - register tables
from app.core.db import Base, get_session
from app.main import app

GEOM = {"type": "Polygon", "coordinates": [[[80.60, 16.50], [80.607, 16.50],
        [80.607, 16.507], [80.60, 16.507], [80.60, 16.50]]]}


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

    async def _override():
        async with sm() as s:
            yield s
    app.dependency_overrides[get_session] = _override

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()
    await engine.dispose()


async def test_email_register_login_me(api):
    r = await api.post("/auth/register",
                       json={"email": "A@Farm.com", "password": "secret123", "name": "Ravi"})
    assert r.status_code == 201
    token = r.json()["access_token"]
    assert r.json()["user"]["email"] == "a@farm.com"  # normalised

    # duplicate email
    assert (await api.post("/auth/register",
            json={"email": "a@farm.com", "password": "secret123"})).status_code == 409
    # wrong password
    assert (await api.post("/auth/login",
            json={"email": "a@farm.com", "password": "nope"})).status_code == 401
    # correct login
    assert (await api.post("/auth/login",
            json={"email": "a@farm.com", "password": "secret123"})).status_code == 200
    # /me with the token
    me = await api.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200 and me.json()["email"] == "a@farm.com"


async def test_phone_otp_flow(api):
    code = (await api.post("/auth/otp/request",
            json={"phone": "+919000000001"})).json()["dev_code"]
    r = await api.post("/auth/otp/verify",
                       json={"phone": "+919000000001", "code": code})
    assert r.status_code == 200
    assert r.json()["user"]["phone"] == "+919000000001"


async def test_field_and_plan_persist(api):
    token = (await api.post("/auth/register",
             json={"email": "f@farm.com", "password": "secret123"})).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}

    created = await api.post("/fields", json={"name": "North plot", "geometry": GEOM}, headers=h)
    assert created.status_code == 201
    fid = created.json()["id"]
    assert created.json()["geometry"]["type"] == "Polygon"
    assert created.json()["area"]["acres"] > 0

    listed = await api.get("/fields", headers=h)
    assert listed.status_code == 200 and len(listed.json()) == 1

    saved = await api.post(f"/fields/{fid}/plans",
                           json={"name": "p1", "data": {"crop": "tomato"}}, headers=h)
    assert saved.status_code == 201
