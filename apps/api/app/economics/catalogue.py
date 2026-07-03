"""Loads the farm-economics dataset (packages/crop-db/economics.json)."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

# apps/api/app/economics/catalogue.py -> repo root is 4 levels up
_REPO_ROOT = Path(__file__).resolve().parents[4]
_ECON_DB = _REPO_ROOT / "packages" / "crop-db" / "economics.json"


@lru_cache
def load_economics() -> dict:
    with _ECON_DB.open(encoding="utf-8") as fh:
        return json.load(fh)


def get_economics(crop_id: str) -> dict | None:
    return load_economics()["crops"].get(crop_id)
