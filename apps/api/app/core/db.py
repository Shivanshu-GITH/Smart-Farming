"""Async database layer (Postgres + PostGIS).

The engine is created lazily on first use so the API keeps booting in stateless
mode when ``DATABASE_URL`` is empty. Any route that needs persistence depends on
``get_session`` — which raises 503 (not 500) when no database is configured.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def persistence_available() -> bool:
    return bool(get_settings().database_url)


def _ensure_engine() -> None:
    global _engine, _sessionmaker
    if _sessionmaker is not None:
        return
    settings = get_settings()
    if not settings.database_url:
        return
    _engine = create_async_engine(settings.database_url, pool_pre_ping=True, future=True)
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding an async session (503 if no DB configured)."""
    _ensure_engine()
    if _sessionmaker is None:
        raise HTTPException(
            status_code=503,
            detail="Persistence is not configured on this server (set DATABASE_URL).",
        )
    async with _sessionmaker() as session:
        yield session
