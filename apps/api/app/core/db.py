"""Async database layer.

Portable across SQLite (zero-config dev — the default in .env is a local file)
and Postgres (prod). The engine is created lazily so the API keeps booting in
stateless mode when ``DATABASE_URL`` is empty; any route that needs persistence
depends on ``get_session``, which raises 503 (not 500) when no DB is configured.
On startup we create tables for SQLite so login/persistence work out of the box;
Postgres uses Alembic migrations.
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


async def init_db() -> None:
    """Create tables when using SQLite (dev). No-op without a DB; Postgres uses
    Alembic. Safe to call on every startup — create_all only adds missing tables.
    """
    _ensure_engine()
    if _engine is None:
        return
    import app.db.models  # noqa: F401 - register tables on Base.metadata

    if _engine.url.get_backend_name() == "sqlite":
        async with _engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)


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
