"""Geometry-aware plant counts and layouts (research Paper 2, deployed)."""
import math

import numpy as np
import pytest
import shapely
from shapely.geometry import Polygon, mapping

from app.agronomy import counts
from app.agronomy.catalogue import get_crop
from app.agronomy.plan import build_plan
from app.layout import engine
from app.layout.engine import _estimate_count, _grid_in, _local_frame, generate_layout


def _field(w_m: float, h_m: float, angle_deg: float = 0.0, lat: float = 17.4, lon: float = 78.4):
    """A w x h metre rectangle (optionally rotated) as a lon/lat polygon."""
    m_lon, m_lat = engine._meters_per_degree(lat)
    rect = shapely.affinity.rotate(Polygon([(0, 0), (w_m, 0), (w_m, h_m), (0, h_m)]),
                                   angle_deg, origin=(0, 0))
    return shapely.transform(rect, lambda xy: np.column_stack(
        [lon + xy[:, 0] / m_lon, lat + xy[:, 1] / m_lat]))


def test_closed_form_is_exact_for_a_rectangle():
    crop = get_crop("banana")                     # 2 m x 2 m, setback 1 m
    A, P = 40 * 25, 2 * (40 + 25)
    s = counts.setback_m(crop)
    expected = int((40 - 2 * s) * (25 - 2 * s) / counts.cell_m2(crop))
    assert counts.geometric_count(crop, A, P) == expected


def test_estimate_falls_back_to_area_formula_without_perimeter():
    crop = get_crop("cotton")
    assert counts.estimate_plants(crop, 10_000, None, "monoculture") == \
        _estimate_count(10_000 * 0.95, crop)


def test_every_plant_respects_the_border_setback():
    poly = _field(37, 23, angle_deg=28)
    out = generate_layout(mapping(poly), ["drumstick"], "monoculture")
    local, fwd, _ = _local_frame(poly)
    pts = np.array([f["geometry"]["coordinates"] for f in out["planting_points"]["features"]])
    x, y = fwd(pts[:, 0], pts[:, 1])
    d = shapely.distance(local.exterior, shapely.points(x, y))
    assert d.min() >= counts.setback_m(get_crop("drumstick")) - 1e-6


def test_grid_search_never_places_fewer_than_the_default_grid():
    crop = get_crop("banana")
    for angle in (0, 17, 33, 61):
        poly = _field(31, 19, angle_deg=angle)
        pts, stride, _theta = engine._place_monoculture_geo(poly, crop)
        local, _, _ = _local_frame(poly)
        inner = local.buffer(-counts.setback_m(crop))
        default = _grid_in(inner, local, 2.0, 2.0, 0.0, 0.0, 0.0)
        assert stride == 1 and len(pts) >= len(default)


def test_tilted_small_field_gains_positions_for_trees():
    # a narrow plot at 30 degrees: an E-W grid wastes the ends
    poly = _field(24, 9, angle_deg=30)
    out = generate_layout(mapping(poly), ["drumstick"], "monoculture")
    local, _, _ = _local_frame(poly)
    inner = local.buffer(-counts.setback_m(get_crop("drumstick")))
    default = len(_grid_in(inner, local, 2.5, 2.5, 0.0, 0.0, 0.0))
    assert out["crops"][0]["plant_count"] > default
    assert out["crops"][0]["count_method"] == "layout"


def test_legacy_mode_reproduces_the_original_engine():
    poly = _field(60, 40)
    area = engine.geodesic_area_m2(poly) * 0.95
    out = generate_layout(mapping(poly), ["cotton"], "monoculture", geometry_aware=False)
    assert out["crops"][0]["plant_count"] == _estimate_count(area, get_crop("cotton"))
    assert out["crops"][0]["count_method"] == "area-estimate"


def test_plan_uses_the_layout_count_when_given():
    plan = build_plan("banana", 1000, system="monoculture", plant_count=180)
    assert plan["plants"]["total_estimate"] == 180
    assert plan["plants"]["count_method"] == "layout"
    assert plan["planting_material"]["quantity"] == math.ceil(180 * 1.05)


def test_plan_geometric_estimate_from_perimeter():
    crop = get_crop("banana")
    plan = build_plan("banana", 1000, system="monoculture", perimeter_m=130)
    assert plan["plants"]["total_estimate"] == counts.geometric_count(crop, 1000, 130)
    assert plan["plants"]["count_method"] == "geometric-estimate"


@pytest.mark.parametrize("system,ids", [
    ("intercrop", ["maize", "soybean"]),
    ("multilayer", ["banana", "chilli", "beans", "coriander", "turmeric"]),
])
def test_other_systems_respect_setback(system, ids):
    poly = _field(45, 30, angle_deg=12)
    out = generate_layout(mapping(poly), ids, system)
    local, fwd, _ = _local_frame(poly)
    for c in out["crops"]:
        pts = np.array([f["geometry"]["coordinates"] for f in out["planting_points"]["features"]
                        if f["properties"]["crop_id"] == c["crop_id"]])
        if len(pts) == 0:
            continue
        x, y = fwd(pts[:, 0], pts[:, 1])
        d = shapely.distance(local.exterior, shapely.points(x, y))
        assert d.min() >= counts.setback_m(get_crop(c["crop_id"])) - 1e-6
