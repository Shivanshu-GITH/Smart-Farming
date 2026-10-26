"""Rules-based crop suitability scoring.

A transparent scoring engine (not an opaque ML model) so recommendations are
explainable to farmers and reviewable by agronomists. Each crop is scored on
soil pH, texture, rainfall, temperature and season; the reasons are returned
alongside the score so the UI can show *why*.
"""
from __future__ import annotations

from . import calibrated
from .catalogue import all_crops, crop_systems


def _range_score(value: float | None, lo: float, hi: float, slack: float) -> float:
    """1.0 inside [lo, hi], tapering to 0 within `slack` beyond the edges."""
    if value is None:
        return 0.5  # unknown -> neutral, don't punish
    if lo <= value <= hi:
        return 1.0
    dist = (lo - value) if value < lo else (value - hi)
    return max(0.0, 1.0 - dist / slack)


_SEASON_TMEAN_KEY = {"Kharif (monsoon)": "kharif", "Rabi (winter)": "rabi",
                     "Zaid (summer)": "zaid"}


def _season_temperature(crop: dict, temp_max: float | None, season: str | None,
                        tmean: dict | None) -> float | None:
    """Temperature to judge the crop on.

    The database's temp_c ranges are growing-season *mean* temperatures, so
    when seasonal means are known we use the requested season's (or, with no
    season, the best of the crop's own seasons). Otherwise fall back to the
    caller's annual mean daily maximum (the original behaviour).
    """
    if not tmean:
        return temp_max
    if season in _SEASON_TMEAN_KEY and tmean.get(_SEASON_TMEAN_KEY[season]) is not None:
        return tmean[_SEASON_TMEAN_KEY[season]]
    lo, hi = crop["temp_c"]
    own = [tmean.get(_SEASON_TMEAN_KEY[s]) for s in crop["seasons"]]
    own = [t for t in own if t is not None]
    if not own:
        return temp_max
    # the season whose temperature sits closest to the crop's range
    return min(own, key=lambda t: 0 if lo <= t <= hi else min(abs(t - lo), abs(t - hi)))


def score_crop(crop: dict, *, ph: float | None, texture: str | None,
               rainfall: float | None, temp_max: float | None,
               season: str | None, tmean: dict | None = None) -> dict:
    reasons: list[str] = []
    temp_max = _season_temperature(crop, temp_max, season, tmean)

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
        what = "growing-season mean temp" if tmean else "max temp"
        reasons.append(f"{what} {temp_max}C vs {crop['temp_c']}C")

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


EXPERT_SLOTS = 2  # expert-only crops appended to a calibrated list, at most


def _rule_level(score: float) -> str:
    return "high" if score >= 0.8 else "ok" if score >= 0.6 else "low" if score >= 0.4 else "none"


def _label(score: float) -> str:
    if score >= 0.8:
        return "Highly suitable"
    if score >= 0.6:
        return "Suitable"
    if score >= 0.4:
        return "Marginal"
    return "Not recommended"


def recommend(*, ph=None, texture=None, rainfall=None, temp_max=None,
              season=None, layer=None, system=None, limit=8,
              tmean: dict | None = None, irrigated: bool | None = None,
              state: str | None = None) -> list[dict]:
    crops = all_crops()
    if system:
        crops = [c for c in crops if system in crop_systems(c)]
    if layer:
        crops = [c for c in crops if c["layer"] == layer]
    # The calibrated model (agronomy/calibrated.py) is fitted to where field
    # crops are *grown at scale* in district statistics. That is the question
    # behind single-crop and intercrop decisions; the statistics record nothing
    # about multi-strata designs and miss most of their crops, so multilayer
    # suggestions stay on the expert rules (with the seasonal-temperature fix).
    if system != "multilayer":
        scored_all = calibrated.recommend(ph=ph, texture=texture, rainfall=rainfall,
                                          tmean=tmean, season=season, irrigated=irrigated,
                                          state=state, crops=crops, limit=len(crops))
        if scored_all is not None:
            by_id = {c["id"]: c for c in crops}
            validated = [r for r in scored_all if r["calibrated"]]
            expert = []
            for r in scored_all:
                if r["calibrated"]:
                    continue
                # No statistics behind this crop: rank and label it by the
                # expert rules, never by a probability built on a generic prior.
                rule = score_crop(by_id[r["crop_id"]], ph=ph, texture=texture,
                                  rainfall=rainfall, temp_max=temp_max, season=season,
                                  tmean=tmean)
                r["suitability"], r["level"] = rule["suitability"], _rule_level(rule["score"])
                r["_rule"] = rule["score"]
                expert.append(r)
            # Validated crops lead (the evaluated ranking); up to EXPERT_SLOTS
            # well-rated expert-only crops follow (vegetables matter on small plots).
            expert = [r for r in sorted(expert, key=lambda r: r["_rule"], reverse=True)
                      if r["level"] in ("high", "ok")][:EXPERT_SLOTS]
            for r in expert:
                r.pop("_rule")
            return validated[:max(0, limit - len(expert))] + expert
    scored = [
        score_crop(c, ph=ph, texture=texture, rainfall=rainfall,
                   temp_max=temp_max, season=season, tmean=tmean)
        for c in crops
    ]
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:limit]
