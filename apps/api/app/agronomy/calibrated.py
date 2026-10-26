"""Calibrated crop-suitability model ("calibrated profiles").

Same factors as the expert rules (pH, rainfall, growing-season temperature,
texture) plus a prevalence prior, all *learned from where each crop is grown
at scale* (Indian district crop statistics, APY 2013-14 .. 2022-23). Each
factor scores how much more often the crop is grown where that factor takes
this value than on average (a log likelihood ratio per value bin), so a crop
grown everywhere gains little from any factor and a regional crop gains a lot
inside its niche. The fitted model is packages/crop-db/calibrated_model.json,
exported by research/scripts/s09_export_model.py; see research/README.md.

The learned 5-95% growing range per factor is kept for the reasons shown to
farmers. Crops the statistics don't cover systematically (vegetables, papaya,
drumstick, climbing beans, spinach) have no profile, get neutral factors, and
are flagged ``calibrated: false`` (recommend.py ranks them by the expert rules).
"""
from __future__ import annotations

import json
import math
import re
from bisect import bisect_right
from functools import lru_cache
from pathlib import Path

from .catalogue import all_crops

_REPO_ROOT = Path(__file__).resolve().parents[4]
MODEL_PATH = _REPO_ROOT / "packages" / "crop-db" / "calibrated_model.json"

VARS = ("ph", "rain_annual", "tmean_kharif", "tmean_rabi", "tmean_zaid")
_SEASON_VAR = {"Kharif (monsoon)": "tmean_kharif", "Rabi (winter)": "tmean_rabi",
               "Zaid (summer)": "tmean_zaid"}
_SEASON_KEY = {"Kharif (monsoon)": "Kharif", "Rabi (winter)": "Rabi"}
_TMEAN_KEY = {"Kharif (monsoon)": "kharif", "Rabi (winter)": "rabi", "Zaid (summer)": "zaid"}
# Expert-rule slacks, used to build envelopes for uncalibrated crops.
_EXPERT_SLACK = {"ph": 1.5, "rain_annual": 600.0, "temp": 8.0}
_VAR_LABEL = {"ph": "soil pH", "rain_annual": "annual rainfall",
              "tmean_kharif": "Kharif mean temperature", "tmean_rabi": "Rabi mean temperature",
              "tmean_zaid": "Zaid mean temperature"}
_UNIT = {"ph": "", "rain_annual": " mm", "tmean_kharif": " °C", "tmean_rabi": " °C",
         "tmean_zaid": " °C"}


@lru_cache(maxsize=1)
def load_model() -> dict | None:
    if not MODEL_PATH.exists():
        return None
    with MODEL_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def available() -> bool:
    return load_model() is not None


def _trapezoid(x: float | None, lo: float, hi: float, slack: float) -> float:
    if x is None:
        return 0.5  # unknown -> neutral, exactly as in training
    if lo <= x <= hi:
        return 1.0
    dist = lo - x if x < lo else x - hi
    return max(0.0, 1.0 - dist / slack)


def _expert_entry(crop: dict, default_prior: float) -> dict:
    """Envelope for a crop the statistics don't cover, from its expert ranges."""
    env: dict = {v: None for v in VARS}
    env["ph"] = [crop["ph"][0], crop["ph"][1], _EXPERT_SLACK["ph"]]
    env["rain_annual"] = [crop["rainfall_mm"][0], crop["rainfall_mm"][1],
                          _EXPERT_SLACK["rain_annual"]]
    # temp_c ranges are growing-season mean temperatures
    for s in crop["seasons"]:
        env[_SEASON_VAR[s]] = [crop["temp_c"][0], crop["temp_c"][1], _EXPERT_SLACK["temp"]]
    seasons = {_SEASON_KEY[s]: default_prior for s in crop["seasons"] if s in _SEASON_KEY}
    return {"envelope": env, "textures": list(crop["textures"]), "log_prior": default_prior,
            "log_prior_season": seasons, "calibrated": False}


def _entry(model: dict, crop: dict) -> dict:
    e = model["crops"].get(crop["id"])
    if e is not None:
        return {**e, "calibrated": True}
    return _expert_entry(crop, model["default_log_prior"])


