from shapely.geometry import Point

from app.core.geo import polygon_from_geojson
from app.layout.engine import MAX_POINTS, generate_layout


def _square(lat, lon, d):
    return {"type": "Polygon", "coordinates": [[
        [lon, lat], [lon + d, lat], [lon + d, lat + d], [lon, lat + d], [lon, lat],
    ]]}


def test_layout_places_points_inside_polygon():
    # small field so tomato spacing stays well under the point cap
    geom = _square(16.5, 80.6, 0.0004)
    poly = polygon_from_geojson(geom)
    res = generate_layout(geom, ["tomato"])

    feats = res["planting_points"]["features"]
    assert res["total_plants"] == len(feats) > 0
    assert not res["truncated"]
    for f in feats:
        x, y = f["geometry"]["coordinates"]
        assert poly.contains(Point(x, y))
        assert f["properties"]["layer"] == "middle"
        assert f["properties"]["crop_id"] == "tomato"


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


def test_layout_respects_max_points_cap():
    # a large field with tight spacing would exceed the cap; ensure it's bounded
    res = generate_layout(_square(16.5, 80.6, 0.05), ["spinach"])  # 25x10 cm spacing
    assert res["total_plants"] <= MAX_POINTS
    if res["total_plants"] == MAX_POINTS:
        assert res["truncated"]
