from __future__ import annotations

import asyncio

from fastapi import APIRouter
from pydantic import BaseModel

from .soil import get_soil
from .weather import get_climate

router = APIRouter(prefix="/land-intel", tags=["land-intel"])


class PointQuery(BaseModel):
    lat: float
    lon: float


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
