"""Auth dependency — resolve the current user from a Supabase Bearer token."""
from __future__ import annotations

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.service import get_or_create_supabase_user
from app.auth.supabase import SupabaseAuthError, verify_supabase_jwt
from app.core.db import get_session
from app.db.models import User

_bearer = HTTPBearer(auto_error=True)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> User:
    try:
        claims = verify_supabase_jwt(credentials.credentials)
    except SupabaseAuthError as exc:
        # Misconfiguration (no SUPABASE_URL) or an unusable token — not the
        # caller's fault to fix, but from their side it's an unauthenticated call.
        raise HTTPException(status_code=401, detail="Authentication unavailable") from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc

    sub = claims.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    email = claims.get("email")
    meta = claims.get("user_metadata") or {}
    name = meta.get("full_name") or meta.get("name")
    return await get_or_create_supabase_user(session, sub, email, name)
