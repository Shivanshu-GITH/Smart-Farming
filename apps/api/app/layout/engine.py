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

import numpy as np
import shapely
from shapely import affinity
from shapely.geometry import Point
from shapely.prepared import prep

from app.agronomy import counts
from app.agronomy.catalogue import get_crop, layers, usable_fraction
from app.core.geo import (centroid_latlon, geodesic_area_m2, geodesic_perimeter_m,
                          polygon_from_geojson)

# Rendering cap per crop. Grids denser than this are uniformly thinned so the
# display stays representative of the whole field.
MAX_POINTS = 3500

SYSTEMS = ("monoculture", "intercrop", "multilayer")

# Grid-position search (geometry-aware mode) only for widely spaced crops: on
# real smallholder fields it adds up to ~10% more tree positions on the
# smallest plots, and <1% for row crops, where it isn't worth the work.
WIDE_SPACING_M = 1.0
_PHASES = (0.0, 1 / 3, 2 / 3)


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


# --- geometry-aware helpers (metres, local frame) ------------------------------

def _local_frame(polygon):
    """Polygon in a local metric frame centred on it, plus point converters."""
    lon0, lat0 = polygon.centroid.x, polygon.centroid.y
    m_lon, m_lat = _meters_per_degree(lat0)

    def fwd(lon, lat):
        return (np.asarray(lon) - lon0) * m_lon, (np.asarray(lat) - lat0) * m_lat

    def inv(x, y):
        return np.asarray(x) / m_lon + lon0, np.asarray(y) / m_lat + lat0

    local = shapely.transform(polygon, lambda xy: np.column_stack(fwd(xy[:, 0], xy[:, 1])))
    return local, fwd, inv


def _mrr_angle(local) -> float:
    """Orientation of the long side of the minimum rotated rectangle, [0, 180)."""
    xy = np.asarray(shapely.minimum_rotated_rectangle(local).exterior.coords)[:4]
    e1, e2 = xy[1] - xy[0], xy[2] - xy[1]
    long_e = e1 if np.hypot(*e1) >= np.hypot(*e2) else e2
    return math.degrees(math.atan2(long_e[1], long_e[0])) % 180.0


def _grid_in(target, frame, plant: float, row: float, theta: float,
             fx: float, fy: float) -> np.ndarray:
    """Staggered grid laid over `frame`'s bounds (as the engine lays it), rotated
    by theta and shifted by (fx, fy) of a step; returns the points in `target`."""
    F = affinity.rotate(frame, -theta, origin=(0, 0)) if theta else frame
    T = affinity.rotate(target, -theta, origin=(0, 0)) if theta else target
    if T.is_empty:
        return np.empty((0, 2))
    minx, miny, maxx, maxy = F.bounds
    ys = miny + fy * row + np.arange(int((maxy - miny) / row) + 2) * row
    ys = ys[ys <= maxy]
    xs = minx + fx * plant + np.arange(int((maxx - minx) / plant) + 2) * plant
    X = np.broadcast_to(xs, (len(ys), len(xs))).copy()
    X[1::2] += plant / 2
    Y = np.broadcast_to(ys[:, None], X.shape)
    keep = X <= maxx
    X, Y = X[keep], Y[keep]
    shapely.prepare(T)
    inside = shapely.contains_xy(T, X, Y)
    pts = np.column_stack([X[inside], Y[inside]])
    if theta:
        c, s = math.cos(math.radians(theta)), math.sin(math.radians(theta))
        pts = pts @ np.array([[c, s], [-s, c]])
    return pts


def _place_monoculture_geo(polygon, crop: dict):
    """Monoculture with the border setback and, for widely spaced crops, the
    best of the default grid, grid shifts and MRR-aligned grids (never fewer
    plants than the default grid). Returns (points, stride, orientation)."""
    local, _fwd, inv = _local_frame(polygon)
    plant, row = crop["spacing_cm"]["plant"] / 100.0, crop["spacing_cm"]["row"] / 100.0
    inner = local.buffer(-counts.setback_m(crop))
    cells = inner.area / (plant * row) if not inner.is_empty else 0
    stride = 1 if cells <= MAX_POINTS else math.ceil(math.sqrt(cells / MAX_POINTS))
    cands = [(0.0, 0.0, 0.0)]
    if stride == 1 and min(plant, row) >= WIDE_SPACING_M:
        a = _mrr_angle(local)
        cands += [(t, fx, fy) for t in (0.0, a, (a + 90) % 180)
                  for fx in _PHASES for fy in _PHASES][1:]
    best, theta = None, 0.0
    for t, fx, fy in cands:
        pts = _grid_in(inner, local, plant * stride, row * stride, t, fx, fy)
        if best is None or len(pts) > len(best):   # ties keep the default grid
            best, theta = pts, t
    lon, lat = inv(best[:, 0], best[:, 1])
    return [(round(float(x), 7), round(float(y), 7)) for x, y in zip(lon, lat)], stride, theta


