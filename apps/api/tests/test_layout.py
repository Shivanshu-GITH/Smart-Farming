from shapely.geometry import Point

from app.core.geo import polygon_from_geojson
from app.layout.engine import MAX_POINTS, generate_layout


def _square(lat, lon, d):
    return {"type": "Polygon", "coordinates": [[
        [lon, lat], [lon + d, lat], [lon + d, lat + d], [lon, lat + d], [lon, lat],
    ]]}


def test_layout_places_points_inside_polygon():
    # ~22 m square (≈1400 tomato plants) — genuinely under the render cap
    geom = _square(16.5, 80.6, 0.0002)
    poly = polygon_from_geojson(geom)
    res = generate_layout(geom, ["tomato"])

    feats = res["planting_points"]["features"]
    assert res["rendered_points"] == len(feats) > 0
    assert not res["truncated"]
    for f in feats:
        x, y = f["geometry"]["coordinates"]
        assert poly.contains(Point(x, y))
        assert f["properties"]["layer"] == "middle"
        assert f["properties"]["crop_id"] == "tomato"


def test_plant_count_is_area_based_estimate():
    # ~22 m square ≈ 470 m²; tomato 0.75x0.45m → ~1400 plants, no thinning
    res = generate_layout(_square(16.5, 80.6, 0.0002), ["tomato"])
    crop = res["crops"][0]
    est = crop["plant_count"]
    # estimate should be in the same ballpark as the rendered grid
    assert est > 0
    assert abs(est - crop["rendered_points"]) / est < 0.35


def test_layout_multilayer_interleaves_distinct_layers():
    res = generate_layout(_square(16.5, 80.6, 0.002), ["turmeric", "tomato", "banana"])
    layers = {c["layer"] for c in res["crops"]}
    assert layers == {"underground", "middle", "top"}
    assert res["total_plants"] > 0


def test_layout_unknown_crop_skipped():
    res = generate_layout(_square(16.5, 80.6, 0.001), ["nope"])
    assert res["crops"] == []
    assert res["total_plants"] == 0


def test_layout_heatmap_shape():
    res = generate_layout(_square(16.5, 80.6, 0.002), ["tomato"])
    hm = res["heatmap"]
    assert hm["grid"] == 24
    assert hm["max_count"] >= 1
    for cell in hm["cells"]:
        assert 0.0 <= cell["intensity"] <= 1.0
        assert len(cell["bbox"]) == 4


def test_render_cap_thins_uniformly_not_into_a_corner():
    """The old engine truncated the scan at MAX_POINTS, piling every point into
    the south-west corner. Thinned output must still span the whole field."""
    geom = _square(16.5, 80.6, 0.02)  # ~2.2 km square, spinach 25x10cm → huge grid
    res = generate_layout(geom, ["spinach"])
    feats = res["planting_points"]["features"]

    assert 0 < len(feats) <= MAX_POINTS
    assert res["truncated"]  # display sampled
    # true agronomic estimate stays honest (way above the render cap)
    assert res["crops"][0]["plant_count"] > MAX_POINTS

    xs = [f["geometry"]["coordinates"][0] for f in feats]
    ys = [f["geometry"]["coordinates"][1] for f in feats]
    minx, miny, maxx, maxy = polygon_from_geojson(geom).bounds
    # points must cover (almost) the full extent in both axes
    assert (max(xs) - min(xs)) / (maxx - minx) > 0.9
    assert (max(ys) - min(ys)) / (maxy - miny) > 0.9


def test_monoculture_uses_single_crop():
    res = generate_layout(_square(16.5, 80.6, 0.001), ["wheat", "mustard"],
                          system="monoculture")
    assert [c["crop_id"] for c in res["crops"]] == ["wheat"]
    assert res["system"] == "monoculture"


def test_intercrop_alternates_row_bands():
    res = generate_layout(_square(16.5, 80.6, 0.001), ["maize", "soybean"],
                          system="intercrop")
    by_crop = {c["crop_id"]: c for c in res["crops"]}
    assert set(by_crop) == {"maize", "soybean"}
    # both crops actually placed
    feats = res["planting_points"]["features"]
    ys = {"maize": set(), "soybean": set()}
    for f in feats:
        ys[f["properties"]["crop_id"]].add(round(f["geometry"]["coordinates"][1], 7))
    assert ys["maize"] and ys["soybean"]
    # row bands don't overlap: no shared row latitude between the two crops
    assert not (ys["maize"] & ys["soybean"])
    # 2:1 default ratio → maize occupies more rows
    assert len(ys["maize"]) > len(ys["soybean"])


def test_unknown_system_rejected():
    import pytest
    with pytest.raises(ValueError):
        generate_layout(_square(16.5, 80.6, 0.001), ["wheat"], system="hydroponics")
