"""Regional soil fallback: crop scoring stays location-aware even when SoilGrids
returns nothing (rate limit, outage, or a coverage gap)."""
import httpx
import pytest

from app.core import cache
from app.land_intel import soil as soil_mod
from app.land_intel.regional_soil import (
    STATE_SOIL,
    regional_soil_estimate,
    state_for_point,
)

# The texture labels the crop database scores against; the fallback must only
# ever emit these, or texture matching silently fails.
_CROP_TEXTURES = {"Clay", "Clay loam", "Loam / Silt loam", "Sandy", "Sandy loam"}


@pytest.fixture(autouse=True)
def _fresh_cache():
    cache._store.clear()
    cache._windows.clear()
    yield
    cache._store.clear()
    cache._windows.clear()


def test_point_resolves_to_state():
    assert state_for_point(26.85, 80.95) == "Uttar Pradesh"   # Lucknow
    assert state_for_point(19.99, 73.79) == "Maharashtra"     # Nashik
    assert state_for_point(9.93, 76.26) == "Kerala"           # Kochi
    assert state_for_point(12.97, 77.59) == "Karnataka"       # Bengaluru


def test_estimate_reflects_the_regional_soil_group():
    mh = regional_soil_estimate(19.99, 73.79)   # Deccan black cotton
    assert mh["texture_class"] == "Clay loam" and mh["ph"] >= 7.5
    kl = regional_soil_estimate(9.93, 76.26)    # acidic laterite
    assert kl["ph"] <= 5.5
    assert "state" in kl and "region" in kl


def test_every_state_texture_is_in_crop_vocabulary():
    for state, v in STATE_SOIL.items():
        assert v["texture_class"] in _CROP_TEXTURES, state
        assert 4.0 <= v["ph"] <= 9.0, state


def test_estimate_none_outside_india():
    # Mid-Atlantic — no district box near, so no meaningful Indian estimate.
    assert regional_soil_estimate(0.0, -40.0) is None


async def test_get_soil_falls_back_when_soilgrids_down(monkeypatch):
    async def _boom(self, *a, **k):
        raise httpx.ConnectError("down")
    monkeypatch.setattr(httpx.AsyncClient, "get", _boom)

    d = await soil_mod.get_soil(19.99, 73.79)   # Nashik, Maharashtra
    assert d["ph"] == 8.0
    assert d["texture_class"] == "Clay loam"
    assert d["ph_source"] == "regional estimate"
    assert d["texture_source"] == "regional estimate"
    assert d["region_state"] == "Maharashtra"


async def test_get_soil_falls_back_when_rate_limited(monkeypatch):
    # Exhaust the SoilGrids window so the call is skipped entirely.
    for _ in range(5):
        await cache.allow("rl:soilgrids", limit=5, window_seconds=60)
    d = await soil_mod.get_soil(9.93, 76.26)    # Kochi, Kerala
    assert d.get("error")  # the "busy" note is still surfaced
    assert d["ph"] == 5.2 and d["texture_class"] == "Sandy loam"
    assert d["ph_source"] == "regional estimate"
