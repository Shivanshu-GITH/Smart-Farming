"""Verify Supabase access tokens.

Authentication is owned by Supabase (email + Google). The frontend signs in with
Supabase and calls this API with the Supabase access token as a Bearer token; we
verify that token here and trust its `sub` (the Supabase user id) as the identity.

Supabase signs user tokens with asymmetric keys (ES256/RS256) exposed at the
project's JWKS endpoint, so verification needs no shared secret — only the public
key, which we fetch and cache. Older projects that still sign with the legacy
HS256 secret can set SUPABASE_JWT_SECRET instead.
"""
from __future__ import annotations

from functools import lru_cache

import jwt
from jwt import PyJWKClient

from app.core.config import get_settings


class SupabaseAuthError(Exception):
    """Auth is unconfigured, or the token could not be verified."""


@lru_cache(maxsize=4)
def _jwks_client(jwks_url: str) -> PyJWKClient:
    # PyJWKClient caches fetched keys and only refetches on an unknown `kid`,
    # so a rotated signing key is picked up without a restart.
    return PyJWKClient(jwks_url)


def _signing_key(token: str, supabase_url: str):
    """Public key for an asymmetric (ES256/RS256) Supabase token, via JWKS."""
    jwks_url = f"{supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
    return _jwks_client(jwks_url).get_signing_key_from_jwt(token).key


def verify_supabase_jwt(token: str) -> dict:
    """Return the verified claims of a Supabase access token.

    Raises SupabaseAuthError if auth is unconfigured, or jwt.PyJWTError if the
    token is invalid, expired, or issued for the wrong audience.
    """
    settings = get_settings()
    if not settings.supabase_url:
        raise SupabaseAuthError("Supabase auth is not configured (set SUPABASE_URL).")

    alg = jwt.get_unverified_header(token).get("alg")
    options = {"require": ["exp", "sub"]}
    aud = settings.supabase_jwt_aud

    if alg == "HS256":
        if not settings.supabase_jwt_secret:
            raise SupabaseAuthError(
                "Token is HS256-signed but SUPABASE_JWT_SECRET is not set.")
        return jwt.decode(token, settings.supabase_jwt_secret,
                          algorithms=["HS256"], audience=aud, options=options)

    key = _signing_key(token, settings.supabase_url)
    return jwt.decode(token, key, algorithms=["ES256", "RS256"],
                      audience=aud, options=options)
