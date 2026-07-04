from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.fields.schemas import GeoJSONGeometry

from .ndvi import get_ndvi, get_ndvi_series
from .soil import get_soil
from .weather import get_climate

router = APIRouter(prefix="/land-intel", tags=["land-intel"])


class PointQuery(BaseModel):
    lat: float
    lon: float


class GeometryQuery(BaseModel):
    geometry: GeoJSONGeometry


@router.get("/soil")
async def soil(lat: float, lon: float) -> dict:
    return await get_soil(lat, lon)


@router.get("/climate")
async def climate(lat: float, lon: float) -> dict:
    return await get_climate(lat, lon)


@router.get("/report")
async def report(lat: float, lon: float) -> dict:
    """Combined land-intelligence report for a point (soil + climate)."""
    soil_data, climate_data = await asyncio.gather(
        get_soil(lat, lon), get_climate(lat, lon)
    )
    return {"lat": lat, "lon": lon, "soil": soil_data, "climate": climate_data}


@router.post("/ndvi")
async def ndvi(q: GeometryQuery) -> dict:
    """Mean NDVI (vegetation vigour) over a field polygon from Sentinel-2."""
    try:
        return await get_ndvi(q.geometry.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class NdviSeriesQuery(GeometryQuery):
    months: int = 6


@router.post("/ndvi-series")
async def ndvi_series(q: NdviSeriesQuery) -> dict:
    """NDVI trend over recent months (time-series field monitoring)."""
    try:
        return await get_ndvi_series(q.geometry.model_dump(), q.months)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
