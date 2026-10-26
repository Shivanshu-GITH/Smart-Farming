"""Auth routes.

Sign-in, sign-up and Google OAuth are handled entirely by Supabase on the
frontend. The only endpoint here echoes the authenticated user (identity resolved
from the verified Supabase token), which the web app uses to confirm a session.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth.deps import get_current_user
from app.auth.schemas import UserOut
from app.db.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut(id=user.id, phone=user.phone, email=user.email, name=user.name)
