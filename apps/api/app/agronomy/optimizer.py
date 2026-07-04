"""5-layer farming design engine — the headline differentiator.

Given the land's conditions, it proposes complete multi-layer stacks (one crop
per vertical layer where possible) that are (a) suitable for the soil/climate,
(b) plantable in the same season and (c) free of antagonist conflicts, ranked by
a blend of per-crop suitability and companion synergy. A small beam search keeps
it from being a naive greedy pick while staying fast and fully explainable.
"""
from __future__ import annotations

from .catalogue import all_crops, crop_systems, layers
from .recommend import score_crop


def _layer_order() -> list[str]:
    return [name for name, _ in sorted(layers().items(), key=lambda kv: kv[1]["order"])]


def _candidates(layer: str, *, ph, texture, rainfall, temp_max, season) -> list[dict]:
    out = []
    for c in all_crops():
        if c["layer"] != layer:
            continue
        if "multilayer" not in crop_systems(c):
            continue  # the stack designer only proposes multilayer-suited crops
        if season and season not in c["seasons"]:
            continue
        s = score_crop(c, ph=ph, texture=texture, rainfall=rainfall,
                       temp_max=temp_max, season=season)
        if s["score"] < 0.4:  # skip unsuitable crops entirely
            continue
        out.append({**s, "crop": c})
    out.sort(key=lambda x: x["score"], reverse=True)
    return out


def _conflict(cand: dict, chosen: list[dict]) -> bool:
    cid = cand["crop"]["id"]
    cand_anta = set(cand["crop"].get("antagonists") or [])
    for ch in chosen:
        if ch["crop"]["id"] in cand_anta:
            return True
        if cid in set(ch["crop"].get("antagonists") or []):
            return True
    return False


def _synergy_bonus(cand: dict, chosen: list[dict]) -> float:
    cid = cand["crop"]["id"]
    cand_comp = set(cand["crop"].get("companions") or [])
    bonus = 0.0
    for ch in chosen:
        if ch["crop"]["id"] in cand_comp or cid in set(ch["crop"].get("companions") or []):
            bonus += 0.08
    return bonus


def design_stacks(*, ph=None, texture=None, rainfall=None, temp_max=None,
                  season=None, max_stacks: int = 3, beam_width: int = 6,
                  top_k_per_layer: int = 4) -> dict:
    """Beam search over vertical layers. Each beam entry is a partial stack:
    {"picks": [...], "score": float}. We extend by one layer at a time."""
    beams: list[dict] = [{"picks": [], "score": 0.0}]

    for layer in _layer_order():
        cands = _candidates(layer, ph=ph, texture=texture, rainfall=rainfall,
                            temp_max=temp_max, season=season)[:top_k_per_layer]
        next_beams: list[dict] = []
        for beam in beams:
            # Option 1: skip this layer (not every field needs all 5 filled).
            next_beams.append(beam)
            # Option 2: add a compatible candidate.
            for cand in cands:
                if _conflict(cand, beam["picks"]):
                    continue
                gain = cand["score"] + _synergy_bonus(cand, beam["picks"])
                next_beams.append({
                    "picks": [*beam["picks"], cand],
                    "score": round(beam["score"] + gain, 4),
                })
        # keep the most promising partial stacks
        next_beams.sort(key=lambda b: b["score"], reverse=True)
        beams = next_beams[:beam_width]

    # Finalise: drop empties, de-duplicate identical crop sets, rank.
    stacks: list[dict] = []
    seen: set[tuple[str, ...]] = set()
    for beam in sorted(beams, key=lambda b: b["score"], reverse=True):
        picks = beam["picks"]
        if not picks:
            continue
        sig = tuple(sorted(p["crop"]["id"] for p in picks))
        if sig in seen:
            continue
        seen.add(sig)
        stacks.append(_format_stack(picks, beam["score"]))
        if len(stacks) >= max_stacks:
            break

    return {"season": season, "count": len(stacks), "stacks": stacks}


def _format_stack(picks: list[dict], score: float) -> dict:
    # collect the companion links within this stack for the "why"
    ids = {p["crop"]["id"] for p in picks}
    layers_out = []
    for p in picks:
        comp = (set(p["crop"].get("companions") or []) & ids)
        comp |= {q["crop"]["id"] for q in picks
                 if p["crop"]["id"] in (q["crop"].get("companions") or [])}
        layers_out.append({
            "layer": p["layer"],
            "crop_id": p["crop"]["id"],
            "name": p["name"],
            "suitability": p["suitability"],
            "score": p["score"],
            "companions_in_stack": sorted(comp),
        })
    return {
        "layers": layers_out,
        "crop_ids": [p["crop"]["id"] for p in picks],
        "filled_layers": len(picks),
        "total_score": round(score, 3),
    }
