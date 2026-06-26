from __future__ import annotations

import httpx

from app.core import cache
from app.core.geo import (
    area_breakdown,
    centroid_latlon,
    geodesic_area_m2,
    geodesic_perimeter_m,
    polygon_from_geojson,
)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
_HEADERS = {"User-Agent": "SmartFarm/0.1 (precision-farm-planning)"}


async def reverse_geocode(lat: float, lon: float) -> dict:
    """Look up village/district/state for a point (cached, OSM Nominatim)."""
    key = cache.geo_key("geocode", lat, lon, precision=2)
    cached = cache.get(key)
    if cached is not None:
        return cached

    params = {"lat": lat, "lon": lon, "format": "jsonv2", "zoom": "12"}
    region = {"display_name": None, "village": None, "district": None,
              "state": None, "country": None}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(NOMINATIM_URL, params=params, headers=_HEADERS)
            resp.raise_for_status()
            data = resp.json()
            addr = data.get("address", {})
            region = {
                "display_name": data.get("display_name"),
                "village": addr.get("village") or addr.get("town")
                or addr.get("city") or addr.get("hamlet"),
                "district": addr.get("state_district") or addr.get("county"),
                "state": addr.get("state"),
                "country": addr.get("country"),
            }
    except (httpx.HTTPError, ValueError):
        pass  # region stays as the empty template — geometry still returns

    cache.set(key, region, ttl_seconds=7 * 86_400)
    return region


async def summarize_field(geometry: dict) -> dict:
    polygon = polygon_from_geojson(geometry)
    area_m2 = geodesic_area_m2(polygon)
    lat, lon = centroid_latlon(polygon)
    region = await reverse_geocode(lat, lon)

    return {
        "area": area_breakdown(area_m2),
        "perimeter_meters": round(geodesic_perimeter_m(polygon), 2),
        "centroid": {"lat": round(lat, 6), "lon": round(lon, 6)},
        "bbox": list(polygon.bounds),  # (minx, miny, maxx, maxy)
        "region": region,
    }
