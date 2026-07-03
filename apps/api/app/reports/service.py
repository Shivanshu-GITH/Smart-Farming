"""Gathers everything needed for a field report, then renders a PDF.

Recomputes server-side from the geometry + chosen crops so a saved/shared link
produces the same document without trusting client-sent numbers.
"""
from __future__ import annotations

import asyncio

from app.agronomy.plan import build_plan
from app.economics import mandi
from app.economics.estimator import estimate
from app.fields.service import summarize_field
from app.land_intel.ndvi import get_ndvi
from app.land_intel.soil import get_soil
from app.land_intel.weather import get_climate
from app.layout.engine import generate_layout

from .pdf import build_report_pdf


async def generate_report(geometry: dict, crop_ids: list[str]) -> bytes:
    summary = await summarize_field(geometry)
    lat = summary["centroid"]["lat"]
    lon = summary["centroid"]["lon"]

    soil, climate, ndvi = await asyncio.gather(
        get_soil(lat, lon),
        get_climate(lat, lon),
        get_ndvi(geometry),
    )

    area_m2 = summary["area"]["square_meters"]
    plans = []
    for cid in crop_ids:
        try:
            plans.append(build_plan(cid, area_m2))
        except ValueError:
            continue  # unknown crop id — skip rather than fail the whole report

    layout = generate_layout(geometry, crop_ids) if crop_ids else None

    economics = None
    if crop_ids:
        state = (summary.get("region") or {}).get("state")
        price_info = await mandi.get_prices(crop_ids, state)
        prices = {
            cid: info["price_per_kg"]
            for cid, info in price_info.items()
            if info.get("source") == "mandi" and info.get("price_per_kg") is not None
        }
        economics = estimate(crop_ids, area_m2, prices)

    context = {
        "summary": summary,
        "soil": soil,
        "climate": climate,
        "ndvi": ndvi,
        "plans": plans,
        "layout": layout,
        "economics": economics,
        "ring": geometry.get("coordinates", [[]])[0],
    }
    # reportlab is synchronous/CPU-bound — run it off the event loop.
    return await asyncio.to_thread(build_report_pdf, context)
