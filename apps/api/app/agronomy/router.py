from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .catalogue import all_crops, layers, load_systems
from .compatibility import suggest_fillers, validate_combo
from .optimizer import design_stacks
from .plan import build_plan
from .recommend import recommend

router = APIRouter(prefix="/agronomy", tags=["agronomy"])


@router.get("/crops")
def crops() -> dict:
    return {"layers": layers(), "crops": all_crops()}


@router.get("/systems")
def systems() -> dict:
    """Farming systems a farmer can choose (monoculture / intercrop / multilayer)."""
    return {"systems": load_systems()}


class RecommendQuery(BaseModel):
    ph: float | None = None
    texture: str | None = None
    rainfall_mm: float | None = None
    temp_max_c: float | None = None
    season: str | None = None
    layer: str | None = None
    system: str | None = None
    limit: int = 8


@router.post("/recommend")
def recommend_crops(q: RecommendQuery) -> dict:
    results = recommend(
        ph=q.ph, texture=q.texture, rainfall=q.rainfall_mm,
        temp_max=q.temp_max_c, season=q.season, layer=q.layer,
        system=q.system, limit=q.limit,
    )
    return {"count": len(results), "recommendations": results}


class PlanQuery(BaseModel):
    crop_id: str
    area_m2: float
    system: str | None = None  # scales quantities to the system's planting area


@router.post("/plan")
def crop_plan(q: PlanQuery) -> dict:
    try:
        return build_plan(q.crop_id, q.area_m2, system=q.system)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


class ValidateQuery(BaseModel):
    crop_ids: list[str]
    system: str = "multilayer"
    # optional land context — enables filler suggestions for empty layers
    ph: float | None = None
    texture: str | None = None
    rainfall_mm: float | None = None
    temp_max_c: float | None = None
    season: str | None = None
    suggest_fillers: bool = True


@router.post("/validate")
def validate(q: ValidateQuery) -> dict:
    """Check whether a chosen crop combo works together for the given farming
    system, and (for multilayer) suggest crops for the empty vertical layers."""
    result = validate_combo(q.crop_ids, q.system)
    if q.suggest_fillers and q.system == "multilayer":
        result["fillers"] = suggest_fillers(
            q.crop_ids, ph=q.ph, texture=q.texture, rainfall=q.rainfall_mm,
            temp_max=q.temp_max_c, season=q.season,
        )
    return result


class DesignQuery(BaseModel):
    ph: float | None = None
    texture: str | None = None
    rainfall_mm: float | None = None
    temp_max_c: float | None = None
    season: str | None = None
    max_stacks: int = 3


@router.post("/design")
def design(q: DesignQuery) -> dict:
    """Propose complete multi-layer (up to 5-layer) planting stacks for the land."""
    return design_stacks(
        ph=q.ph, texture=q.texture, rainfall=q.rainfall_mm,
        temp_max=q.temp_max_c, season=q.season, max_stacks=q.max_stacks,
    )
