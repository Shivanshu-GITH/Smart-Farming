from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .catalogue import all_crops, layers
from .plan import build_plan
from .recommend import recommend

router = APIRouter(prefix="/agronomy", tags=["agronomy"])


@router.get("/crops")
def crops() -> dict:
    return {"layers": layers(), "crops": all_crops()}


class RecommendQuery(BaseModel):
    ph: float | None = None
    texture: str | None = None
    rainfall_mm: float | None = None
    temp_max_c: float | None = None
    season: str | None = None
    layer: str | None = None
    limit: int = 8


@router.post("/recommend")
def recommend_crops(q: RecommendQuery) -> dict:
    results = recommend(
        ph=q.ph, texture=q.texture, rainfall=q.rainfall_mm,
        temp_max=q.temp_max_c, season=q.season, layer=q.layer, limit=q.limit,
    )
    return {"count": len(results), "recommendations": results}


class PlanQuery(BaseModel):
    crop_id: str
    area_m2: float


@router.post("/plan")
def crop_plan(q: PlanQuery) -> dict:
    try:
        return build_plan(q.crop_id, q.area_m2)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
