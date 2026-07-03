"""Climate summary via Open-Meteo (free, no API key).

Pulls a recent-normals snapshot and derives a coarse Indian agro-climatic
descriptor used by the crop recommender (season + temperature + rainfall band).
"""
from __future__ import annotations

import datetime as dt

import httpx

from app.core import cache

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


def current_indian_season(today: dt.date | None = None) -> str:
    """Kharif (Jun-Oct), Rabi (Nov-Mar), Zaid (Apr-May)."""
    m = (today or dt.date.today()).month
    if 6 <= m <= 10:
        return "Kharif (monsoon)"
    if m in (11, 12, 1, 2, 3):
        return "Rabi (winter)"
    return "Zaid (summer)"


async def get_climate(lat: float, lon: float) -> dict:
    key = cache.geo_key("climate", lat, lon, precision=2)
    cached = await cache.get(key)
    if cached is not None:
        return cached

    end = dt.date.today() - dt.timedelta(days=5)
    start = end - dt.timedelta(days=365)
    result: dict = {"source": "Open-Meteo", "season": current_indian_season()}

    try:
        params = {
            "latitude": lat, "longitude": lon,
            "start_date": start.isoformat(), "end_date": end.isoformat(),
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
            "timezone": "auto",
        }
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(ARCHIVE_URL, params=params)
            resp.raise_for_status()
            daily = resp.json().get("daily", {})

        tmax = [t for t in daily.get("temperature_2m_max", []) if t is not None]
        tmin = [t for t in daily.get("temperature_2m_min", []) if t is not None]
        rain = [r for r in daily.get("precipitation_sum", []) if r is not None]

        result.update({
            "annual_rainfall_mm": round(sum(rain), 1) if rain else None,
            "temp_max_avg_c": round(sum(tmax) / len(tmax), 1) if tmax else None,
            "temp_min_avg_c": round(sum(tmin) / len(tmin), 1) if tmin else None,
            "temp_max_record_c": round(max(tmax), 1) if tmax else None,
            "temp_min_record_c": round(min(tmin), 1) if tmin else None,
        })
        result["rainfall_band"] = _rainfall_band(result.get("annual_rainfall_mm"))
    except (httpx.HTTPError, ValueError, ZeroDivisionError):
        result["error"] = "Climate data unavailable; try again shortly"

    if "error" not in result:
        await cache.set(key, result, ttl_seconds=7 * 86_400)
    return result


def _rainfall_band(mm: float | None) -> str | None:
    if mm is None:
        return None
    if mm < 500:
        return "Low (arid/semi-arid)"
    if mm < 1000:
        return "Moderate"
    if mm < 2000:
        return "High"
    return "Very high (humid)"
