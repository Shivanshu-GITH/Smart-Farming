from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.fields.schemas import GeoJSONGeometry

from .engine import generate_layout

router = APIRouter(prefix="/layout", tags=["layout"])


class LayoutRequest(BaseModel):
    geometry: GeoJSONGeometry
    crop_ids: list[str]
    system: str = "multilayer"  # monoculture | intercrop | multilayer


@router.post("")
def layout(req: LayoutRequest) -> dict:
    """Generate per-plant placement points (+ density heatmap) for the field."""
    if not req.crop_ids:
        raise HTTPException(status_code=422, detail="Provide at least one crop_id")
    try:
        return generate_layout(req.geometry.model_dump(), req.crop_ids, req.system)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
