"""Supabase access-token verification + the /auth/me identity path.

Mints ES256 tokens with a throwaway key and monkeypatches the JWKS lookup to
return its public half, so the real verifier + user-upsert run with no network.
"""
import time

import jwt
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.db.models  # noqa: F401 - register tables
from app.auth import supabase as sb
from app.core.config import get_settings
from app.core.db import Base, get_session
from app.main import app

_PRIV = ec.generate_private_key(ec.SECP256R1())
_PRIV_PEM = _PRIV.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
)
_PUB_PEM = _PRIV.public_key().public_bytes(
    serialization.Encoding.PEM,
    serialization.PublicFormat.SubjectPublicKeyInfo,
)


def _token(**overrides) -> str:
    now = int(time.time())
    payload = {
        "sub": "abcd1234-0000-0000-0000-000000000001",
        "email": "farmer@example.com",
        "aud": "authenticated",
        "iat": now,
        "exp": now + 3600,
    }
    payload.update(overrides)
    return jwt.encode(payload, _PRIV_PEM, algorithm="ES256",
                      headers={"kid": "test-kid"})


@pytest.fixture(autouse=True)
def _configure(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "supabase_url", "https://test.supabase.co")
    monkeypatch.setattr(s, "supabase_jwt_aud", "authenticated")
    # Serve our public key instead of fetching the project's JWKS.
    monkeypatch.setattr(sb, "_signing_key", lambda token, url: _PUB_PEM)
    yield


# ---- verifier unit tests ----

def test_valid_token_decodes():
    claims = sb.verify_supabase_jwt(_token())
    assert claims["sub"] == "abcd1234-0000-0000-0000-000000000001"
    assert claims["email"] == "farmer@example.com"


def test_wrong_audience_rejected():
    with pytest.raises(jwt.InvalidAudienceError):
        sb.verify_supabase_jwt(_token(aud="anon"))


def test_expired_token_rejected():
    with pytest.raises(jwt.ExpiredSignatureError):
        sb.verify_supabase_jwt(_token(exp=int(time.time()) - 10))


def test_unconfigured_raises(monkeypatch):
    monkeypatch.setattr(get_settings(), "supabase_url", "")
    with pytest.raises(sb.SupabaseAuthError):
        sb.verify_supabase_jwt(_token())


# ---- /auth/me integration (verify -> upsert -> echo) ----

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


async def test_me_creates_user_from_token(api):
    h = {"Authorization": f"Bearer {_token(user_metadata={'full_name': 'Ravi K'})}"}
    me = await api.get("/auth/me", headers=h)
    assert me.status_code == 200
    body = me.json()
    assert body["id"] == "abcd1234-0000-0000-0000-000000000001"
    assert body["email"] == "farmer@example.com"
    assert body["name"] == "Ravi K"

    # idempotent — a second call reuses the same row, still 200
    assert (await api.get("/auth/me", headers=h)).status_code == 200


async def test_me_without_token_is_403(api):
    assert (await api.get("/auth/me")).status_code == 403


async def test_fields_reject_garbage_token(api):
    h = {"Authorization": "Bearer not.a.real.token"}
    assert (await api.get("/fields", headers=h)).status_code == 401
