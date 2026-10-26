"""Climate summary via Open-Meteo (free, no API key).

Pulls a recent-normals snapshot and derives a coarse Indian agro-climatic
descriptor used by the crop recommender (season + temperature + rainfall band).
"""
from __future__ import annotations

import asyncio
import datetime as dt

import httpx

from app.core import cache

# 10-year climate normals from NASA POWER — the same source and period the crop
# recommender was trained on (research/scripts/s03_climate.py), so it is served
# normals rather than one year's weather.
POWER_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
NORMALS_START, NORMALS_END = "20110101", "20201231"
_POWER_MISSING = -900.0

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
# Same daily variables and full start/end range as the archive host; used when
# archive-api is unreachable (it intermittently fails the TLS handshake).
HISTORICAL_FORECAST_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"


# Growing-season months. The crop database's temperature ranges describe the
# growing season, so crops are judged on these, not on the annual average.
SEASON_MONTHS = {"kharif": (6, 7, 8, 9, 10), "rabi": (11, 12, 1, 2, 3), "zaid": (4, 5)}


def current_indian_season(today: dt.date | None = None) -> str:
    """Kharif (Jun-Oct), Rabi (Nov-Mar), Zaid (Apr-May)."""
    m = (today or dt.date.today()).month
    if 6 <= m <= 10:
        return "Kharif (monsoon)"
    if m in (11, 12, 1, 2, 3):
        return "Rabi (winter)"
    return "Zaid (summer)"


def seasonal_means(dates: list[str], tmean: list, tmax: list, tmin: list) -> dict:
    """Mean daily temperature per growing season.

    Uses the daily mean when the provider returns it, else (max + min) / 2.
    """
    by_season: dict[str, list[float]] = {s: [] for s in SEASON_MONTHS}
    for i, d in enumerate(dates):
        t = tmean[i] if i < len(tmean) else None
        if t is None and i < len(tmax) and i < len(tmin) \
                and tmax[i] is not None and tmin[i] is not None:
            t = (tmax[i] + tmin[i]) / 2
        if t is None:
            continue
        month = int(d[5:7])
        for s, months in SEASON_MONTHS.items():
            if month in months:
                by_season[s].append(t)
    all_t = [t for v in by_season.values() for t in v]
    out = {f"tmean_{s}_c": round(sum(v) / len(v), 1) if v else None
           for s, v in by_season.items()}
    out["temp_mean_avg_c"] = round(sum(all_t) / len(all_t), 1) if all_t else None
    return out


def normals_from_power(param: dict) -> dict:
    """Annual rainfall normal + seasonal mean temperatures from POWER daily data."""
    dates = sorted(param.get("T2M", {}))
    tmean = [param["T2M"][d] for d in dates]
    tmean = [None if t is None or t <= _POWER_MISSING else t for t in tmean]
    iso = [f"{d[:4]}-{d[4:6]}-{d[6:]}" for d in dates]
    out = seasonal_means(iso, tmean, [], [])
    rain = param.get("PRECTOTCORR", {})
    years = {d[:4] for d in rain}
    total = sum(v for v in rain.values() if v is not None and v > _POWER_MISSING)
    out["annual_rainfall_normal_mm"] = round(total / len(years), 1) if years else None
    return out


async def get_climate_normals(lat: float, lon: float) -> dict | None:
    """10-year normals at a point (cached for 30 days — they don't change)."""
    key = cache.geo_key("normals", lat, lon, precision=2)
    cached = await cache.get(key)
    if cached is not None:
        return cached
    params = {"parameters": "T2M,PRECTOTCORR", "community": "AG", "format": "JSON",
              "latitude": round(lat, 4), "longitude": round(lon, 4),
              "start": NORMALS_START, "end": NORMALS_END}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(POWER_URL, params=params)
            resp.raise_for_status()
            out = normals_from_power(resp.json()["properties"]["parameter"])
    except (httpx.HTTPError, ValueError, KeyError, ZeroDivisionError):
        return None
    await cache.set(key, out, ttl_seconds=30 * 86_400)
    return out


async def get_climate(lat: float, lon: float) -> dict:
    # "climate3": entries now carry seasonal normals; don't serve older ones.
    key = cache.geo_key("climate3", lat, lon, precision=2)
    cached = await cache.get(key)
    if cached is not None:
        return cached
    normals_task = asyncio.create_task(get_climate_normals(lat, lon))

    end = dt.date.today() - dt.timedelta(days=5)
    start = end - dt.timedelta(days=365)
    result: dict = {"source": "Open-Meteo", "season": current_indian_season()}

    try:
        params = {
            "latitude": lat, "longitude": lon,
            "start_date": start.isoformat(), "end_date": end.isoformat(),
            "daily": "temperature_2m_max,temperature_2m_min,temperature_2m_mean,precipitation_sum",
            "timezone": "auto",
        }
        daily = await _fetch_daily(params)

        result.update(seasonal_means(daily.get("time", []),
                                     daily.get("temperature_2m_mean", []),
                                     daily.get("temperature_2m_max", []),
                                     daily.get("temperature_2m_min", [])))
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

    # Normals override the one-year seasonal means (which remain the fallback).
    normals = await normals_task
    if normals:
        result.update({k: v for k, v in normals.items() if v is not None})
        result["normals_source"] = "NASA POWER 2011-2020"

    if "error" not in result:
        await cache.set(key, result, ttl_seconds=7 * 86_400)
    return result


async def _fetch_daily(params: dict) -> dict:
    """Daily series from the archive host, falling back to historical-forecast.

    Both serve the same variables over the same explicit date range, so the
    derived rainfall/temperature figures mean the same thing either way.
    """
    last_error: httpx.HTTPError | None = None
    async with httpx.AsyncClient(timeout=20) as client:
        for url in (ARCHIVE_URL, HISTORICAL_FORECAST_URL):
            try:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                return resp.json().get("daily", {})
            except httpx.HTTPError as exc:
                last_error = exc
    raise last_error  # type: ignore[misc]


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
