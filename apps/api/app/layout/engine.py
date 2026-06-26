"""Spatial planting-layout engine — the signature feature.

Given a field polygon and one or more crops, it places each plant as a point
inside the polygon at that crop's row/plant spacing, clipped to the boundary.
For multi-layer farming, each crop occupies its own layer and its grid is
phase-offset so layers interleave instead of stacking on the same spot.

Also produces a coarse density heatmap (plants per grid cell) for the UI.

Coordinates are WGS84 lon/lat. Spacing in metres is converted to degrees at
the field's latitude — accurate enough at field scale (sub-km).
"""
from __future__ import annotations

import math

from shapely.geometry import Point

from app.agronomy.catalogue import get_crop
from app.core.geo import centroid_latlon, polygon_from_geojson

MAX_POINTS = 6000  # safety cap so huge fields don't explode the response


def _meters_per_degree(lat: float) -> tuple[float, float]:
    """(meters-per-degree-lon, meters-per-degree-lat) at a latitude."""
    lat_rad = math.radians(lat)
    m_per_deg_lat = 111_132.92 - 559.82 * math.cos(2 * lat_rad)
    m_per_deg_lon = 111_412.84 * math.cos(lat_rad) - 93.5 * math.cos(3 * lat_rad)
    return m_per_deg_lon, m_per_deg_lat


def _grid_points(polygon, row_m: float, plant_m: float, lat: float,
                 phase: float) -> list[tuple[float, float]]:
    m_lon, m_lat = _meters_per_degree(lat)
    step_x = plant_m / m_lon   # plant spacing along rows (E-W)
    step_y = row_m / m_lat     # row spacing (N-S)
    minx, miny, maxx, maxy = polygon.bounds

    # phase offset interleaves layers (0..1 of a cell)
    ox = step_x * phase
    oy = step_y * phase

    pts: list[tuple[float, float]] = []
    y = miny + oy
    while y <= maxy:
        x = minx + ox
        while x <= maxx:
            if polygon.contains(Point(x, y)):
                pts.append((round(x, 7), round(y, 7)))
                if len(pts) >= MAX_POINTS:
                    return pts
            x += step_x
        y += step_y
    return pts


def generate_layout(geometry: dict, crop_ids: list[str]) -> dict:
    polygon = polygon_from_geojson(geometry)
    lat, _ = centroid_latlon(polygon)

    features: list[dict] = []
    per_crop: list[dict] = []
    truncated = False

    n = max(len(crop_ids), 1)
    for idx, crop_id in enumerate(crop_ids):
        crop = get_crop(crop_id)
        if crop is None:
            continue
        row_m = crop["spacing_cm"]["row"] / 100.0
        plant_m = crop["spacing_cm"]["plant"] / 100.0
        phase = idx / n  # spread layers across the cell
        pts = _grid_points(polygon, row_m, plant_m, lat, phase)
        if len(pts) >= MAX_POINTS:
            truncated = True

        for (x, y) in pts:
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [x, y]},
                "properties": {
                    "crop_id": crop_id,
                    "name": crop["name"],
                    "layer": crop["layer"],
                },
            })
        per_crop.append({
            "crop_id": crop_id,
            "name": crop["name"],
            "layer": crop["layer"],
            "plant_count": len(pts),
            "spacing_cm": crop["spacing_cm"],
        })

    heatmap = _density_heatmap(polygon, features)

    return {
        "type": "layout",
        "crops": per_crop,
        "total_plants": len(features),
        "truncated": truncated,
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
