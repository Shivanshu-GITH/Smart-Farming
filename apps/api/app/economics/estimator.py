"""Cost / revenue / profit estimator.

For each crop it builds a transparent cost breakdown (seed + inputs + labour)
and a revenue range (yield range x price), then a margin range. For a multi-layer
stack the crops share the same land, so costs and revenue are summed — that
higher revenue-per-acre at shared land cost is exactly the multi-layer value.

All figures are planning estimates and clearly flagged as such.
"""
from __future__ import annotations

from app.agronomy.catalogue import get_crop
from app.core.geo import SQM_PER_HECTARE

from .catalogue import get_economics


def _crop_economics(crop_id: str, ha: float, price: float | None) -> dict | None:
    crop = get_crop(crop_id)
    econ = get_economics(crop_id)
    if crop is None or econ is None:
        return None

    seed_rate = crop.get("seed_rate_kg_per_ha", 0) or 0
    seed_cost = round(seed_rate * econ["seed_cost_per_kg"] * ha)
    input_cost = round(econ["input_cost_per_ha"] * ha)
    labour_cost = round(econ["labour_cost_per_ha"] * ha)
    total_cost = seed_cost + input_cost + labour_cost

    unit_price = price if price is not None else econ["price_per_kg"]
    y_lo, y_hi = econ["yield_kg_per_ha"]
    yield_lo, yield_hi = round(y_lo * ha), round(y_hi * ha)
    rev_lo, rev_hi = round(yield_lo * unit_price), round(yield_hi * unit_price)

    return {
        "crop_id": crop_id,
        "name": crop["name"],
        "layer": crop["layer"],
        "cost": {
            "seed": seed_cost,
            "inputs": input_cost,
            "labour": labour_cost,
            "total": total_cost,
        },
        "yield_kg": [yield_lo, yield_hi],
        "price_per_kg": unit_price,
        "price_source": "mandi" if price is not None else "estimate",
        "revenue": [rev_lo, rev_hi],
        "margin": [rev_lo - total_cost, rev_hi - total_cost],
    }


def estimate(crop_ids: list[str], area_m2: float,
             prices: dict[str, float] | None = None) -> dict:
    ha = area_m2 / SQM_PER_HECTARE
    prices = prices or {}
    rows: list[dict] = []
    for cid in crop_ids:
        row = _crop_economics(cid, ha, prices.get(cid))
        if row is not None:
            rows.append(row)

    totals = {
        "cost": sum(r["cost"]["total"] for r in rows),
        "revenue": [sum(r["revenue"][0] for r in rows),
                    sum(r["revenue"][1] for r in rows)],
        "margin": [sum(r["margin"][0] for r in rows),
                   sum(r["margin"][1] for r in rows)],
    }
    return {
        "area_hectares": round(ha, 4),
        "currency": "INR",
        "crops": rows,
        "totals": totals,
        "layers": len({r["layer"] for r in rows}),
        "disclaimer": "Rough planning estimates only. Validate costs, yields and "
                      "prices locally with an agronomist/extension officer before "
                      "any financial decision.",
    }
