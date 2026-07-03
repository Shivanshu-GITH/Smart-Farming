from __future__ import annotations

from pydantic import BaseModel, Field


class OtpRequest(BaseModel):
    phone: str = Field(min_length=6, max_length=20, examples=["+919876543210"])


class OtpRequestResponse(BaseModel):
    sent: bool
    # Only populated when otp_dev_mode is on (no SMS gateway configured).
    dev_code: str | None = None


class OtpVerify(BaseModel):
    phone: str = Field(min_length=6, max_length=20)
    code: str = Field(min_length=4, max_length=8)


class UserOut(BaseModel):
    id: str
    phone: str
    name: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