def _apply_setback(polygon, placed: list) -> list:
    """Drop positions closer than the crop's setback to the field boundary."""
    local, fwd, _inv = _local_frame(polygon)
    out = []
    for crop, pts, stride, share in placed:
        if pts:
            inner = local.buffer(-counts.setback_m(crop))
            if inner.is_empty:
                pts = []
            else:
                arr = np.asarray(pts)
                x, y = fwd(arr[:, 0], arr[:, 1])
                shapely.prepare(inner)
                keep = shapely.contains_xy(inner, x, y)
                pts = [p for p, k in zip(pts, keep) if k]
        out.append((crop, pts, stride, share))
    return out


# --- system-specific placement -------------------------------------------------

def _place_monoculture(polygon, crops: list[dict], lat: float):
    crop = crops[0]
    sx, sy = _crop_steps_deg(crop, lat)
    s = _thin_stride(polygon, sx, sy)
    pts = _scan(polygon, sx * s, sy * s, 0.0, 0.0, stagger=True)
    return [(crop, pts, s, 1.0)]


# Multilayer working corridors: an E-W walking/drip path of PATH_M every
# BLOCK_M of field depth, rendered as visible gaps in the understory.
_BLOCK_M = 12.0
_PATH_M = 1.2


def _place_multilayer(polygon, crops: list[dict], lat: float):
    """Canopy first on a square grid; lower layers interleave between trees and
    leave walking corridors every ~12 m."""
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
        if not is_canopy:
            tree_ctx = tree

            def keep(x: float, y: float, tree_ctx=tree_ctx) -> bool:
                # walking corridor bands (canopy trees span them; understory not)
                if ((y - miny) * m_lat) % _BLOCK_M < _PATH_M:
                    return False
                if tree_ctx is not None:
                    dx = (x - tree_ctx["ox"]) % tree_ctx["sx"]
                    dx = min(dx, tree_ctx["sx"] - dx) * m_lon
                    dy = (y - tree_ctx["oy"]) % tree_ctx["sy"]
                    dy = min(dy, tree_ctx["sy"] - dy) * m_lat
                    if dx * dx + dy * dy < tree_ctx["clear_m"] ** 2:
                        return False
                return True

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
                    system: str = "multilayer", geometry_aware: bool = True) -> dict:
    """Plant positions + counts for a field.

    geometry_aware (default): plant centres keep a border setback of half a row
    spacing; widely spaced monocultures get the best grid position/orientation;
    counts are what the layout actually holds (the closed-form geometric
    estimate when the display is thinned). geometry_aware=False reproduces the
    original engine — area x usable_fraction counts, no setback — so the
    research evaluating that behaviour stays reproducible.
    """
    if system not in SYSTEMS:
        raise ValueError(f"Unknown farming system '{system}'")

    polygon = polygon_from_geojson(geometry)
    lat, _ = centroid_latlon(polygon)
    # plant counts are computed on the PLANTING area (gross minus bunds, paths
    # and irrigation space for this system), not the gross polygon area
    fraction = usable_fraction(system)
    gross_m2 = geodesic_area_m2(polygon)
    perimeter_m = geodesic_perimeter_m(polygon)
    area_m2 = gross_m2 * fraction

    crops = [c for c in (get_crop(cid) for cid in crop_ids) if c is not None]
    if system == "monoculture":
        crops = crops[:1]

    orientation = 0.0
    if not crops:
        placed = []
    elif system == "monoculture":
        if geometry_aware:
            pts, stride, orientation = _place_monoculture_geo(polygon, crops[0])
            placed = [(crops[0], pts, stride, 1.0)]
        else:
            placed = _place_monoculture(polygon, crops, lat)
    elif system == "intercrop":
        placed = _place_intercrop(polygon, crops, lat)
    else:
        placed = _place_multilayer(polygon, crops, lat)
    if geometry_aware and system != "monoculture":
        placed = _apply_setback(polygon, placed)

    def count(crop, pts, stride, share) -> tuple[int, str]:
        if not geometry_aware:
            return _estimate_count(area_m2, crop, share), "area-estimate"
        if stride == 1:
            return len(pts), "layout"
        if system == "multilayer":
            # corridors and tree clearance are in the thinned layout too
            return len(pts) * stride * stride, "layout-scaled"
        return counts.geometric_count(crop, gross_m2, perimeter_m, share), "geometric-estimate"

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
        n, method = count(crop, pts, stride, share)
        per_crop.append({
            "crop_id": crop["id"],
            "name": crop["name"],
            "layer": crop["layer"],
            "plant_count": n,
            "count_method": method,
            "rendered_points": len(pts),
            "spacing_cm": crop["spacing_cm"],
        })

    heatmap = _density_heatmap(polygon, features)

    return {
        "type": "layout",
        "system": system,
        "geometry_aware": geometry_aware,
        "setback_fraction_of_row": counts.SETBACK_FRAC if geometry_aware else 0.0,
        "row_orientation_deg": round(orientation, 1),
        "usable_fraction": fraction,
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
