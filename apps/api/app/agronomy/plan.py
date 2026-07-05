"""Turns a crop choice + field area into a concrete agronomic plan:
planting material (seed / seedlings / suckers / rhizomes / setts / tubers),
fertilizer totals, plant count and a stage-based crop calendar.

When a farming ``system`` is given, quantities are computed on the *planting*
area — gross land minus the share reserved for bunds, walking/inspection paths
and irrigation lines (see systems.json usable_area_fraction).
"""
from __future__ import annotations

import datetime as dt
import math

from app.core.geo import SQM_PER_HECTARE

from .catalogue import get_crop, propagation, usable_fraction

# Extra planting material over the theoretical count, for nursery losses and
# gap filling — standard practice.
_MATERIAL_BUFFER = 1.05

_MATERIAL_LABELS = {
    "seed": "seed",
    "seedling": "seedlings (nursery-raised)",
    "sucker": "suckers / tissue-culture plantlets",
    "rhizome": "seed rhizomes",
    "sett": "three-bud setts",
    "tuber": "seed tubers",
}


def plants_per_hectare(crop: dict) -> int:
    row = crop["spacing_cm"]["row"] / 100.0
    plant = crop["spacing_cm"]["plant"] / 100.0
    if row <= 0 or plant <= 0:
        return 0
    return int(SQM_PER_HECTARE / (row * plant))


def _planting_material(crop: dict, plant_count: int, seed_qty: float) -> dict:
    """What the farmer actually has to buy/raise, in the right unit."""
    prop = propagation(crop)
    if prop in ("seedling", "sucker"):
        return {
            "type": prop,
            "label": _MATERIAL_LABELS[prop],
            "unit": "plants",
            "quantity": int(math.ceil(plant_count * _MATERIAL_BUFFER)),
            "note": "Includes ~5% extra for nursery losses and gap filling."
                    + (" Nursery seed requirement shown separately."
                       if crop.get("seed_rate_kg_per_ha") else ""),
        }
    if prop in ("rhizome", "sett", "tuber"):
        return {
            "type": prop,
            "label": _MATERIAL_LABELS[prop],
            "unit": "kg",
            "quantity": seed_qty,
            "note": crop.get("plants_note"),
        }
    return {
        "type": "seed",
        "label": _MATERIAL_LABELS["seed"],
        "unit": "kg",
        "quantity": seed_qty,
        "note": crop.get("plants_note"),
    }


def build_plan(crop_id: str, area_m2: float, start: dt.date | None = None,
               system: str | None = None) -> dict:
    crop = get_crop(crop_id)
    if crop is None:
        raise ValueError(f"Unknown crop '{crop_id}'")

    gross_ha = area_m2 / SQM_PER_HECTARE
    fraction = usable_fraction(system)
    planting_ha = gross_ha * fraction

    pph = plants_per_hectare(crop)
    plant_count = int(pph * planting_ha)

    seed_rate = crop.get("seed_rate_kg_per_ha", 0) or 0
    seed_qty = round(seed_rate * planting_ha, 2)

    npk = crop["fertilizer_npk_kg_ha"]
    fert_total = {k: round(v * planting_ha, 1) for k, v in npk.items()}

    return {
        "crop": {"id": crop["id"], "name": crop["name"], "layer": crop["layer"]},
        "system": system,
        "area_hectares": round(gross_ha, 4),
        "planting_area_hectares": round(planting_ha, 4),
        "usable_fraction": fraction,
        "spacing_cm": crop["spacing_cm"],
        "plants": {
            "per_hectare": pph,
            "total_estimate": plant_count,
            "note": crop.get("plants_note"),
        },
        "planting_material": _planting_material(crop, plant_count, seed_qty),
        "seed": {
            "rate_kg_per_ha": seed_rate,
            "quantity_kg": seed_qty,
        },
        "fertilizer": {
            "npk_kg_per_ha": npk,
            "total_kg": fert_total,
            "schedule": _fertilizer_schedule(npk, fert_total),
        },
        "calendar": _calendar(crop, start or dt.date.today()),
        "best_practices": _best_practices(crop),
        "disclaimer": "Estimates from a curated knowledge base; verify with a "
                      "local agronomist and a soil test before field use.",
    }


def _fertilizer_schedule(npk: dict, total: dict) -> list[dict]:
    """Split: full P + half K basal; N + remaining K as two top-dressings."""
    return [
        {"stage": "Basal (at sowing)",
         "N_kg": round(total["N"] * 0.25, 1),
         "P_kg": total["P"],
         "K_kg": round(total["K"] * 0.5, 1)},
        {"stage": "Top-dress 1 (~30 days)",
         "N_kg": round(total["N"] * 0.4, 1),
         "P_kg": 0.0,
         "K_kg": round(total["K"] * 0.25, 1)},
        {"stage": "Top-dress 2 (~60 days)",
         "N_kg": round(total["N"] * 0.35, 1),
         "P_kg": 0.0,
         "K_kg": round(total["K"] * 0.25, 1)},
    ]


def _calendar(crop: dict, start: dt.date) -> list[dict]:
    dur = crop["duration_days"]
    stages = [
        ("Sowing / planting", 0.0),
        ("Establishment & weeding", 0.15),
        ("Vegetative growth / 1st top-dress", 0.30),
        ("Flowering / 2nd top-dress", 0.55),
        ("Fruiting / maturation", 0.80),
        ("Harvest", 1.0),
    ]
    out = []
    for label, frac in stages:
        day = int(dur * frac)
        out.append({
            "stage": label,
            "day": day,
            "date": (start + dt.timedelta(days=day)).isoformat(),
        })
    return out


def _best_practices(crop: dict) -> list[str]:
    tips = [crop.get("notes", "")]
    comp = crop.get("companions") or []
    if comp:
        tips.append("Good companions for intercropping: " + ", ".join(comp) + ".")
    anta = crop.get("antagonists") or []
    if anta:
        tips.append("Avoid planting next to: " + ", ".join(anta) + ".")
    tips.append("Position taller crops on the north side so shorter crops still "
                "get sunlight.")
    return [t for t in tips if t]