def _ratio(model: dict, e: dict, var: str, x) -> float:
    """Log likelihood ratio for one factor (0 = no evidence, as in training)."""
    table = (e.get("profile") or {}).get(var)
    if x is None or table is None:
        return 0.0
    return table[bisect_right(model["bins"][var], x)]


def _factor(model: dict, e: dict, var: str, x, reasons: list[str]) -> float:
    """Score for one factor, plus a human-readable reason.

    Profile models (schema 2) score the log likelihood ratio; the older
    envelope models score the trapezoid. The reason always states the range
    where the crop is grown, and for profiles how much more (or less) often.
    """
    env = e["envelope"].get(var)
    profiled = "bins" in model
    s = _ratio(model, e, var, x) if profiled else 0.5
    if env is None:
        return s
    lo, hi, slack = env
    t = _trapezoid(x, lo, hi, slack)
    if not profiled:
        s = t
    if x is None:
        return s
    if profiled and e.get("profile"):
        # The ratio is the evidence; the 5-95% range is context only (a crop's
        # niche can sit at the edge of its all-India range: bajra in the desert).
        reasons.append(f"{_VAR_LABEL[var]} {x:g}{_UNIT[var]}: grown {_times(s)} as often as "
                       f"average at this level (most growing districts: "
                       f"{lo:.4g}–{hi:.4g}{_UNIT[var]})")
    else:
        where = "within" if t == 1.0 else ("below" if x < lo else "above")
        reasons.append(f"{_VAR_LABEL[var]} {x:g}{_UNIT[var]} is {where} the range "
                       f"{lo:.4g}–{hi:.4g}{_UNIT[var]} where it is grown")
    return s


def _times(log_ratio: float) -> str:
    r = math.exp(log_ratio)
    return f"{r:.1f}×" if r >= 1 else f"{r:.2f}×"


def _norm_state(name: str) -> str:
    """'The Dadra And Nagar Haveli…' / 'Dadra and Nagar Haveli…' -> same key."""
    return re.sub(r"[^a-z]", "", re.sub(r"^the\s+", "", name.strip(), flags=re.I).lower())


def _state_key(model: dict, state: str | None) -> str | None:
    """The model's own spelling of a state name (APY vs OpenStreetMap differ)."""
    if not state:
        return None
    index = model.setdefault("_state_index",
                             {_norm_state(s): s for s in model.get("state_priors") or {}})
    return index.get(_norm_state(state))


def _prior(model: dict, e: dict, crop_id: str, key: str | None, state: str | None) -> float:
    """State prior (shrunk to the national rate) when the state is known, else national.

    state_priors layout: annual model {state: {crop: lp}}; seasonal model
    {state: {crop: {"Kharif": lp, "Rabi": lp}}}. ``state`` is the model's key.
    """
    sp = (model.get("state_priors") or {}).get(state or "", {}).get(crop_id)
    if isinstance(sp, dict) and key in sp:
        return sp[key]
    if isinstance(sp, (int, float)):
        return sp
    if key:
        return (e.get("log_prior_season") or {}).get(key, e["log_prior"])
    return e["log_prior"]


