"""Spatial planting-layout engine — the signature feature.

Given a field polygon and one or more crops, places each plant as a point
inside the polygon at that crop's row/plant spacing, clipped to the boundary.

Supports three farming systems:
- ``monoculture``  — one crop on a uniform staggered grid over the whole field.
- ``intercrop``    — crops alternate in row bands (e.g. 2 rows A : 1 row B).
- ``multilayer``   — each crop occupies its vertical layer; the canopy (top)
  crop is placed first on a square orchard grid and lower layers fill the
  space between trees, keeping a clearance around each trunk.

Rendering honesty: dense grids are *uniformly thinned* for display (never
truncated mid-scan, which used to pile points into one corner). ``plant_count``
is always the agronomic estimate from area/spacing; ``rendered_points`` is how
many symbols the map shows.

Coordinates are WGS84 lon/lat. Spacing in metres is converted to degrees at
the field's latitude — accurate enough at field scale (sub-km).
"""
from __future__ import annotations

import math
from typing import Callable

from shapely.geometry import Point
from shapely.prepared import prep

from app.agronomy.catalogue import get_crop, layers
from app.core.geo import centroid_latlon, geodesic_area_m2, polygon_from_geojson

# Rendering cap per crop. Grids denser than this are uniformly thinned so the
# display stays representative of the whole field.
MAX_POINTS = 3500

SYSTEMS = ("monoculture", "intercrop", "multilayer")


def _meters_per_degree(lat: float) -> tuple[float, float]:
    """(meters-per-degree-lon, meters-per-degree-lat) at a latitude."""
    lat_rad = math.radians(lat)
    m_per_deg_lat = 111_132.92 - 559.82 * math.cos(2 * lat_rad)
    m_per_deg_lon = 111_412.84 * math.cos(lat_rad) - 93.5 * math.cos(3 * lat_rad)
    return m_per_deg_lon, m_per_deg_lat


def _crop_steps_deg(crop: dict, lat: float) -> tuple[float, float]:
    """(step_x, step_y) in degrees for a crop's plant/row spacing."""
    m_lon, m_lat = _meters_per_degree(lat)
    plant_m = crop["spacing_cm"]["plant"] / 100.0
    row_m = crop["spacing_cm"]["row"] / 100.0
    return plant_m / m_lon, row_m / m_lat


def _thin_stride(polygon, step_x: float, step_y: float) -> int:
    """Uniform decimation factor keeping rendered points under MAX_POINTS."""
    minx, miny, maxx, maxy = polygon.bounds
    nx = max(1, int((maxx - minx) / step_x) + 1)
    ny = max(1, int((maxy - miny) / step_y) + 1)
    cells = nx * ny
    if cells <= MAX_POINTS:
        return 1
    return math.ceil(math.sqrt(cells / MAX_POINTS))


def _scan(polygon, step_x: float, step_y: float, ox: float, oy: float,
          stagger: bool, keep: Callable[[float, float], bool] | None = None,
          ) -> list[tuple[float, float]]:
    """All in-polygon grid points; alternate rows offset by half a step when
    ``stagger`` is on (natural planting look). ``keep`` can veto points
    (used for clearance around canopy trees)."""
    minx, miny, maxx, maxy = polygon.bounds
    prepared = prep(polygon)
    pts: list[tuple[float, float]] = []
    j = 0
    y = miny + oy
    while y <= maxy:
        x = minx + ox + (step_x / 2 if (stagger and j % 2) else 0.0)
        while x <= maxx:
            if prepared.contains(Point(x, y)) and (keep is None or keep(x, y)):
                pts.append((round(x, 7), round(y, 7)))
            x += step_x
        y += step_y
        j += 1
    return pts


def _estimate_count(area_m2: float, crop: dict, share: float = 1.0) -> int:
    plant_m = crop["spacing_cm"]["plant"] / 100.0
    row_m = crop["spacing_cm"]["row"] / 100.0
    if plant_m <= 0 or row_m <= 0:
        return 0
    return int(area_m2 * share / (plant_m * row_m))


def _layer_rank(crop: dict) -> int:
    return layers().get(crop["layer"], {}).get("order", 0)


# --- system-specific placement -------------------------------------------------

def _place_monoculture(polygon, crops: list[dict], lat: float):
    crop = crops[0]
    sx, sy = _crop_steps_deg(crop, lat)
    s = _thin_stride(polygon, sx, sy)
    pts = _scan(polygon, sx * s, sy * s, 0.0, 0.0, stagger=True)
    return [(crop, pts, s, 1.0)]


def _place_multilayer(polygon, crops: list[dict], lat: float):
    """Canopy first on a square grid; lower layers interleave between trees."""
    ordered = sorted(crops, key=_layer_rank, reverse=True)  # top layer first
    m_lon, m_lat = _meters_per_degree(lat)
    minx, miny, _, _ = polygon.bounds

    tree: dict | None = None  # rendered canopy grid, for clearance vetoes
    out = []
    n = max(len(ordered), 1)
    for idx, crop in enumerate(ordered):
        sx, sy = _crop_steps_deg(crop, lat)
        s = _thin_stride(polygon, sx, sy)
        sx, sy = sx * s, sy * s
        is_canopy = crop["layer"] == "top"
        # phase-offset lower layers so grids interleave rather than stack
        phase = (idx / n) if not is_canopy else 0.0
        ox, oy = sx * phase, sy * phase

        keep = None
        if tree is not None and not is_canopy:
            tsx, tsy = tree["sx"], tree["sy"]
            tox, toy = tree["ox"], tree["oy"]
            clear2 = tree["clear_m"] ** 2

            def keep(x: float, y: float,
                     tsx=tsx, tsy=tsy, tox=tox, toy=toy, clear2=clear2) -> bool:
                dx = (x - tox) % tsx
                dx = min(dx, tsx - dx) * m_lon
                dy = (y - toy) % tsy
                dy = min(dy, tsy - dy) * m_lat
                return dx * dx + dy * dy >= clear2

        pts = _scan(polygon, sx, sy, ox, oy, stagger=not is_canopy, keep=keep)

        if is_canopy and tree is None:
            spacing_m = min(crop["spacing_cm"]["row"], crop["spacing_cm"]["plant"]) / 100.0
            tree = {
                "sx": sx, "sy": sy,
                "ox": minx + ox, "oy": miny + oy,
                # keep understory off the trunks, but never carve out huge holes
                "clear_m": max(0.3, min(1.5, 0.25 * spacing_m * s)),
            }
        out.append((crop, pts, s, 1.0))
    return out


