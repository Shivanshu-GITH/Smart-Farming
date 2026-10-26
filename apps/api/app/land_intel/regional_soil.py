"""Curated regional soil estimate for India.

SoilGrids (the primary source) has gaps and rate limits, and returns nothing for
a meaningful share of Indian points. When it does, the pH and texture that drive
crop scoring go missing and every crop scores the same — so the recommendation
stops depending on where the farmer actually is.

This module fills that gap with the dominant soil group of the point's *state*,
from India's well-documented soil geography (alluvial Indo-Gangetic plains, black
cotton / regur of the Deccan, red & laterite of the peninsula, Himalayan forest
soils, arid west). It is a planning-grade regional estimate, never a lab test,
and it is only used to fill values SoilGrids did not provide.

The point -> state lookup reuses the bundled district bounding boxes, so it needs
no network.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

# apps/api/app/land_intel/regional_soil.py -> repo root is 4 levels up.
_REPO_ROOT = Path(__file__).resolve().parents[4]
_BBOXES_DB = _REPO_ROOT / "packages" / "india-geo" / "district-bboxes.json"

# Dominant soil group per state/UT: representative pH and a texture class drawn
# from the crop database's own vocabulary ("Loam / Silt loam", "Sandy loam",
# "Clay loam", "Clay", "Sandy"), plus a short human label. Values are typical
# surface-soil figures from Indian soil surveys (ICAR / NBSS&LUP soil regions),
# chosen to be defensible for the state as a whole, not any single field.
STATE_SOIL: dict[str, dict] = {
    # --- Indo-Gangetic & valley alluvium (deep loam, neutral to alkaline) ---
    "Punjab": {"ph": 7.8, "texture_class": "Loam / Silt loam", "region": "Indo-Gangetic alluvial plain"},
    "Haryana": {"ph": 7.9, "texture_class": "Loam / Silt loam", "region": "Indo-Gangetic alluvial plain"},
    "Delhi": {"ph": 7.6, "texture_class": "Loam / Silt loam", "region": "Indo-Gangetic alluvial plain"},
    "Chandigarh": {"ph": 7.5, "texture_class": "Loam / Silt loam", "region": "Indo-Gangetic alluvial plain"},
    "Uttar Pradesh": {"ph": 7.5, "texture_class": "Loam / Silt loam", "region": "Indo-Gangetic alluvial plain"},
    "Bihar": {"ph": 7.0, "texture_class": "Loam / Silt loam", "region": "Gangetic alluvial plain"},
    "West Bengal": {"ph": 6.5, "texture_class": "Loam / Silt loam", "region": "Gangetic alluvial & delta"},
    "Assam": {"ph": 5.5, "texture_class": "Sandy loam", "region": "Brahmaputra valley alluvium (acidic)"},
    # --- Black cotton / regur (heavy clay, alkaline) ---
    "Maharashtra": {"ph": 8.0, "texture_class": "Clay loam", "region": "Deccan black cotton (regur)"},
    "Gujarat": {"ph": 8.0, "texture_class": "Clay loam", "region": "black cotton & coastal alluvium"},
    "Madhya Pradesh": {"ph": 7.6, "texture_class": "Clay loam", "region": "Malwa black & red soils"},
    "Dadra and Nagar Haveli and Daman and Diu": {"ph": 7.2, "texture_class": "Clay loam", "region": "coastal black & alluvium"},
    # --- Red, red-yellow & rice-bowl soils (light, slightly acidic to neutral) ---
    "Karnataka": {"ph": 6.3, "texture_class": "Sandy loam", "region": "Deccan red sandy loam"},
    "Telangana": {"ph": 7.0, "texture_class": "Sandy loam", "region": "red sandy & black soils"},
    "Andhra Pradesh": {"ph": 6.8, "texture_class": "Sandy loam", "region": "red sandy & coastal alluvium"},
    "Tamil Nadu": {"ph": 6.8, "texture_class": "Sandy loam", "region": "red loam & coastal alluvium"},
    "Chhattisgarh": {"ph": 6.3, "texture_class": "Clay loam", "region": "red-yellow & rice-bowl clays"},
    "Odisha": {"ph": 5.8, "texture_class": "Sandy loam", "region": "red & laterite (acidic)"},
    "Jharkhand": {"ph": 5.6, "texture_class": "Sandy loam", "region": "red & laterite (acidic)"},
    # --- Laterite & coastal (acidic, leached) ---
    "Kerala": {"ph": 5.2, "texture_class": "Sandy loam", "region": "laterite (strongly acidic)"},
    "Goa": {"ph": 5.5, "texture_class": "Sandy loam", "region": "coastal laterite (acidic)"},
    "Puducherry": {"ph": 6.8, "texture_class": "Sandy loam", "region": "coastal red & alluvium"},
    "Andaman and Nicobar Islands": {"ph": 5.5, "texture_class": "Sandy loam", "region": "island forest & laterite"},
    # --- North-eastern hills (acidic forest soils) ---
    "Arunachal Pradesh": {"ph": 5.3, "texture_class": "Sandy loam", "region": "eastern Himalayan forest (acidic)"},
    "Nagaland": {"ph": 5.3, "texture_class": "Sandy loam", "region": "hill forest (acidic)"},
    "Manipur": {"ph": 5.5, "texture_class": "Loam / Silt loam", "region": "hill & valley (acidic)"},
    "Mizoram": {"ph": 5.2, "texture_class": "Sandy loam", "region": "hill forest (acidic)"},
    "Meghalaya": {"ph": 5.0, "texture_class": "Sandy loam", "region": "Shillong plateau laterite (acidic)"},
    "Tripura": {"ph": 5.5, "texture_class": "Sandy loam", "region": "hill & valley (acidic)"},
    "Sikkim": {"ph": 5.5, "texture_class": "Loam / Silt loam", "region": "Himalayan mountain (acidic)"},
    # --- Himalayan mountain / forest ---
    "Himachal Pradesh": {"ph": 6.0, "texture_class": "Loam / Silt loam", "region": "Himalayan mountain/forest"},
    "Uttarakhand": {"ph": 6.2, "texture_class": "Loam / Silt loam", "region": "Himalayan & terai"},
    "Jammu and Kashmir": {"ph": 7.0, "texture_class": "Loam / Silt loam", "region": "Himalayan mountain valley"},
    "Ladakh": {"ph": 7.8, "texture_class": "Sandy loam", "region": "cold desert (alkaline)"},
    # --- Arid west ---
    "Rajasthan": {"ph": 7.8, "texture_class": "Sandy loam", "region": "arid & alluvial (light, alkaline)"},
    "Lakshadweep": {"ph": 7.8, "texture_class": "Sandy", "region": "coral sandy (alkaline)"},
}


@lru_cache(maxsize=1)
def _district_index() -> list[tuple[str, float, float, float, float, float]]:
    """(state, south, north, west, east, area) for every bundled district bbox."""
    if not _BBOXES_DB.exists():
        return []
    with _BBOXES_DB.open(encoding="utf-8") as fh:
        data = json.load(fh)
    index: list[tuple[str, float, float, float, float, float]] = []
    for state, districts in data.get("states", {}).items():
        for bbox in districts.values():
            if not bbox or len(bbox) != 4:
                continue
            s, n, w, e = bbox  # [south, north, west, east]
            index.append((state, s, n, w, e, (n - s) * (e - w)))
    return index


def state_for_point(lat: float, lon: float) -> str | None:
    """Resolve a point to an Indian state, offline, via district bounding boxes.

    Boxes overlap, so the smallest box containing the point wins (it is the most
    specific). If no box contains it (just offshore, or on a border), fall back
    to the state whose nearest district-box centre is closest — but only within
    ~3 degrees (~330 km), so a point well outside India stays unresolved.
    """
    index = _district_index()
    if not index:
        return None

    _NEAR_LIMIT2 = 3.0 ** 2  # squared-degree cap for the offshore/border fallback

    best_state: str | None = None
    best_area = float("inf")
    nearest_state: str | None = None
    nearest_d2 = float("inf")
    for state, s, n, w, e, area in index:
        if s <= lat <= n and w <= lon <= e and area < best_area:
            best_area, best_state = area, state
        cy, cx = (s + n) / 2, (w + e) / 2
        d2 = (lat - cy) ** 2 + (lon - cx) ** 2
        if d2 < nearest_d2:
            nearest_d2, nearest_state = d2, state

    if best_state is not None:
        return best_state
    return nearest_state if nearest_d2 <= _NEAR_LIMIT2 else None


def regional_soil_estimate(lat: float, lon: float) -> dict | None:
    """Dominant-soil estimate for a point, or None if it isn't in India.

    Returns {"ph", "texture_class", "region", "state"}. Never a substitute for a
    soil test — a state-level typical value used only to fill SoilGrids gaps.
    """
    state = state_for_point(lat, lon)
    if state is None:
        return None
    soil = STATE_SOIL.get(state)
    if soil is None:
        return None
    return {**soil, "state": state}
