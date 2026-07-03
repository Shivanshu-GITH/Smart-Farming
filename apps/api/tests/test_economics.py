from app.economics.estimator import estimate


def test_single_crop_cost_and_margin_exact():
    # tomato on 1 ha: seed 0.4kg x 8000 = 3200; +40000 inputs +45000 labour
    res = estimate(["tomato"], 10_000.0)
    crop = res["crops"][0]
    assert crop["cost"] == {"seed": 3200, "inputs": 40000, "labour": 45000, "total": 88200}
    # yield 25000-50000 kg x 12 INR/kg
    assert crop["revenue"] == [300000, 600000]
    assert crop["margin"] == [300000 - 88200, 600000 - 88200]
    assert crop["price_source"] == "estimate"


def test_totals_are_the_sum_of_crops():
    res = estimate(["tomato", "spinach"], 10_000.0)
    assert res["totals"]["cost"] == sum(c["cost"]["total"] for c in res["crops"])
    assert res["totals"]["margin"][0] == sum(c["margin"][0] for c in res["crops"])
    assert res["layers"] == len({c["layer"] for c in res["crops"]})


def test_mandi_price_override_used_when_supplied():
    base = estimate(["tomato"], 10_000.0)["crops"][0]
    override = estimate(["tomato"], 10_000.0, prices={"tomato": 24})["crops"][0]
    assert override["price_per_kg"] == 24
    assert override["price_source"] == "mandi"
    assert override["revenue"][0] == base["revenue"][0] * 2


def test_unknown_crop_skipped():
    res = estimate(["tomato", "nope"], 10_000.0)
    assert [c["crop_id"] for c in res["crops"]] == ["tomato"]


def test_area_scales_linearly():
    half = estimate(["banana"], 5_000.0)["crops"][0]["cost"]["total"]
    full = estimate(["banana"], 10_000.0)["crops"][0]["cost"]["total"]
    assert full == 2 * half
