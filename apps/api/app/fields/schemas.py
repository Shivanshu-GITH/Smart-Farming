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


# --- Persistence (saved fields) ---

class FieldCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    geometry: GeoJSONGeometry


class FieldOut(BaseModel):
    id: str
    name: str
    geometry: dict  # GeoJSON Polygon
    area: AreaBreakdown | None = None
    region: Region | None = None
    created_at: str


# --- Saved plans & layouts (belong to a field) ---

class PlanCreate(BaseModel):
    name: str | None = Field(default=None, max_length=160)
    data: dict


class SavedPlanOut(BaseModel):
    id: str
    field_id: str
    name: str | None = None
    data: dict
    created_at: str


class LayoutCreate(BaseModel):
    data: dict


class SavedLayoutOut(BaseModel):
    id: str
    field_id: str
    data: dict
    created_at: str
