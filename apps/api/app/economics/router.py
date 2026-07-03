from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import mandi
from .estimator import estimate

router = APIRouter(prefix="/economics", tags=["economics"])


class EstimateRequest(BaseModel):
    crop_ids: list[str] = Field(min_length=1)
    area_m2: float = Field(gt=0)
    state: str | None = None
    use_mandi: bool = True


@router.post("/estimate")
async def estimate_economics(req: EstimateRequest) -> dict:
    """Cost / revenue / profit estimate for a crop or multi-layer stack.

    Uses live mandi prices when available (and requested), else curated
    farm-gate estimates.
    """
    prices: dict[str, float] = {}
    price_info: dict[str, dict] = {}
    if req.use_mandi:
        price_info = await mandi.get_prices(req.crop_ids, req.state)
        prices = {
            cid: info["price_per_kg"]
            for cid, info in price_info.items()
            if info.get("source") == "mandi" and info.get("price_per_kg") is not None
        }

    result = estimate(req.crop_ids, req.area_m2, prices)
    result["prices"] = price_info
    return result


@router.get("/price")
async def price(crop: str, state: str | None = None) -> dict:
    """Latest mandi price for a single crop (falls back to estimate)."""
    info = await mandi.get_price(crop, state)
    if info.get("price_per_kg") is None:
        raise HTTPException(status_code=404, detail=f"Unknown crop '{crop}'")
    return info
