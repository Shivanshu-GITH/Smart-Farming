"""Rules-based crop suitability scoring.

A transparent scoring engine (not an opaque ML model) so recommendations are
explainable to farmers and reviewable by agronomists. Each crop is scored on
soil pH, texture, rainfall, temperature and season; the reasons are returned
alongside the score so the UI can show *why*.
"""
from __future__ import annotations

from .catalogue import all_crops


def _range_score(value: float | None, lo: float, hi: float, slack: float) -> float:
    """1.0 inside [lo, hi], tapering to 0 within `slack` beyond the edges."""
    if value is None:
        return 0.5  # unknown -> neutral, don't punish
    if lo <= value <= hi:
        return 1.0
    dist = (lo - value) if value < lo else (value - hi)
    return max(0.0, 1.0 - dist / slack)


def score_crop(crop: dict, *, ph: float | None, texture: str | None,
               rainfall: float | None, temp_max: float | None,
               season: str | None) -> dict:
    reasons: list[str] = []

    ph_s = _range_score(ph, crop["ph"][0], crop["ph"][1], slack=1.5)
    if ph is not None:
        reasons.append(
            f"pH {ph} vs preferred {crop['ph'][0]}-{crop['ph'][1]} "
            f"({'good' if ph_s == 1 else 'marginal'})"
        )

    rain_s = _range_score(rainfall, crop["rainfall_mm"][0], crop["rainfall_mm"][1],
                          slack=600)
    if rainfall is not None:
        reasons.append(f"rainfall {rainfall:.0f}mm vs {crop['rainfall_mm']}mm")

    temp_s = _range_score(temp_max, crop["temp_c"][0], crop["temp_c"][1], slack=8)
    if temp_max is not None:
        reasons.append(f"max temp {temp_max}C vs {crop['temp_c']}C")

    texture_s = 1.0
    if texture:
        texture_s = 1.0 if texture in crop["textures"] else 0.4
        reasons.append(
            f"soil texture {texture} "
            f"({'suitable' if texture_s == 1 else 'workable'})"
        )

    season_s = 1.0
    if season:
        season_s = 1.0 if season in crop["seasons"] else 0.3
        reasons.append(
            f"season {season} "
            f"({'in window' if season_s == 1 else 'off-season'})"
        )

    # weighted blend
    score = (0.25 * ph_s + 0.2 * rain_s + 0.2 * temp_s
             + 0.15 * texture_s + 0.2 * season_s)
    return {
        "crop_id": crop["id"],
        "name": crop["name"],
        "layer": crop["layer"],
        "category": crop["category"],
        "score": round(score, 3),
        "suitability": _label(score),
        "reasons": reasons,
    }


def _label(score: float) -> str:
    if score >= 0.8:
        return "Highly suitable"
    if score >= 0.6:
        return "Suitable"
    if score >= 0.4:
        return "Marginal"
    return "Not recommended"


def recommend(*, ph=None, texture=None, rainfall=None, temp_max=None,
              season=None, layer=None, limit=8) -> list[dict]:
    crops = all_crops()
    if layer:
        crops = [c for c in crops if c["layer"] == layer]
    scored = [
        score_crop(c, ph=ph, texture=texture, rainfall=rainfall,
                   temp_max=temp_max, season=season)
        for c in crops
    ]
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:limit]
