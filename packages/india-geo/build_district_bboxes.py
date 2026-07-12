"""Build the offline district bounding-box index from OSM Nominatim.

Produces district-bboxes.json:
    {"source": "OSM Nominatim (ODbL)",
     "states": {"<State>": {"<District>": [south, north, west, east]}}}

The API uses these bboxes to slice the bundled GeoNames village index per
district WITHOUT any live geocoding call, so the village picker works even
when nominatim.openstreetmap.org is slow, rate-limited or unreachable.

Run (resumable — re-running only fetches districts still missing):
    python build_district_bboxes.py

Respects the Nominatim usage policy: 1 request/second, identifying UA.
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "district-bboxes.json"
SEARCH = "https://nominatim.openstreetmap.org/search"
UA = {"User-Agent": "SmartFarm/1.0 (precision-farm-planning; one-time data build)"}

# A real Indian district never spans more than ~4 degrees (Kachchh, Leh are
# the largest). Anything bigger means Nominatim matched the state/country.
MAX_SPAN_DEG = 4.5


def fetch(query: str) -> list[dict]:
    params = urllib.parse.urlencode({
        "q": query, "format": "jsonv2", "limit": "5",
        "countrycodes": "in", "addressdetails": "0",
    })
    req = urllib.request.Request(f"{SEARCH}?{params}", headers=UA)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def bbox_of(items: list[dict]) -> list[float] | None:
    # Prefer the admin boundary relation; fall back to the top hit.
    ranked = sorted(items, key=lambda i: (i.get("osm_type") != "relation",))
    for item in ranked:
        try:
            s, n, w, e = (float(v) for v in item.get("boundingbox", []))
        except (TypeError, ValueError):
            continue
        if 0 < n - s <= MAX_SPAN_DEG and 0 < e - w <= MAX_SPAN_DEG:
            return [round(s, 4), round(n, 4), round(w, 4), round(e, 4)]
    return None


def main() -> None:
    ours = json.loads((HERE / "states-districts.json").read_text(encoding="utf-8"))
    out = {"source": "OSM Nominatim (ODbL)", "states": {}}
    if OUT.exists():
        out = json.loads(OUT.read_text(encoding="utf-8"))
        out.setdefault("states", {})

    total = sum(len(s["districts"]) for s in ours["states"])
    done = failed = 0
    for state in ours["states"]:
        sname = state["name"]
        got = out["states"].setdefault(sname, {})
        for district in state["districts"]:
            if got.get(district):
                done += 1
                continue
            queries = [f"{district} district, {sname}, India",
                       f"{district}, {sname}, India"]
            bbox = None
            for q in queries:
                try:
                    bbox = bbox_of(fetch(q))
                except Exception as exc:  # noqa: BLE001 - keep the build going
                    print(f"  !! {district}, {sname}: {exc}")
                time.sleep(1.1)  # Nominatim policy: max 1 req/s
                if bbox:
                    break
            if bbox:
                got[district] = bbox
                done += 1
            else:
                failed += 1
                print(f"  -- no bbox: {district}, {sname}")
            if (done + failed) % 25 == 0:
                OUT.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
                print(f"{done + failed}/{total} ({failed} missing)")
        OUT.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"finished: {done}/{total} resolved, {failed} missing -> {OUT.name}")


if __name__ == "__main__":
    main()
