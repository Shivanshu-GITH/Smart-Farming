"""Persistence for saved fields (owner-scoped)."""
from __future__ import annotations

from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import mapping
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.geo import area_breakdown, polygon_from_geojson
from app.db.models import Field
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
