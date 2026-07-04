"""Curated government schemes, marketplaces and input resources for farmers."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter

_REPO_ROOT = Path(__file__).resolve().parents[4]
_DB = _REPO_ROOT / "packages" / "crop-db" / "resources.json"

router = APIRouter(prefix="/resources", tags=["resources"])


@lru_cache
def _load() -> dict:
    with _DB.open(encoding="utf-8") as fh:
        return json.load(fh)


@router.get("/schemes")
def schemes(state: str | None = None, category: str | None = None) -> dict:
    """List schemes/resources, optionally filtered by state and category.

    State-specific entries (audience = a state name) are included only when that
    state matches; national entries (audience = "all") always appear.
    """
    items = _load()["resources"]
    if category:
        items = [r for r in items if r["category"] == category]
    if state:
        items = [r for r in items
                 if r["audience"] == "all" or r["audience"].lower() == state.lower()]
    else:
        items = [r for r in items if r["audience"] == "all"]
    return {"count": len(items), "resources": items}
