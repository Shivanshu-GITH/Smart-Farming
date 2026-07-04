"""Admin analytics — aggregate platform stats, gated by a shared admin token.

Requires persistence; returns 503 without a DB and 401/403 without a valid
``X-Admin-Token`` header. Read-only counts only — no user data is exposed.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.db.models import Field, LandReport, Layout, Plan, User

router = APIRouter(prefix="/admin", tags=["admin"])


def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    token = get_settings().admin_token
    if not token:
        raise HTTPException(status_code=503, detail="Admin API is not enabled.")
    if x_admin_token != token:
        raise HTTPException(status_code=403, detail="Invalid admin token.")


@router.get("/stats", dependencies=[Depends(require_admin)])
async def stats(session: AsyncSession = Depends(get_session)) -> dict:
    async def count(model) -> int:
        return (await session.execute(select(func.count()).select_from(model))).scalar_one()

    return {
        "users": await count(User),
        "fields": await count(Field),
        "plans": await count(Plan),
        "layouts": await count(Layout),
        "land_reports": await count(LandReport),
    }
