"""Geospatial helpers shared across modules.

Areas/lengths are computed on the WGS84 ellipsoid with pyproj's geodesic
routines, so results are accurate anywhere in India without picking a local
projection.
"""
from __future__ import annotations

from pyproj import Geod
from shapely.geometry import Polygon, shape

_GEOD = Geod(ellps="WGS84")

# Indian-friendly area units
SQM_PER_HECTARE = 10_000.0
SQM_PER_ACRE = 4_046.8564224
SQM_PER_GUNTHA = 101.17141056  # 1 guntha = 1/40 acre


def polygon_from_geojson(geometry: dict) -> Polygon:
    geom = shape(geometry)
    if geom.geom_type != "Polygon":
        raise ValueError(f"Expected a Polygon, got {geom.geom_type}")
    if not geom.is_valid:
        geom = geom.buffer(0)  # fix self-intersections
    return geom


def geodesic_area_m2(polygon: Polygon) -> float:
    """Absolute geodesic area in square metres."""
    lons, lats = polygon.exterior.coords.xy
    area, _ = _GEOD.polygon_area_perimeter(list(lons), list(lats))
    return abs(area)


def geodesic_perimeter_m(polygon: Polygon) -> float:
    lons, lats = polygon.exterior.coords.xy
    _, perimeter = _GEOD.polygon_area_perimeter(list(lons), list(lats))
    return abs(perimeter)


def area_breakdown(area_m2: float) -> dict[str, float]:
    return {
        "square_meters": round(area_m2, 2),
        "hectares": round(area_m2 / SQM_PER_HECTARE, 4),
        "acres": round(area_m2 / SQM_PER_ACRE, 4),
        "guntha": round(area_m2 / SQM_PER_GUNTHA, 2),
    }


def centroid_latlon(polygon: Polygon) -> tuple[float, float]:
    c = polygon.centroid
    return c.y, c.x  # (lat, lon)
