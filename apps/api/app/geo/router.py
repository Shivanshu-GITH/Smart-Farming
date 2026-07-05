"""Location search so a farmer can find their village/field.

Three complementary paths:
- Layered finder: bundled all-India states/districts (GET /geo/states,
  /geo/districts) plus a live per-district village directory from
  OpenStreetMap via Overpass (GET /geo/villages) so a farmer can drill
  state -> district -> village without typing anything.
- Free-text search: proxies OSM Nominatim (free; needs a User-Agent and modest
  rate use — results are cached). India-biased by default. When scoped to a
  district and the plain text query misses, we retry bounded to the district's
  bounding box so tiny hamlets still resolve.
"""
from __future__ import annotations

import gzip
import json
import re
from functools import lru_cache
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Query

from app.core import cache

router = APIRouter(prefix="/geo", tags=["geo"])

NOMINATIM_SEARCH = "https://nominatim.openstreetmap.org/search"
# Public Overpass mirrors, tried in order (free; district-sized place queries
# are light, and results are cached for 30 days).
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
_HEADERS = {"User-Agent": "SmartFarm/1.0 (precision-farm-planning)"}

# OSM place types that count as a "village" for the finder dropdown.
_PLACE_FILTER = '["place"~"^(village|hamlet|town|suburb)$"]["name"]'

# apps/api/app/geo/router.py -> repo root is 4 levels up
_REPO_ROOT = Path(__file__).resolve().parents[4]
_PLACES_DB = _REPO_ROOT / "packages" / "india-geo" / "states-districts.json"
# Per-state village index built from the GeoNames dump (CC BY 4.0) by
# packages/india-geo/build_villages.py — ~550k populated places.
_VILLAGES_DIR = _REPO_ROOT / "packages" / "india-geo" / "villages"
_VILLAGE_KINDS = {"v": "village", "t": "town"}
_MAX_VILLAGES = 12_000


@lru_cache
def _places() -> dict:
    with _PLACES_DB.open(encoding="utf-8") as fh:
        return json.load(fh)


@router.get("/states")
def states() -> dict:
    """All Indian states/UTs for the layered location finder."""
    return {"states": [s["name"] for s in _places()["states"]]}


@router.get("/districts")
def districts(state: str = Query(min_length=2, max_length=80)) -> dict:
    """Districts of one state/UT."""
    for s in _places()["states"]:
        if s["name"].lower() == state.strip().lower():
            return {"state": s["name"], "districts": s["districts"]}
    raise HTTPException(status_code=404, detail=f"Unknown state '{state}'")


async def _nominatim(params: dict) -> list[dict]:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(NOMINATIM_SEARCH, params=params, headers=_HEADERS)
        resp.raise_for_status()
        return resp.json()


def _to_results(items: list[dict]) -> list[dict]:
    results: list[dict] = []
    for item in items:
        try:
            bbox = [float(v) for v in item.get("boundingbox", [])]
        except (TypeError, ValueError):
            bbox = []
        results.append({
            "display_name": item.get("display_name"),
            "lat": float(item["lat"]),
            "lon": float(item["lon"]),
            "type": item.get("type"),
            # Nominatim bbox order: [south, north, west, east]
            "bbox": bbox if len(bbox) == 4 else None,
        })
    return results


async def _resolve_admin(q: str) -> dict | None:
    """Resolve an admin area (district/state) to its OSM relation + bbox.

    The relation id drives the Overpass area query; the bbox drives the
    bounded Nominatim retry. Cached 30 days — district boundaries don't move.
    """
    key = f"geoadmin:{q.lower()}"
    cached = await cache.get(key)
    if cached is not None:
        return cached or None

    params = {"q": q, "format": "jsonv2", "limit": "5", "countrycodes": "in",
              "addressdetails": "0"}
    try:
        items = await _nominatim(params)
    except (httpx.HTTPError, ValueError):
        return None
    best = next((i for i in items if i.get("osm_type") == "relation"),
                items[0] if items else None)
    if best is None:
        await cache.set(key, {}, ttl_seconds=86_400)
        return None
    try:
        bbox = [float(v) for v in best.get("boundingbox", [])]
    except (TypeError, ValueError):
        bbox = []
    out = {
        "osm_type": best.get("osm_type"),
        "osm_id": int(best["osm_id"]),
        "bbox": bbox if len(bbox) == 4 else None,  # [S, N, W, E]
    }
    await cache.set(key, out, ttl_seconds=30 * 86_400)
    return out


@lru_cache(maxsize=6)
def _state_villages(state: str) -> list | None:
    """Load the bundled village list of one state (name, lat, lon, kind)."""
    # canonicalise against the bundled state list so casing/spacing don't matter
    canonical = next((s["name"] for s in _places()["states"]
                      if s["name"].lower() == state.strip().lower()), state.strip())
    slug = re.sub(r"[^a-z0-9]+", "-", canonical.lower()).strip("-")
    path = _VILLAGES_DIR / f"{slug}.json.gz"
    if not path.exists():
        return None
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)["villages"]


async def _overpass(query: str) -> list[dict] | None:
    """Run an Overpass QL query against the mirror list; None if all fail."""
    for url in OVERPASS_URLS:
        try:
            async with httpx.AsyncClient(timeout=50) as client:
                resp = await client.post(url, data={"data": query}, headers=_HEADERS)
                resp.raise_for_status()
                return resp.json().get("elements", [])
        except (httpx.HTTPError, ValueError):
            continue
    return None


