import math

import pytest

from app.core.geo import (
    SQM_PER_ACRE,
    SQM_PER_GUNTHA,
    SQM_PER_HECTARE,
    area_breakdown,
    centroid_latlon,
    geodesic_area_m2,
    polygon_from_geojson,
)


def _square(lat: float, lon: float, d: float) -> dict:
    return {"type": "Polygon", "coordinates": [[
        [lon, lat], [lon + d, lat], [lon + d, lat + d], [lon, lat + d], [lon, lat],
    ]]}


def test_area_breakdown_conversions_are_consistent():
    b = area_breakdown(10_000.0)
    # outputs are rounded (ha 4dp, acres 4dp, guntha 2dp), so use abs tolerance
    assert b["hectares"] == pytest.approx(1.0, abs=1e-4)
    assert b["acres"] == pytest.approx(10_000 / SQM_PER_ACRE, abs=1e-2)
    assert b["guntha"] == pytest.approx(10_000 / SQM_PER_GUNTHA, abs=1e-2)
    # 1 hectare ~= 2.47 acres ~= 98.8 guntha (40 guntha = 1 acre)
    assert 2.4 < b["acres"] < 2.5
    assert 98 < b["guntha"] < 100


def test_geodesic_area_of_small_square_is_plausible():
    poly = polygon_from_geojson(_square(16.5, 80.6, 0.001))
    area = geodesic_area_m2(poly)
    # ~0.001 deg square near 16.5N is roughly 100-115 m a side
    assert 9_000 < area < 15_000


def test_centroid_is_inside_and_ordered_latlon():
    poly = polygon_from_geojson(_square(16.5, 80.6, 0.002))
    lat, lon = centroid_latlon(poly)
    assert lat == pytest.approx(16.501, abs=1e-3)
    assert lon == pytest.approx(80.601, abs=1e-3)


def test_non_polygon_rejected():
    with pytest.raises(ValueError):
        polygon_from_geojson({"type": "Point", "coordinates": [80.6, 16.5]})


def test_self_intersecting_polygon_is_repaired_not_raised():
    # bow-tie ring; buffer(0) should fix it
    bowtie = {"type": "Polygon", "coordinates": [[
        [0, 0], [1, 1], [1, 0], [0, 1], [0, 0],
    ]]}
    poly = polygon_from_geojson(bowtie)
    assert poly.is_valid


def test_hectare_constant():
    assert SQM_PER_HECTARE == 10_000.0
    assert math.isclose(SQM_PER_ACRE, 4046.8564224)