def _place_intercrop(polygon, crops: list[dict], lat: float):
    """Row-band alternation. Two crops default to 2:1 (main : companion),
    a classic Indian intercropping ratio; three crops go 1:1:1."""
    ratios = [2, 1] if len(crops) == 2 else [1] * len(crops)
    cycle: list[int] = []
    for i, r in enumerate(ratios[: len(crops)]):
        cycle.extend([i] * r)
    total_rows = len(cycle)
    shares = [cycle.count(i) / total_rows for i in range(len(crops))]

    steps = [_crop_steps_deg(c, lat) for c in crops]
    # one thinning factor for the whole pattern, from the densest participant
    avg_sx = sum(s[0] for s in steps) / len(steps)
    avg_sy = sum(s[1] for s in steps) / len(steps)
    stride = _thin_stride(polygon, avg_sx, avg_sy)

    minx, miny, maxx, maxy = polygon.bounds
    prepared = prep(polygon)
    per_crop_pts: list[list[tuple[float, float]]] = [[] for _ in crops]

    y = miny
    j = 0
    while y <= maxy:
        ci = cycle[j % total_rows]
        step_x = steps[ci][0] * stride
        x = minx + (step_x / 2 if j % 2 else 0.0)
        while x <= maxx:
            if prepared.contains(Point(x, y)):
                per_crop_pts[ci].append((round(x, 7), round(y, 7)))
            x += step_x
        # row gap to the next band: average of this and the next crop's row spacing
        nci = cycle[(j + 1) % total_rows]
        y += ((steps[ci][1] + steps[nci][1]) / 2.0) * stride
        j += 1

    return [(crops[i], per_crop_pts[i], stride, shares[i]) for i in range(len(crops))]


# --- public API -----------------------------------------------------------------

def generate_layout(geometry: dict, crop_ids: list[str],
                    system: str = "multilayer") -> dict:
    if system not in SYSTEMS:
        raise ValueError(f"Unknown farming system '{system}'")

    polygon = polygon_from_geojson(geometry)
    lat, _ = centroid_latlon(polygon)
    area_m2 = geodesic_area_m2(polygon)

    crops = [c for c in (get_crop(cid) for cid in crop_ids) if c is not None]
    if system == "monoculture":
        crops = crops[:1]

    if not crops:
        placed = []
    elif system == "monoculture":
        placed = _place_monoculture(polygon, crops, lat)
    elif system == "intercrop":
        placed = _place_intercrop(polygon, crops, lat)
    else:
        placed = _place_multilayer(polygon, crops, lat)

    features: list[dict] = []
    per_crop: list[dict] = []
    sampled = False
    for crop, pts, stride, share in placed:
        if stride > 1:
            sampled = True
        for (x, y) in pts:
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [x, y]},
                "properties": {
                    "crop_id": crop["id"],
                    "name": crop["name"],
                    "layer": crop["layer"],
                },
            })
        per_crop.append({
            "crop_id": crop["id"],
            "name": crop["name"],
            "layer": crop["layer"],
            "plant_count": _estimate_count(area_m2, crop, share),
            "rendered_points": len(pts),
            "spacing_cm": crop["spacing_cm"],
        })

    heatmap = _density_heatmap(polygon, features)

    return {
        "type": "layout",
        "system": system,
        "crops": per_crop,
        "total_plants": sum(c["plant_count"] for c in per_crop),
        "rendered_points": len(features),
        "truncated": sampled,  # kept name for API compat: display is sampled
        "planting_points": {"type": "FeatureCollection", "features": features},
        "heatmap": heatmap,
    }


def _density_heatmap(polygon, features: list[dict], grid: int = 24) -> dict:
    """Bucket planting points into a grid of cells (plants per cell)."""
    minx, miny, maxx, maxy = polygon.bounds
    w = (maxx - minx) / grid or 1e-9
    h = (maxy - miny) / grid or 1e-9
    counts: dict[tuple[int, int], int] = {}
    for f in features:
        x, y = f["geometry"]["coordinates"]
        cx = min(int((x - minx) / w), grid - 1)
        cy = min(int((y - miny) / h), grid - 1)
        counts[(cx, cy)] = counts.get((cx, cy), 0) + 1

    max_count = max(counts.values(), default=0)
    cells = []
    for (cx, cy), c in counts.items():
        cells.append({
            "bbox": [round(minx + cx * w, 7), round(miny + cy * h, 7),
                     round(minx + (cx + 1) * w, 7), round(miny + (cy + 1) * h, 7)],
            "count": c,
            "intensity": round(c / max_count, 3) if max_count else 0,
        })
    return {"grid": grid, "max_count": max_count, "cells": cells}
