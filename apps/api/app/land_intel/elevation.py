"""Terrain elevation & coarse slope via the free Open-Elevation API (no key).

Samples the field centroid plus four neighbours (~165 m N/S/E/W) to estimate a
rough slope and aspect — useful context for drainage and erosion planning.
Guidance only; degrades gracefully if the service is unavailable.
"""
from __future__ import annotations

import math

import httpx

from app.core import cache

OPEN_ELEVATION_URL = "https://api.open-elevation.com/api/v1/lookup"
_OFFSET_DEG = 0.0015  # ~165 m at India's latitudes


def _slope_class(pct: float | None) -> str | None:
    if pct is None:
        return None
    if pct < 2:
        return "Flat"
    if pct < 5:
        return "Gentle"
    if pct < 10:
        return "Moderate"
    return "Steep"


async def get_elevation(lat: float, lon: float) -> dict:
    key = cache.geo_key("elevation", lat, lon, precision=3)
    cached = await cache.get(key)
    if cached is not None:
        return cached

    result: dict = {"source": "Open-Elevation (SRTM)", "estimate": True}
    # centre, N, S, E, W
    pts = [
        (lat, lon), (lat + _OFFSET_DEG, lon), (lat - _OFFSET_DEG, lon),
        (lat, lon + _OFFSET_DEG), (lat, lon - _OFFSET_DEG),
    ]
    body = {"locations": [{"latitude": a, "longitude": b} for a, b in pts]}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(OPEN_ELEVATION_URL, json=body)
            resp.raise_for_status()
            elevs = [r.get("elevation") for r in resp.json().get("results", [])]
    except (httpx.HTTPError, ValueError, KeyError):
        result["error"] = "Elevation service unavailable; try again shortly"
        return result

    elevs = [e for e in elevs if e is not None]
    if not elevs:
        result["error"] = "No elevation data for this location"
        return result

    result["elevation_m"] = round(elevs[0], 1)  # centre point
    if len(elevs) >= 5:
        # horizontal run between opposite neighbours ~ 2 x offset (m)
        run_lat = 2 * _OFFSET_DEG * 111_132.0
        run_lon = 2 * _OFFSET_DEG * 111_320.0 * math.cos(math.radians(lat))
        ns = abs(elevs[1] - elevs[2]) / run_lat if run_lat else 0.0
        ew = abs(elevs[3] - elevs[4]) / run_lon if run_lon else 0.0
        slope_pct = round(math.hypot(ns, ew) * 100, 1)
        result["slope_pct"] = slope_pct
        result["slope_class"] = _slope_class(slope_pct)
        # aspect: rough facing of the downhill direction
        dz_ns = elevs[2] - elevs[1]  # + means slopes down to the north
        dz_ew = elevs[4] - elevs[3]  # + means slopes down to the east
        if slope_pct >= 1:
            result["aspect"] = _aspect(dz_ns, dz_ew)

    await cache.set(key, result, ttl_seconds=30 * 86_400)
    return result


def _aspect(dz_ns: float, dz_ew: float) -> str:
    ns = "N" if dz_ns > 0 else "S"
    ew = "E" if dz_ew > 0 else "W"
    if abs(dz_ns) > 2 * abs(dz_ew):
        return ns
    if abs(dz_ew) > 2 * abs(dz_ns):
        return ew
    return ns + ew
