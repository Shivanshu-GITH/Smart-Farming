import datetime as dt

import pytest

from app.agronomy.catalogue import all_crops, get_crop
from app.agronomy.plan import build_plan, plants_per_hectare
from app.agronomy.recommend import recommend, score_crop


def test_catalogue_has_expected_crops():
    ids = {c["id"] for c in all_crops()}
    assert {"tomato", "banana", "turmeric"} <= ids          # horticulture originals
    assert {"paddy", "wheat", "cotton", "sugarcane"} <= ids  # field crops
    assert len(all_crops()) == 24
    # every crop declares which farming systems it suits
    for c in all_crops():
        assert set(c["systems"]) <= {"monoculture", "intercrop", "multilayer"}
        assert c["systems"]


def test_score_within_bounds_and_unknown_is_neutral():
    tomato = get_crop("tomato")
    s = score_crop(tomato, ph=6.5, texture="Loam / Silt loam",
                   rainfall=900, temp_max=28, season="Rabi (winter)")
    assert 0.0 <= s["score"] <= 1.0
    assert s["suitability"] in {"Highly suitable", "Suitable", "Marginal", "Not recommended"}
    # all-unknown inputs -> neutral-ish, never punished below 0.5 blend
    s2 = score_crop(tomato, ph=None, texture=None, rainfall=None,
                    temp_max=None, season=None)
    assert s2["score"] >= 0.5


def test_good_conditions_outscore_bad():
    good = score_crop(get_crop("tomato"), ph=6.5, texture="Loam / Silt loam",
                      rainfall=900, temp_max=25, season="Rabi (winter)")["score"]
    bad = score_crop(get_crop("tomato"), ph=9.0, texture="Sandy",
                     rainfall=100, temp_max=45, season="Zaid (summer)")["score"]
    assert good > bad


def test_recommend_sorted_and_limited():
    res = recommend(ph=6.5, rainfall=900, temp_max=28, season="Kharif (monsoon)", limit=5)
    assert len(res) == 5
    scores = [r["score"] for r in res]
    assert scores == sorted(scores, reverse=True)


def test_recommend_layer_filter():
    res = recommend(layer="top", limit=10)
    assert res and all(r["layer"] == "top" for r in res)


def test_plants_per_hectare_matches_spacing():
    tomato = get_crop("tomato")  # 75 x 45 cm
    assert plants_per_hectare(tomato) == int(10_000 / (0.75 * 0.45))


def test_build_plan_numbers():
    plan = build_plan("tomato", 10_000.0, start=dt.date(2026, 1, 1))
    assert plan["area_hectares"] == pytest.approx(1.0)
    assert plan["seed"]["quantity_kg"] == pytest.approx(0.4)
    assert plan["fertilizer"]["total_kg"] == {"N": 120.0, "P": 80.0, "K": 60.0}
    assert plan["plants"]["total_estimate"] == int(10_000 / (0.75 * 0.45))
    # calendar is ordered and starts at day 0
    days = [s["day"] for s in plan["calendar"]]
    assert days[0] == 0 and days == sorted(days)


def test_build_plan_unknown_crop_raises():
    with pytest.raises(ValueError):
        build_plan("does-not-exist", 10_000.0)
