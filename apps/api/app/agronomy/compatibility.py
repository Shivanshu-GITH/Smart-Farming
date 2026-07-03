"""Multi-layer combo validation — a core piece of the differentiator.

Uses the curated companions/antagonists + layer + season data to tell a farmer
whether a chosen set of crops actually works *together*: it flags antagonist
pairs (hard conflicts), same-layer crowding and season mismatches (warnings),
highlights companion synergies, and can suggest compatible crops to fill the
empty vertical layers.
"""
from __future__ import annotations

from collections import defaultdict

from .catalogue import all_crops, get_crop, layers
from .recommend import score_crop


def _resolve(crop_ids: list[str]) -> list[tuple[str, dict]]:
    """Keep only ids present in the catalogue, preserving order & uniqueness."""
    seen: set[str] = set()
    out: list[tuple[str, dict]] = []
    for cid in crop_ids:
        if cid in seen:
            continue
        crop = get_crop(cid)
        if crop is not None:
            out.append((cid, crop))
            seen.add(cid)
    return out


def validate_combo(crop_ids: list[str]) -> dict:
    crops = _resolve(crop_ids)
    conflicts: list[dict] = []
    warnings: list[dict] = []
    synergies: list[dict] = []

    # Pairwise antagonist / companion relations (relation is symmetric if either
    # crop lists the other).
    for i in range(len(crops)):
        for j in range(i + 1, len(crops)):
            (ida, ca), (idb, cb) = crops[i], crops[j]
            a_anta = set(ca.get("antagonists") or [])
            b_anta = set(cb.get("antagonists") or [])
            if idb in a_anta or ida in b_anta:
                conflicts.append({
                    "type": "antagonist",
                    "crops": [ida, idb],
                    "message": f"{ca['name']} and {cb['name']} are antagonists — "
                               "keep them apart or drop one.",
                })
            a_comp = set(ca.get("companions") or [])
            b_comp = set(cb.get("companions") or [])
            if idb in a_comp or ida in b_comp:
                synergies.append({
                    "type": "companion",
                    "crops": [ida, idb],
                    "message": f"{ca['name']} + {cb['name']} are good companions.",
                })

    # Same-layer crowding: multi-layer farming wants ~one crop per vertical layer.
    by_layer: dict[str, list[str]] = defaultdict(list)
    for _cid, c in crops:
        by_layer[c["layer"]].append(c["name"])
    for layer, names in by_layer.items():
        if len(names) > 1:
            warnings.append({
                "type": "layer_crowding",
                "layer": layer,
                "message": f"{len(names)} crops share the {layer} layer "
                           f"({', '.join(names)}) — they compete for the same "
                           "space. Multi-layer farming works best with one per layer.",
            })

    # Season overlap: can they all be in the ground at once?
    season_sets = [set(c["seasons"]) for _cid, c in crops]
    common = set.intersection(*season_sets) if season_sets else set()
    if len(crops) > 1 and not common:
        warnings.append({
            "type": "season",
            "message": "These crops don't share a common growing season, so they "
                       "can't all be grown together at the same time.",
        })

    return {
        "compatible": len(conflicts) == 0,
        "conflicts": conflicts,
        "warnings": warnings,
        "synergies": synergies,
        "layers_used": dict(by_layer),
        "common_seasons": sorted(common),
    }


def _banned_against(selected: list[dict]) -> set[str]:
    """Ids that antagonise (or are antagonised by) any selected crop."""
    selected_ids = {c["id"] for c in selected}
    banned: set[str] = set()
    for c in selected:
        banned |= set(c.get("antagonists") or [])
    # also ban crops that list a selected crop as their antagonist
    for cand in all_crops():
        if set(cand.get("antagonists") or []) & selected_ids:
            banned.add(cand["id"])
    return banned


def suggest_fillers(crop_ids: list[str], *, ph=None, texture=None, rainfall=None,
                    temp_max=None, season=None, per_layer: int = 2) -> dict:
    """For each empty vertical layer, suggest land-suitable, non-antagonist crops
    (companions of the current selection ranked first)."""
    selected = [c for _cid, c in _resolve(crop_ids)]
    selected_ids = {c["id"] for c in selected}
    used_layers = {c["layer"] for c in selected}
    banned = _banned_against(selected)

    def companion_link(cand: dict) -> list[str]:
        links = set(cand.get("companions") or []) & selected_ids
        links |= {s["id"] for s in selected if cand["id"] in (s.get("companions") or [])}
        return sorted(links)

    suggestions: dict[str, list[dict]] = {}
    for layer in layers():
        if layer in used_layers:
            continue
        scored: list[dict] = []
        for cand in all_crops():
            if cand["layer"] != layer or cand["id"] in selected_ids or cand["id"] in banned:
                continue
            if season and season not in cand["seasons"]:
                continue  # must be plantable in the target season
            s = score_crop(cand, ph=ph, texture=texture, rainfall=rainfall,
                           temp_max=temp_max, season=season)
            links = companion_link(cand)
            s["companion_with"] = links
            s["combo_score"] = round(min(1.0, s["score"] + (0.1 if links else 0.0)), 3)
            scored.append(s)
        scored.sort(key=lambda x: x["combo_score"], reverse=True)
        if scored:
            suggestions[layer] = scored[:per_layer]
    return suggestions
