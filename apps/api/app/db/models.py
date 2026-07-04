"""ORM models for SmartFarm persistence.

Portable across SQLite (zero-config dev) and Postgres (prod): field geometry is
stored as GeoJSON in a JSON column (we clip/measure in-memory with shapely, not
in the DB), and all provider-shaped blobs use the generic JSON type. Users can
authenticate by phone (OTP) or email+password.
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now_col() -> Mapped[dt.datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    # A user has at least one of phone / email (both unique when present).
    phone: Mapped[str | None] = mapped_column(String(20), unique=True, index=True,
                                              nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, index=True,
                                              nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[dt.datetime] = _now_col()

    fields: Mapped[list["Field"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )


class Field(Base):
    __tablename__ = "fields"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160))
    geometry: Mapped[dict] = mapped_column(JSON)  # GeoJSON Polygon
    area_m2: Mapped[float | None] = mapped_column(Float, nullable=True)
    region: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[dt.datetime] = _now_col()

    owner: Mapped[User] = relationship(back_populates="fields")
    reports: Mapped[list["LandReport"]] = relationship(
        back_populates="field", cascade="all, delete-orphan"
    )
    plans: Mapped[list["Plan"]] = relationship(
        back_populates="field", cascade="all, delete-orphan"
    )
    layouts: Mapped[list["Layout"]] = relationship(
        back_populates="field", cascade="all, delete-orphan"
    )


class LandReport(Base):
    """Cached soil + climate (+ NDVI) snapshot for a field."""

    __tablename__ = "land_reports"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    field_id: Mapped[str] = mapped_column(
        ForeignKey("fields.id", ondelete="CASCADE"), index=True
    )
    data: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[dt.datetime] = _now_col()

    field: Mapped[Field] = relationship(back_populates="reports")


class Plan(Base):
    """A saved agronomic plan (crop(s), seed/fertilizer, calendar) for a field."""

    __tablename__ = "plans"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    field_id: Mapped[str] = mapped_column(
        ForeignKey("fields.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    data: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[dt.datetime] = _now_col()

    field: Mapped[Field] = relationship(back_populates="plans")


class Layout(Base):
    """A saved spatial planting layout (per-plant points + heatmap) for a field."""

    __tablename__ = "layouts"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    field_id: Mapped[str] = mapped_column(
        ForeignKey("fields.id", ondelete="CASCADE"), index=True
    )
    data: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[dt.datetime] = _now_col()

    field: Mapped[Field] = relationship(back_populates="layouts")