@router.get("/villages")
async def villages(state: str = Query(min_length=2, max_length=80),
                   district: str = Query(min_length=2, max_length=80)) -> dict:
    """Every named village/town of a district, with coordinates so the map
    can jump straight to a picked village without another geocoding trip.

    Primary source: the bundled GeoNames index (~550k Indian places),
    filtered by the district's bounding box — bbox filtering keeps working
    for districts carved out after the source data's admin split (the box
    just also catches some villages of neighbouring districts, which is
    harmless in a picker). Falls back to live OSM Overpass, then to an
    ``error`` payload (HTTP 200) so the UI degrades to free-text search.
    """
    fallback = {"district": district, "villages": [],
                "error": "Village directory unavailable; type the name and search"}

    key = f"geovillages2:{state.strip().lower()}:{district.strip().lower()}"
    cached = await cache.get(key)
    if cached is not None:
        return cached

    admin = await _resolve_admin(f"{district.strip()} district, {state.strip()}, India")

    pool = _state_villages(state)
    if pool and admin and admin.get("bbox"):
        s, n, w, e = admin["bbox"]
        found = [{"name": v[0], "lat": v[1], "lon": v[2],
                  "kind": _VILLAGE_KINDS.get(v[3], "village")}
                 for v in pool if s <= v[1] <= n and w <= v[2] <= e]
        if found:
            found = found[:_MAX_VILLAGES]
            out = {"district": district.strip(), "count": len(found),
                   "villages": found, "source": "GeoNames (CC BY 4.0)"}
            await cache.set(key, out, ttl_seconds=30 * 86_400)
            return out

    # ---- live OSM fallback (unknown state name / bbox unresolved) ----
    if admin is None:
        return fallback
    if admin.get("osm_type") == "relation":
        # 3600000000 + relation id is Overpass's derived-area id scheme.
        scope = (f'area(id:{3_600_000_000 + admin["osm_id"]})->.d;\n'
                 f"node{_PLACE_FILTER}(area.d);")
    elif admin.get("bbox"):
        s, n, w, e = admin["bbox"]
        scope = f"node{_PLACE_FILTER}({s},{w},{n},{e});"
    else:
        return fallback

    elements = await _overpass(f"[out:json][timeout:45];\n{scope}\nout body 6000;")
    if elements is None:
        return fallback

    seen: dict[str, dict] = {}
    for el in elements:
        tags = el.get("tags", {})
        name = (tags.get("name:en") or tags.get("name") or "").strip()
        if not name or el.get("lat") is None or el.get("lon") is None:
            continue
        seen.setdefault(name.lower(), {
            "name": name,
            "lat": round(float(el["lat"]), 5),
            "lon": round(float(el["lon"]), 5),
            "kind": tags.get("place"),
        })
    out = {"district": district.strip(), "count": len(seen),
           "villages": sorted(seen.values(), key=lambda v: v["name"].lower())}
    # An empty (but successful) directory may mean a mis-resolved district —
    # cache it briefly so a fix upstream shows up within a day.
    await cache.set(key, out, ttl_seconds=30 * 86_400 if seen else 86_400)
    return out


@router.get("/search")
async def search(q: str = Query(min_length=2, max_length=200),
                 limit: int = Query(default=5, ge=1, le=10),
                 state: str | None = Query(default=None, max_length=80),
                 district: str | None = Query(default=None, max_length=80),
                 india_only: bool = True) -> dict:
    """Free-text place search. When ``state``/``district`` are given the query
    is scoped to them, so tiny villages resolve instead of drowning in
    same-named places elsewhere. If the scoped text query finds nothing, we
    retry restricted to the district's bounding box — that catches hamlets
    whose OSM address hierarchy doesn't textually match the district name."""
    scoped_q = ", ".join(p for p in [q.strip(), (district or "").strip(),
                                     (state or "").strip()] if p)
    key = f"geosearch2:{scoped_q.lower()}:{limit}:{india_only}"
    cached = await cache.get(key)
    if cached is not None:
        return cached

    params = {
        "q": scoped_q,
        "format": "jsonv2",
        "limit": str(limit),
        "addressdetails": "0",
    }
    if india_only:
        params["countrycodes"] = "in"

    try:
        results = _to_results(await _nominatim(params))
        if not results and (state or district):
            admin_q = (f"{district.strip()} district, {(state or '').strip()}, India"
                       if district else f"{(state or '').strip()}, India")
            admin = await _resolve_admin(admin_q)
            if admin and admin.get("bbox"):
                s, n, w, e = admin["bbox"]
                bounded = {
                    "q": q.strip(),
                    "format": "jsonv2",
                    "limit": str(limit),
                    "addressdetails": "0",
                    # Nominatim viewbox: left(top-right-bottom) = W,N,E,S
                    "viewbox": f"{w},{n},{e},{s}",
                    "bounded": "1",
                }
                if india_only:
                    bounded["countrycodes"] = "in"
                results = _to_results(await _nominatim(bounded))
    except (httpx.HTTPError, ValueError, KeyError):
        return {"query": q, "results": [], "error": "Search unavailable; try again"}

    out = {"query": q, "results": results}
    await cache.set(key, out, ttl_seconds=7 * 86_400)
    return out
