"""Persistence for saved fields (owner-scoped)."""
from __future__ import annotations

from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import mapping
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.geo import area_breakdown, polygon_from_geojson
from app.db.models import Field, Layout, Plan
from app.fields.service import reverse_geocode


async def create_field(
    session: AsyncSession, owner_id: str, name: str, geometry: dict
) -> Field:
    from app.core.geo import centroid_latlon, geodesic_area_m2

    polygon = polygon_from_geojson(geometry)
    area_m2 = geodesic_area_m2(polygon)
    lat, lon = centroid_latlon(polygon)
    region = await reverse_geocode(lat, lon)

    field = Field(
        owner_id=owner_id,
        name=name,
        geom=from_shape(polygon, srid=4326),
        area_m2=area_m2,
        region=region,
    )
    session.add(field)
    await session.commit()
    await session.refresh(field)
    return field


async def list_fields(session: AsyncSession, owner_id: str) -> list[Field]:
    result = await session.execute(
        select(Field).where(Field.owner_id == owner_id).order_by(Field.created_at.desc())
    )
    return list(result.scalars().all())


async def get_field(session: AsyncSession, owner_id: str, field_id: str) -> Field | None:
    field = await session.get(Field, field_id)
    if field is None or field.owner_id != owner_id:
        return None
    return field


async def delete_field(session: AsyncSession, owner_id: str, field_id: str) -> bool:
    field = await get_field(session, owner_id, field_id)
    if field is None:
        return False
    await session.delete(field)
    await session.commit()
    return True


def to_out(field: Field) -> dict:
    """Serialize a Field ORM row into the FieldOut shape."""
    geometry = mapping(to_shape(field.geom))
    return {
        "id": field.id,
        "name": field.name,
        "geometry": geometry,
        "area": area_breakdown(field.area_m2) if field.area_m2 is not None else None,
        "region": field.region,
        "created_at": field.created_at.isoformat() if field.created_at else "",
    }


# --- Saved plans (owner-scoped via the parent field) ---

async def save_plan(session: AsyncSession, owner_id: str, field_id: str,
                    name: str | None, data: dict) -> Plan | None:
    if await get_field(session, owner_id, field_id) is None:
        return None
    plan = Plan(field_id=field_id, name=name, data=data)
    session.add(plan)
    await session.commit()
    await session.refresh(plan)
    return plan


async def list_plans(session: AsyncSession, owner_id: str,
                     field_id: str) -> list[Plan] | None:
    if await get_field(session, owner_id, field_id) is None:
        return None
    result = await session.execute(
        select(Plan).where(Plan.field_id == field_id).order_by(Plan.created_at.desc()))
    return list(result.scalars().all())


async def delete_plan(session: AsyncSession, owner_id: str, field_id: str,
                      plan_id: str) -> bool:
    if await get_field(session, owner_id, field_id) is None:
        return False
    plan = await session.get(Plan, plan_id)
    if plan is None or plan.field_id != field_id:
        return False
    await session.delete(plan)
    await session.commit()
    return True


def plan_out(p: Plan) -> dict:
    return {"id": p.id, "field_id": p.field_id, "name": p.name, "data": p.data,
            "created_at": p.created_at.isoformat() if p.created_at else ""}


# --- Saved layouts (owner-scoped via the parent field) ---

async def save_layout(session: AsyncSession, owner_id: str, field_id: str,
                      data: dict) -> Layout | None:
    if await get_field(session, owner_id, field_id) is None:
        return None
    layout = Layout(field_id=field_id, data=data)
    session.add(layout)
    await session.commit()
    await session.refresh(layout)
    return layout


async def list_layouts(session: AsyncSession, owner_id: str,
                       field_id: str) -> list[Layout] | None:
    if await get_field(session, owner_id, field_id) is None:
        return None
    result = await session.execute(
        select(Layout).where(Layout.field_id == field_id).order_by(Layout.created_at.desc()))
    return list(result.scalars().all())


async def delete_layout(session: AsyncSession, owner_id: str, field_id: str,
                        layout_id: str) -> bool:
    if await get_field(session, owner_id, field_id) is None:
        return False
    layout = await session.get(Layout, layout_id)
    if layout is None or layout.field_id != field_id:
        return False
    await session.delete(layout)
    await session.commit()
    return True


def layout_out(L: Layout) -> dict:
    return {"id": L.id, "field_id": L.field_id, "data": L.data,
            "created_at": L.created_at.isoformat() if L.created_at else ""}
