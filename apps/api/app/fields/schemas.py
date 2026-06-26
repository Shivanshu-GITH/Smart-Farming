from __future__ import annotations

from pydantic import BaseModel, Field


class GeoJSONGeometry(BaseModel):
    type: str = Field(examples=["Polygon"])
    coordinates: list = Field(
        description="GeoJSON Polygon coordinates: [[[lon, lat], ...]]"
    )


class FieldRequest(BaseModel):
    geometry: GeoJSONGeometry


class AreaBreakdown(BaseModel):
    square_meters: float
    hectares: float
    acres: float
    guntha: float


class Region(BaseModel):
    display_name: str | None = None
    village: str | None = None
    district: str | None = None
    state: str | None = None
    country: str | None = None


class FieldSummary(BaseModel):
    area: AreaBreakdown
    perimeter_meters: float
    centroid: dict  # {"lat": .., "lon": ..}
    bbox: list[float]  # [min_lon, min_lat, max_lon, max_lat]
    region: Region