def score(crop: dict, *, ph=None, texture=None, rainfall=None, tmean=None,
          season: str | None = None, irrigated: bool | None = None,
          state: str | None = None) -> dict | None:
    """Probability that the crop is grown at scale here, with reasons.

    Five factors, exactly as trained: pH, annual rainfall, growing-season mean
    temperature, texture and a prevalence prior. ``tmean`` maps
    "kharif"/"rabi"/"zaid" to seasonal mean temperatures; with a Kharif/Rabi
    ``season`` that season is used, otherwise the best of the crop's own seasons.
    ``state`` enables the state-level prior (the "known region" scenario).

    ``irrigated``: True / False (rain-fed) / None (unknown). The crop statistics
    mix irrigated and rain-fed land, so the learned rainfall ranges are wide
    (paddy is grown at ~300 mm in canal-irrigated districts). For a rain-fed
    farm the expert rain-fed requirement is applied on top; when unknown, crops
    short of rain are flagged but not demoted. Excess rain is not something
    irrigation changes, so only a deficit counts.
    Returns None if no model has been exported.
    """
    root = load_model()
    if root is None:
        return None
    key = _SEASON_KEY.get(season or "")
    model = root["seasonal"] if key else root["annual"]
    state = _state_key(model, state)
    e = _entry(model, crop)
    tmean = tmean or {}
    reasons: list[str] = []

    f_ph = _factor(model, e, "ph", ph, reasons)
    f_rain = _factor(model, e, "rain_annual", rainfall, reasons)
    if key:
        f_temp = _factor(model, e, _SEASON_VAR[season], tmean.get(_TMEAN_KEY[season]), reasons)
    else:
        own: list[tuple[float, list[str]]] = []
        for s in crop["seasons"]:
            r: list[str] = []
            own.append((_factor(model, e, _SEASON_VAR[s], tmean.get(_TMEAN_KEY[s]), r), r))
        f_temp, best_reasons = max(own, key=lambda t: t[0]) if own else (0.5, [])
        reasons.extend(best_reasons)
    tex = e.get("textures")
    tex_profile = (e.get("profile") or {}).get("texture")
    if "bins" in model:
        f_tex = tex_profile.get(texture, 0.0) if (texture and tex_profile) else 0.0
    else:
        f_tex = (1.0 if texture in tex else 0.4) if (texture and tex) else 0.5
    if texture and tex:
        reasons.append(f"soil texture {texture} "
                       f"({'typical' if texture in tex else 'less typical'} for this crop)")
    feats = [f_ph, f_rain, f_temp, f_tex, _prior(model, e, crop["id"], key, state)]

    # Weights fitted alongside state priors when this state has a prior table.
    known = state is not None
    coef = model["coef_state"] if known else model["coef"]
    intercept = model["intercept_state"] if known else model["intercept"]
    z = intercept + sum(w * f for w, f in zip(coef, feats))
    p = 1.0 / (1.0 + math.exp(-z))

    # Water: expert rain-fed requirement (lower bound of rainfall_mm), deficit only.
    lo_rain = crop["rainfall_mm"][0]
    rainfed = 1.0 if rainfall is None or rainfall >= lo_rain else \
        max(0.0, 1.0 - (lo_rain - rainfall) / _EXPERT_SLACK["rain_annual"])
    needs_irrigation = rainfed < 0.5
    if needs_irrigation:
        reasons.append(f"needs irrigation: {rainfall:g} mm of rain is below its rain-fed "
                       f"requirement of {crop['rainfall_mm'][0]}–{crop['rainfall_mm'][1]} mm")
    if irrigated is False:
        p *= rainfed

    if not e["calibrated"]:
        reasons.append("expert ranges — not yet calibrated on crop statistics")
    # Levels relative to places where this crop is grown at scale, on the scale
    # of whichever weights scored it (state-prior or national).
    sfx = "_state" if known else ""
    levels = ((model.get(f"levels_by_crop{sfx}") or {}).get(crop["id"])
              or model.get(f"levels{sfx}") or root["levels"])
    return {"crop_id": crop["id"], "name": crop["name"], "layer": crop["layer"],
            "category": crop["category"], "score": round(p, 3),
            "level": _level(p, levels), "suitability": _label(p, levels),
            "calibrated": e["calibrated"], "needs_irrigation": needs_irrigation,
            "reasons": reasons}


def _level(p: float, levels: dict) -> str:
    if p >= levels["high"]:
        return "high"
    if p >= levels["ok"]:
        return "ok"
    if p >= levels["low"]:
        return "low"
    return "none"


def _label(p: float, levels: dict) -> str:
    return {"high": "Highly suitable", "ok": "Suitable", "low": "Marginal",
            "none": "Not recommended"}[_level(p, levels)]


def recommend(*, ph=None, texture=None, rainfall=None, tmean=None, season=None,
              irrigated: bool | None = None, state: str | None = None,
              crops: list[dict] | None = None, limit: int = 8) -> list[dict] | None:
    if load_model() is None:
        return None
    pool = crops if crops is not None else all_crops()
    scored = [score(c, ph=ph, texture=texture, rainfall=rainfall, tmean=tmean,
                    season=season, irrigated=irrigated, state=state)
              for c in pool]
    scored.sort(key=lambda r: r["score"], reverse=True)
    return scored[:limit]
