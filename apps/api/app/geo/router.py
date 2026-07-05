"""Location search so a farmer can find their village/field.

Two complementary paths:
- Layered finder: bundled all-India states/districts (GET /geo/states,
  /geo/districts) narrow the free-text village search to one district, which
  makes small-place names resolvable.
- Free-text search: proxies OSM Nominatim (free; needs a User-Agent and modest
  rate use — results are cached). India-biased by default.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Query

from app.core import cache

router = APIRouter(prefix="/geo", tags=["geo"])

NOMINATIM_SEARCH = "https://nominatim.openstreetmap.org/search"
_HEADERS = {"User-Agent": "SmartFarm/1.0 (precision-farm-planning)"}

# apps/api/app/geo/router.py -> repo root is 4 levels up
_REPO_ROOT = Path(__file__).resolve().parents[4]
_PLACES_DB = _REPO_ROOT / "packages" / "india-geo" / "states-districts.json"


@lru_cache
def _places() -> dict:
    with _PLACES_DB.open(encoding="utf-8") as fh:
        return json.load(fh)


@router.get("/states")
def states() -> dict:
    """All Indian states/UTs for the layered location finder."""
    return {"states": [s["name"] for s in _places()["states"]]}


@router.get("/districts")
def districts(state: str = Query(min_length=2, max_length=80)) -> dict:
    """Districts of one state/UT."""
    for s in _places()["states"]:
        if s["name"].lower() == state.strip().lower():
            return {"state": s["name"], "districts": s["districts"]}
    raise HTTPException(status_code=404, detail=f"Unknown state '{state}'")


@router.get("/search")
async def search(q: str = Query(min_length=2, max_length=200),
                 limit: int = Query(default=5, ge=1, le=10),
                 state: str | None = Query(default=None, max_length=80),
                 district: str | None = Query(default=None, max_length=80),
                 india_only: bool = True) -> dict:
    """Free-text place search. When ``state``/``district`` are given the query
    is scoped to them, so tiny villages resolve instead of drowning in
    same-named places elsewhere."""
    scoped_q = ", ".join(p for p in [q.strip(), (district or "").strip(),
                                     (state or "").strip()] if p)
    key = f"geosearch:{scoped_q.lower()}:{limit}:{india_only}"
    cached = await cache.get(key)
    if cached is not None:
        return cached

    params = {
        "q": scoped_q,
        "format": "jsonv2",
        "limit": str(limit),
        "addressdetails": "0",
    }
    if india_only:
        params["countrycodes"] = "in"

    results: list[dict] = []
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(NOMINATIM_SEARCH, params=params, headers=_HEADERS)
            resp.raise_for_status()
            for item in resp.json():
                try:
                    bbox = [float(v) for v in item.get("boundingbox", [])]
                except (TypeError, ValueError):
                    bbox = []
                results.append({
                    "display_name": item.get("display_name"),
                    "lat": float(item["lat"]),
                    "lon": float(item["lon"]),
                    "type": item.get("type"),
                    # Nominatim bbox order: [south, north, west, east]
                    "bbox": bbox if len(bbox) == 4 else None,
                })
    except (httpx.HTTPError, ValueError, KeyError):
        return {"query": q, "results": [], "error": "Search unavailable; try again"}

    out = {"query": q, "results": results}
    await cache.set(key, out, ttl_seconds=7 * 86_400)
    return out
