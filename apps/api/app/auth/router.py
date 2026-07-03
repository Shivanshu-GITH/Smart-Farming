from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import otp
from app.auth.deps import get_current_user
from app.auth.schemas import (
    OtpRequest,
    OtpRequestResponse,
    OtpVerify,
    TokenResponse,
    UserOut,
)
from app.auth.security import create_access_token
from app.auth.service import get_or_create_user
from app.core.config import get_settings
from app.core.db import get_session
from app.db.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/otp/request", response_model=OtpRequestResponse)
async def request_otp(req: OtpRequest) -> OtpRequestResponse:
    """Issue a one-time code for a phone number.

    No DB needed to request a code. In dev mode the code is returned so you can
    sign in without an SMS gateway.
    """
    code = await otp.issue_otp(req.phone)
    dev = get_settings().otp_dev_mode
    return OtpRequestResponse(sent=True, dev_code=code if dev else None)


@router.post("/otp/verify", response_model=TokenResponse)
async def verify_otp(
    req: OtpVerify, session: AsyncSession = Depends(get_session)
) -> TokenResponse:
    """Verify a code, create the user on first sign-in, return a JWT."""
    if not await otp.verify_otp(req.phone, req.code):
        raise HTTPException(status_code=401, detail="Invalid or expired code")
    user = await get_or_create_user(session, req.phone)
    token = create_access_token(user.id)
    return TokenResponse(
        access_token=token,
        user=UserOut(id=user.id, phone=user.phone, name=user.name),
    )


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut(id=user.id, phone=user.phone, name=user.name)
