from __future__ import annotations

import jwt
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import otp
from app.auth.deps import get_current_user
from app.auth.schemas import (
    LoginRequest,
    OtpRequest,
    OtpRequestResponse,
    OtpVerify,
    RegisterRequest,
    TokenResponse,
    UserOut,
)
from app.auth.security import (
    create_access_token,
    hash_password,
    verify_password,
)
from app.auth.service import (
    create_email_user,
    get_or_create_user,
    get_user_by_email,
)
from app.core.config import get_settings
from app.core.db import get_session
from app.db.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_out(user: User) -> UserOut:
    return UserOut(id=user.id, phone=user.phone, email=user.email, name=user.name)


def _token_response(user: User) -> TokenResponse:
    return TokenResponse(access_token=create_access_token(user.id), user=_user_out(user))


# --- Email + password ---

@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(
    req: RegisterRequest, session: AsyncSession = Depends(get_session)
) -> TokenResponse:
    """Create an account with email + password and return a session token."""
    email = req.email.strip().lower()
    if await get_user_by_email(session, email) is not None:
        raise HTTPException(status_code=409, detail="Email already registered")
    user = await create_email_user(session, email, hash_password(req.password), req.name)
    return _token_response(user)


@router.post("/login", response_model=TokenResponse)
async def login(
    req: LoginRequest, session: AsyncSession = Depends(get_session)
) -> TokenResponse:
    """Log in with email + password."""
    user = await get_user_by_email(session, req.email.strip().lower())
    if user is None or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return _token_response(user)


# --- Google sign-in ---

class GoogleAuth(BaseModel):
    credential: str  # Google Identity Services ID token (JWT)


@router.post("/google", response_model=TokenResponse)
async def google_auth(
    req: GoogleAuth, session: AsyncSession = Depends(get_session)
) -> TokenResponse:
    """Sign in with Google. Verifies the GIS ID token against Google's
    tokeninfo endpoint and checks it was issued for OUR client id."""
    import httpx

    client_id = get_settings().google_client_id
    if not client_id:
        raise HTTPException(status_code=503, detail="Google sign-in is not configured.")

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get("https://oauth2.googleapis.com/tokeninfo",
                                    params={"id_token": req.credential})
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Could not verify Google token") from exc
    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid Google token")

    info = resp.json()
    if info.get("aud") != client_id:
        raise HTTPException(status_code=401, detail="Token issued for another app")
    email = (info.get("email") or "").strip().lower()
    if not email or str(info.get("email_verified")).lower() != "true":
        raise HTTPException(status_code=401, detail="Google account has no verified email")

    user = await get_user_by_email(session, email)
    if user is None:
        user = await create_email_user(session, email, None, info.get("name"))
    elif info.get("name") and not user.name:
        user.name = info["name"]
        await session.commit()
    return _token_response(user)


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
    return _token_response(user)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> UserOut:
    return _user_out(user)


class SsoRequest(BaseModel):
    token: str  # JWT issued by the Kadapala Groups site (HS256, shared secret)


@router.post("/sso", response_model=TokenResponse)
async def sso(req: SsoRequest, session: AsyncSession = Depends(get_session)) -> TokenResponse:
    """Single sign-on from the Kadapala Groups website.

    Kadapala signs a short-lived JWT (claims: ``phone``, optional ``name``) with
    the shared ``KADAPALA_SSO_SECRET``; we verify it and mint our own session so a
    farmer logged into the parent site is logged into SmartFarm on the subdomain.
    Scaffold — finalise the exact claim set with the Kadapala auth team.
    """
    secret = get_settings().kadapala_sso_secret
    if not secret:
        raise HTTPException(status_code=503, detail="SSO is not configured.")
    try:
        claims = jwt.decode(req.token, secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid SSO token") from exc

    phone = claims.get("phone")
    if not phone:
        raise HTTPException(status_code=400, detail="SSO token missing 'phone'")
    user = await get_or_create_user(session, phone)
    if claims.get("name") and not user.name:
        user.name = claims["name"]
        await session.commit()
    return _token_response(user)
