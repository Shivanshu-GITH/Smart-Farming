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
import math

import httpx

from app.core import cache
from app.core.config import get_settings
from app.core.geo import centroid_latlon, polygon_from_geojson

_CDSE_TOKEN_URL = ("https://identity.dataspace.copernicus.eu/auth/realms/"
                   "CDSE/protocol/openid-connect/token")


def _sh_urls() -> tuple[str, str]:
    """(oauth token url, statistics url) for the configured Sentinel Hub base.

    The Statistical API path is the same across hosts, but Copernicus Data Space
    (the free tier) issues OAuth tokens from a separate identity server, so the
    token URL is auto-selected (and can be overridden via SENTINELHUB_TOKEN_URL).
    """
    settings = get_settings()
    base = settings.sentinelhub_base_url.rstrip("/")
    token_url = settings.sentinelhub_token_url.strip()
    if not token_url:
        token_url = (_CDSE_TOKEN_URL if "dataspace.copernicus.eu" in base
                     else f"{base}/oauth/token")
    return token_url, f"{base}/api/v1/statistics"

# FLOAT32 keeps NDVI's -1..1 range intact. Pixels the L2A scene
# classification marks as cloud shadow (3), cloud (8, 9), cirrus (10) or snow
# (11) are masked out: they are not a vegetation reading.
_EVALSCRIPT = """//VERSION=3
function setup() {
  return {
    input: [{ bands: ["B04", "B08", "SCL", "dataMask"] }],
    output: [
      { id: "ndvi", bands: 1, sampleType: "FLOAT32" },
      { id: "dataMask", bands: 1 }
    ]
  };
}
function evaluatePixel(s) {
  let clear = [3, 8, 9, 10, 11].indexOf(s.SCL) === -1;
  let ndvi = (s.B08 - s.B04) / (s.B08 + s.B04);
  return { ndvi: [ndvi], dataMask: [s.dataMask && clear ? 1 : 0] };
}
"""

# A pass counts only if at least this share of the field's pixels is clear;
# a mean over a few gaps between clouds is not the field's NDVI.
MIN_CLEAR_FRACTION = 0.3


def _resolution_deg(lat: float, metres: float = 10.0) -> tuple[float, float]:
    """(resx, resy) in degrees for ~`metres` pixels: the request CRS is EPSG:4326,
    whose units are degrees, so a bare 10 would mean 10-degree pixels."""
    return metres / (111_320 * math.cos(math.radians(lat))), metres / 110_574


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
        _sh_urls()[0],
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
    key = f"{cache.geo_key('ndvi2', lat, lon, precision=3)}:{month}"
    cached = await cache.get(key)
    if cached is not None:
        return cached

    end = dt.date.today()
    start = end - dt.timedelta(days=90)
    resx, resy = _resolution_deg(lat)
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
            "resx": resx,
            "resy": resy,
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
                _sh_urls()[1], json=body,
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


async def get_ndvi_series(geometry: dict, months: int = 6) -> dict:
    """NDVI trend over the last `months` (one point per ~15-day Sentinel-2 bucket).

    Enables time-series field monitoring — spotting decline/stress over a season.
    """
    settings = get_settings()
    polygon = polygon_from_geojson(geometry)
    lat, lon = centroid_latlon(polygon)
    months = max(1, min(months, 12))

    result: dict = {"source": "Sentinel-2 L2A (Sentinel Hub)", "estimate": True,
                    "configured": bool(settings.sentinelhub_client_id
                                       and settings.sentinelhub_client_secret),
                    "series": []}
    if not result["configured"]:
        result["note"] = "NDVI needs Sentinel Hub credentials."
        return result

    key = f"{cache.geo_key('ndvi2-series', lat, lon, precision=3)}:{months}:{dt.date.today():%Y-%m}"
    cached = await cache.get(key)
    if cached is not None:
        return cached

    end = dt.date.today()
    start = end - dt.timedelta(days=months * 30)
    resx, resy = _resolution_deg(lat)
    body = {
        "input": {
            "bounds": {"geometry": geometry,
                       "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"}},
            "data": [{"type": "sentinel-2-l2a", "dataFilter": {"maxCloudCoverage": 40}}],
        },
        "aggregation": {
            "timeRange": {"from": f"{start.isoformat()}T00:00:00Z",
                          "to": f"{end.isoformat()}T23:59:59Z"},
            "aggregationInterval": {"of": "P15D"},
            "evalscript": _EVALSCRIPT, "resx": resx, "resy": resy,
        },
        "calculations": {"ndvi": {"statistics": {"default": {}}}},
    }
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            token = await _get_token(client, settings.sentinelhub_client_id,
                                     settings.sentinelhub_client_secret)
            if not token:
                result["error"] = "Could not authenticate with Sentinel Hub"
                return result
            resp = await client.post(_sh_urls()[1], json=body,
                                     headers={"Authorization": f"Bearer {token}"})
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError, KeyError):
        result["error"] = "NDVI service unavailable; try again shortly"
        return result

    series = []
    for item in data.get("data", []):
        stats = _stats(item)
        if _usable(stats):
            series.append({"date": item.get("interval", {}).get("from", "")[:10],
                           "mean": round(stats["mean"], 3)})
    result["series"] = series
    if len(series) >= 2:
        result["trend"] = "improving" if series[-1]["mean"] > series[0]["mean"] else "declining"
    await cache.set(key, result, ttl_seconds=3 * 86_400)
    return result


def _stats(item: dict) -> dict:
    return item.get("outputs", {}).get("ndvi", {}).get("bands", {}).get("B0", {}).get("stats", {})


def _usable(stats: dict) -> bool:
    """Numeric mean (all-nodata intervals report "NaN") over a mostly clear field."""
    if not isinstance(stats.get("mean"), (int, float)):
        return False
    samples = stats.get("sampleCount") or 0
    clear = samples - (stats.get("noDataCount") or 0)
    return samples > 0 and clear / samples >= MIN_CLEAR_FRACTION


def _latest_valid(intervals: list) -> tuple[str, dict] | None:
    """Pick the most recent interval that has valid NDVI stats."""
    for item in reversed(intervals):
        stats = _stats(item)
        if _usable(stats):
            return item.get("interval", {}).get("from", "")[:10], stats
    return None
