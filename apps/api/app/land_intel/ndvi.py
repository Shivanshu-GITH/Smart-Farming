"""Vegetation index (NDVI) over a field polygon via Sentinel Hub.

NDVI needs an *area* (not a point) and a recent cloud-low Sentinel-2 pass, so
this takes the drawn polygon and returns the mean NDVI of the most recent
usable acquisition plus a coarse vigour label.

Requires Sentinel Hub OAuth credentials (SENTINELHUB_CLIENT_ID/SECRET). Without
them the endpoint degrades gracefully (``configured: false``) exactly like the
other providers, so the app stays runnable out of the box.
"""
from __future__ import annotations

import datetime as dt

import httpx

from app.core import cache
from app.core.config import get_settings
from app.core.geo import centroid_latlon, polygon_from_geojson

OAUTH_URL = "https://services.sentinel-hub.com/oauth/token"
STATS_URL = "https://services.sentinel-hub.com/api/v1/statistics"

_EVALSCRIPT = """//VERSION=3
function setup() {
  return {
    input: [{ bands: ["B04", "B08", "dataMask"] }],
    output: [
      { id: "ndvi", bands: 1 },
      { id: "dataMask", bands: 1 }
    ]
  };
}
function evaluatePixel(s) {
  let ndvi = (s.B08 - s.B04) / (s.B08 + s.B04);
  return { ndvi: [ndvi], dataMask: [s.dataMask] };
}
"""


def _vigour(mean: float | None) -> str | None:
    if mean is None:
        return None
    if mean < 0.2:
        return "Bare / very sparse (soil, water or built-up)"
    if mean < 0.4:
        return "Sparse / early-stage vegetation"
    if mean < 0.6:
        return "Moderate, developing canopy"
    return "Dense, vigorous canopy"


async def _get_token(client: httpx.AsyncClient, cid: str, secret: str) -> str | None:
    cached = await cache.get("sh:token")
    if cached:
        return cached
    resp = await client.post(
        OAUTH_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": cid,
            "client_secret": secret,
        },
    )
    resp.raise_for_status()
    payload = resp.json()
    token = payload.get("access_token")
    if token:
        # Tokens live ~1h; cache a little under that.
        await cache.set("sh:token", token, ttl_seconds=int(payload.get("expires_in", 3600)) - 120)
    return token


async def get_ndvi(geometry: dict) -> dict:
    settings = get_settings()
    polygon = polygon_from_geojson(geometry)  # validates the polygon
    lat, lon = centroid_latlon(polygon)

    result: dict = {"source": "Sentinel-2 L2A (Sentinel Hub)", "estimate": True,
                    "configured": bool(settings.sentinelhub_client_id
                                       and settings.sentinelhub_client_secret)}

    if not result["configured"]:
        result["note"] = ("NDVI needs Sentinel Hub credentials "
                          "(SENTINELHUB_CLIENT_ID / SECRET).")
        return result

    # NDVI shifts over the season — cache by centroid + current month.
    month = dt.date.today().strftime("%Y-%m")
    key = f"{cache.geo_key('ndvi', lat, lon, precision=3)}:{month}"
    cached = await cache.get(key)
    if cached is not None:
        return cached

    end = dt.date.today()
    start = end - dt.timedelta(days=90)
    body = {
        "input": {
            "bounds": {
                "geometry": geometry,
                "properties": {
                    "crs": "http://www.opengis.net/def/crs/EPSG/0/4326"
                },
            },
            "data": [{
                "type": "sentinel-2-l2a",
                "dataFilter": {"maxCloudCoverage": 40},
            }],
        },
        "aggregation": {
            "timeRange": {
                "from": f"{start.isoformat()}T00:00:00Z",
                "to": f"{end.isoformat()}T23:59:59Z",
            },
            "aggregationInterval": {"of": "P15D"},
            "evalscript": _EVALSCRIPT,
            "resx": 10,
            "resy": 10,
        },
        "calculations": {"ndvi": {"statistics": {"default": {}}}},
    }

    try:
        async with httpx.AsyncClient(timeout=40) as client:
            token = await _get_token(
                client, settings.sentinelhub_client_id,
                settings.sentinelhub_client_secret,
            )
            if not token:
                result["error"] = "Could not authenticate with Sentinel Hub"
                return result
            resp = await client.post(
                STATS_URL, json=body,
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            data = resp.json()

        latest = _latest_valid(data.get("data", []))
        if latest is None:
            result["error"] = "No cloud-free Sentinel-2 pass in the last 90 days"
            return result

        interval, stats = latest
        result.update({
            "date": interval,
            "mean": round(stats.get("mean"), 3) if stats.get("mean") is not None else None,
            "min": round(stats.get("min"), 3) if stats.get("min") is not None else None,
            "max": round(stats.get("max"), 3) if stats.get("max") is not None else None,
        })
        result["vigour"] = _vigour(result["mean"])
    except (httpx.HTTPError, ValueError, KeyError):
        result["error"] = "NDVI service unavailable; try again shortly"
        return result

    await cache.set(key, result, ttl_seconds=7 * 86_400)
    return result


def _latest_valid(intervals: list) -> tuple[str, dict] | None:
    """Pick the most recent interval that has valid NDVI stats."""
    for item in reversed(intervals):
        outputs = item.get("outputs", {}).get("ndvi", {})
        bands = outputs.get("bands", {})
        stats = bands.get("B0", {}).get("stats", {})
        # sampleCount==0 or all-nodata intervals report no usable mean
        if stats.get("mean") is not None and stats.get("sampleCount", 1) != 0:
            return item.get("interval", {}).get("from", "")[:10], stats
    return None
