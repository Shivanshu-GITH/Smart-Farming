from __future__ import annotations

from pydantic import BaseModel


class UserOut(BaseModel):
    id: str
    phone: str | None = None
    email: str | None = None
    name: str | None = None
