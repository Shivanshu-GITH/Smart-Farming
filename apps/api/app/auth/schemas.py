from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

# Deliberately loose — just enough shape to reject garbage, not a full RFC 5322.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class OtpRequest(BaseModel):
    phone: str = Field(min_length=6, max_length=20, examples=["+919876543210"])

    @field_validator("phone")
    @classmethod
    def _phone_shape(cls, v: str) -> str:
        v = v.strip()
        if not re.fullmatch(r"\+?[0-9][0-9 \-]{4,18}", v):
            raise ValueError("Enter a valid phone number")
        return v


class OtpRequestResponse(BaseModel):
    sent: bool
    # Only populated when otp_dev_mode is on (no SMS gateway configured).
    dev_code: str | None = None


class OtpVerify(BaseModel):
    phone: str = Field(min_length=6, max_length=20)
    code: str = Field(min_length=4, max_length=8)


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255, examples=["farmer@example.com"])
    password: str = Field(min_length=6, max_length=128)
    name: str | None = Field(default=None, max_length=120)

    @field_validator("email")
    @classmethod
    def _email_shape(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL_RE.fullmatch(v):
            raise ValueError("Enter a valid email address")
        return v


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    id: str
    phone: str | None = None
    email: str | None = None
    name: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
