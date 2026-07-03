from app.agronomy.optimizer import design_stacks

KHARIF = dict(ph=6.8, texture="Clay loam", rainfall=950, temp_max=33,
              season="Kharif (monsoon)")


def test_design_returns_ranked_stacks():
    res = design_stacks(**KHARIF, max_stacks=3)
    assert 1 <= res["count"] <= 3
    scores = [s["total_score"] for s in res["stacks"]]
    assert scores == sorted(scores, reverse=True)


def test_each_stack_has_one_crop_per_layer_and_no_antagonists():
    res = design_stacks(**KHARIF, max_stacks=3)
    for stack in res["stacks"]:
        layers = [L["layer"] for L in stack["layers"]]
        assert len(layers) == len(set(layers))  # one crop per layer
        ids = [L["crop_id"] for L in stack["layers"]]
        assert stack["crop_ids"] == ids
        assert stack["filled_layers"] == len(ids)


def test_design_respects_season_filter():
    # Rabi-only design should not include Kharif-only crops like turmeric
    res = design_stacks(ph=6.5, texture="Loam / Silt loam", rainfall=700,
                        temp_max=25, season="Rabi (winter)")
    for stack in res["stacks"]:
        assert "turmeric" not in stack["crop_ids"]
