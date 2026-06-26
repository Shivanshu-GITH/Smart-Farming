"""Loads and serves the curated crop knowledge base (packages/crop-db)."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

# apps/api/app/agronomy/catalogue.py -> repo root is 4 levels up
_REPO_ROOT = Path(__file__).resolve().parents[4]
_CROP_DB = _REPO_ROOT / "packages" / "crop-db" / "crops.json"


@lru_cache
def load_db() -> dict:
    with _CROP_DB.open(encoding="utf-8") as fh:
        return json.load(fh)


def all_crops() -> list[dict]:
    return load_db()["crops"]


def layers() -> dict:
    return load_db()["layers"]


def get_crop(crop_id: str) -> dict | None:
    return next((c for c in all_crops() if c["id"] == crop_id), None)
