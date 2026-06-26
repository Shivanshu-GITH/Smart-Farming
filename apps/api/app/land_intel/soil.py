"""Soil intelligence via the ISRIC SoilGrids v2.0 REST API.

SoilGrids is global, free (CC-BY) and ~250 m resolution. It is rate limited to
~5 calls/min, so every lookup is cached by a coarse geo-key. Values are
*estimates* for planning, never a substitute for a lab soil test.
"""
from __future__ import annotations

import httpx

from app.core import cache

SOILGRIDS_URL = "https://rest.isric.org/soilgrids/v2.0/properties/query"

# property -> (depth, conversion factor to human units, unit label)
# SoilGrids returns integers scaled by a d_factor; we convert to real units.
_PROPS = {
    "phh2o": (10.0, "pH"),          # pH*10  -> pH
    "clay": (10.0, "%"),            # g/kg*10? actually returned in g/kg /10 -> %
    "sand": (10.0, "%"),
    "silt": (10.0, "%"),
    "soc": (10.0, "g/kg"),          # soil organic carbon, dg/kg -> g/kg
    "nitrogen": (100.0, "g/kg"),    # cg/kg -> g/kg
    "cec": (10.0, "cmol(c)/kg"),    # cation exchange capacity
    "bdod": (100.0, "g/cm3"),       # bulk density, cg/cm3 -> g/cm3
}


def _texture_class(sand: float | None, clay: float | None) -> str | None:
    """Coarse USDA-ish texture label from sand/clay percentages."""
    if sand is None or clay is None:
        return None
    if clay >= 40:
        return "Clay"
    if sand >= 70 and clay < 15:
        return "Sandy"
    if clay >= 27 and sand <= 45:
        return "Clay loam"
    if sand >= 52:
        return "Sandy loam"
    if clay < 27 and sand < 52:
        return "Loam / Silt loam"
    return "Loam"


async def get_soil(lat: float, lon: float) -> dict:
    key = cache.geo_key("soil", lat, lon, precision=3)
    cached = cache.get(key)
    if cached is not None:
        return cached

    params = [("lat", lat), ("lon", lon), ("depth", "0-5cm"),
              ("depth", "5-15cm"), ("value", "mean")]
    for p in _PROPS:
        params.append(("property", p))

    result: dict = {"source": "ISRIC SoilGrids v2.0", "estimate": True,
                    "properties": {}, "lat": lat, "lon": lon}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(SOILGRIDS_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
        for layer in data.get("properties", {}).get("layers", []):
            name = layer.get("name")
            factor, unit = _PROPS.get(name, (1.0, ""))
            depths = layer.get("depths", [])
            if not depths:
                continue
            mean = depths[0].get("values", {}).get("mean")
            value = round(mean / factor, 2) if mean is not None else None
            result["properties"][name] = {"value": value, "unit": unit}
    except (httpx.HTTPError, ValueError, KeyError):
        result["error"] = "SoilGrids unavailable; try again shortly"

    props = result["properties"]
    sand = props.get("sand", {}).get("value")
    clay = props.get("clay", {}).get("value")
    result["texture_class"] = _texture_class(sand, clay)
    result["ph"] = props.get("phh2o", {}).get("value")

    cache.set(key, result, ttl_seconds=30 * 86_400)
    return result
