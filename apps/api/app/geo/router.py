"""Location search (forward geocoding) so a farmer can find their village/field.

Proxies OSM Nominatim's search API (free; requires a User-Agent and modest
rate use — results are cached). India-biased by default since the product is
pan-India, but the bias can be lifted with ``india_only=false``.
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Query

from app.core import cache

router = APIRouter(prefix="/geo", tags=["geo"])

NOMINATIM_SEARCH = "https://nominatim.openstreetmap.org/search"
_HEADERS = {"User-Agent": "SmartFarm/1.0 (precision-farm-planning)"}


@router.get("/search")
async def search(q: str = Query(min_length=2, max_length=200),
                 limit: int = Query(default=5, ge=1, le=10),
                 india_only: bool = True) -> dict:
    key = f"geosearch:{q.strip().lower()}:{limit}:{india_only}"
    cached = await cache.get(key)
    if cached is not None:
        return cached

    params = {
        "q": q.strip(),
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
