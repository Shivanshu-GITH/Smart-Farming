import jwt
import pytest

from app.auth import otp
from app.auth.security import create_access_token, decode_token
from app.core import cache


async def test_cache_roundtrip_and_delete():
    await cache.set("k1", {"a": 1}, ttl_seconds=30)
    assert await cache.get("k1") == {"a": 1}
    await cache.delete("k1")
    assert await cache.get("k1") is None


async def test_rate_limiter_allows_then_blocks():
    key = "rl:test-unit"
    results = [await cache.allow(key, limit=3, window_seconds=60) for _ in range(5)]
    assert results == [True, True, True, False, False]


async def test_otp_is_single_use():
    code = await otp.issue_otp("+910000000001")
    assert await otp.verify_otp("+910000000001", code) is True
    assert await otp.verify_otp("+910000000001", code) is False  # consumed


async def test_otp_wrong_code_rejected():
    await otp.issue_otp("+910000000002")
    assert await otp.verify_otp("+910000000002", "000000") is False


def test_jwt_roundtrip():
    token = create_access_token("user-xyz")
    assert decode_token(token)["sub"] == "user-xyz"


def test_jwt_tampered_token_raises():
    with pytest.raises(jwt.PyJWTError):
        decode_token("not.a.valid.token")
