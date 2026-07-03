"""Auth dependencies — resolve the current user from a Bearer token."""
from __future__ import annotations

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import decode_token
from app.auth.service import get_user
from app.core.db import get_session
from app.db.models import User

_bearer = HTTPBearer(auto_error=True)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> User:
    try:
        payload = decode_token(credentials.credentials)
        user_id = payload.get("sub")
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc

    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    user = await get_user(session, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="User no longer exists")
    return user
