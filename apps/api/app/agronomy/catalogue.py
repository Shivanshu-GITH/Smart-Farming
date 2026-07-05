"""Loads and serves the curated crop knowledge base (packages/crop-db)."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

# apps/api/app/agronomy/catalogue.py -> repo root is 4 levels up
_REPO_ROOT = Path(__file__).resolve().parents[4]
_CROP_DB = _REPO_ROOT / "packages" / "crop-db" / "crops.json"
_SYSTEMS_DB = _REPO_ROOT / "packages" / "crop-db" / "systems.json"

_ALL_SYSTEMS = ("monoculture", "intercrop", "multilayer")


@lru_cache
def load_db() -> dict:
    with _CROP_DB.open(encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache
def load_systems() -> list[dict]:
    with _SYSTEMS_DB.open(encoding="utf-8") as fh:
        return json.load(fh)["systems"]


def all_crops() -> list[dict]:
    return load_db()["crops"]


def layers() -> dict:
    return load_db()["layers"]


def get_crop(crop_id: str) -> dict | None:
    return next((c for c in all_crops() if c["id"] == crop_id), None)


def crop_systems(crop: dict) -> list[str]:
    """Farming systems a crop suits (older entries without the key suit all)."""
    return crop.get("systems", list(_ALL_SYSTEMS))


def usable_fraction(system: str | None) -> float:
    """Share of gross land actually planted for a farming system — the rest is
    bunds, walking/inspection paths and irrigation lines. 1.0 when unknown."""
    if not system:
        return 1.0
    for s in load_systems():
        if s["id"] == system:
            return float(s.get("usable_area_fraction", 1.0))
    return 1.0


# How each crop is actually planted. crops.json can override per crop with a
# "propagation" key; this table is the curated default.
_PROPAGATION: dict[str, str] = {
    "turmeric": "rhizome", "ginger": "rhizome",
    "banana": "sucker",
    "papaya": "seedling", "drumstick": "seedling", "tomato": "seedling",
    "brinjal": "seedling", "chilli": "seedling", "onion": "seedling",
    "paddy": "seedling",
    "sugarcane": "sett",
    "potato": "tuber",
}


def propagation(crop: dict) -> str:
    """seed | seedling | sucker | rhizome | sett | tuber"""
    return crop.get("propagation") or _PROPAGATION.get(crop["id"], "seed")


def crops_for_system(system: str | None) -> list[dict]:
    if not system:
        return all_crops()
    return [c for c in all_crops() if system in crop_systems(c)]
