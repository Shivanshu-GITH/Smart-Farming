"""Live mandi (market) prices via data.gov.in's Agmarknet daily-price resource.

Falls back to the curated farm-gate price in economics.json when no API key is
configured or no market record is found — so the estimator always has a price.
Prices from Agmarknet are per quintal (100 kg); we convert to per kg.
"""
from __future__ import annotations

import httpx

from app.core import cache
from app.core.config import get_settings

from .catalogue import get_economics

# "Current Daily Price of Various Commodities from Various Markets (Mandi)"
RESOURCE = "9ef84268-d588-465a-a308-a864a43d0070"
DATA_GOV_URL = f"https://api.data.gov.in/resource/{RESOURCE}"


async def get_price(crop_id: str, state: str | None = None) -> dict:
    """Return {price_per_kg, source, market?, district?, date?} for a crop."""
    econ = get_economics(crop_id)
    fallback = {
        "crop_id": crop_id,
        "price_per_kg": econ["price_per_kg"] if econ else None,
        "source": "estimate",
    }
    settings = get_settings()
    if not settings.data_gov_api_key or econ is None:
        return fallback

    commodity = econ.get("agmarknet_commodity")
    if not commodity:
        return fallback

    key = f"mandi:{crop_id}:{(state or 'all').lower()}"
    cached = await cache.get(key)
    if cached is not None:
        return cached

    params = {
        "api-key": settings.data_gov_api_key,
        "format": "json",
        "limit": "50",
        "filters[commodity]": commodity,
    }
    if state:
        params["filters[state]"] = state

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(DATA_GOV_URL, params=params)
            resp.raise_for_status()
            records = resp.json().get("records", [])
    except (httpx.HTTPError, ValueError):
        return fallback

    prices = []
    for r in records:
        try:
            prices.append(float(r.get("modal_price")))
        except (TypeError, ValueError):
            continue
    if not prices:
        return fallback

    latest = records[0]
    result = {
        "crop_id": crop_id,
        # average modal price across markets, quintal -> kg
        "price_per_kg": round(sum(prices) / len(prices) / 100.0, 2),
        "source": "mandi",
        "market": latest.get("market"),
        "district": latest.get("district"),
        "state": latest.get("state"),
        "date": latest.get("arrival_date"),
        "samples": len(prices),
    }
    await cache.set(key, result, ttl_seconds=86_400)
    return result


async def get_prices(crop_ids: list[str], state: str | None = None) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for cid in crop_ids:
        out[cid] = await get_price(cid, state)
    return out
