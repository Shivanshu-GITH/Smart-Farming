"""ORM models for SmartFarm persistence.

All models live here so Alembic autogenerate has a single import point. Field
geometry is stored natively in PostGIS (SRID 4326 polygon); everything else that
is provider-shaped (region, soil/climate reports, plan JSON, layout points) is
kept as JSONB so the curated-knowledge-base shape can evolve without migrations.
"""
from __future__ import annotations

import datetime as dt
import uuid

from geoalchemy2 import Geometry
from sqlalchemy import DateTime, Float, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now_col() -> Mapped[dt.datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    phone: Mapped[str] = mapped_column(String(20), unique=True, index=True)
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
    geom = mapped_column(Geometry(geometry_type="POLYGON", srid=4326), nullable=False)
    area_m2: Mapped[float | None] = mapped_column(Float, nullable=True)
    region: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
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
    """Cached soil + climate (+ later NDVI) snapshot for a field."""

    __tablename__ = "land_reports"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    field_id: Mapped[str] = mapped_column(
        ForeignKey("fields.id", ondelete="CASCADE"), index=True
    )
    data: Mapped[dict] = mapped_column(JSONB)
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
    data: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[dt.datetime] = _now_col()

    field: Mapped[Field] = relationship(back_populates="plans")


class Layout(Base):
    """A saved spatial planting layout (per-plant points + heatmap) for a field."""

    __tablename__ = "layouts"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    field_id: Mapped[str] = mapped_column(
        ForeignKey("fields.id", ondelete="CASCADE"), index=True
    )
    data: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[dt.datetime] = _now_col()

    field: Mapped[Field] = relationship(back_populates="layouts")
