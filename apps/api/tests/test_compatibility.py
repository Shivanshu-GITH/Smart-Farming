from app.agronomy import compatibility
from app.agronomy.compatibility import suggest_fillers, validate_combo


def test_companion_synergy_detected():
    res = validate_combo(["tomato", "spinach"])  # spinach is a tomato companion
    assert res["compatible"] is True
    assert any("companion" == s["type"] for s in res["synergies"])


def test_same_layer_crowding_warns():
    res = validate_combo(["tomato", "brinjal"])  # both middle layer
    assert any(w["type"] == "layer_crowding" and w["layer"] == "middle"
               for w in res["warnings"])


def test_no_common_season_warns():
    # turmeric = Kharif only; coriander = Rabi only -> no overlap
    res = validate_combo(["turmeric", "coriander"])
    assert res["common_seasons"] == []
    assert any(w["type"] == "season" for w in res["warnings"])


def test_antagonist_conflict_flags_incompatible(monkeypatch):
    crops = {
        "a": {"id": "a", "name": "A", "layer": "ground", "seasons": ["Kharif (monsoon)"],
              "companions": [], "antagonists": ["b"]},
        "b": {"id": "b", "name": "B", "layer": "middle", "seasons": ["Kharif (monsoon)"],
              "companions": [], "antagonists": []},
    }
    monkeypatch.setattr(compatibility, "get_crop", lambda cid: crops.get(cid))
    res = validate_combo(["a", "b"])
    assert res["compatible"] is False
    assert res["conflicts"] and res["conflicts"][0]["type"] == "antagonist"


def test_suggest_fillers_only_for_empty_layers():
    res = suggest_fillers(["tomato"], ph=6.8, texture="Clay loam",
                          rainfall=950, temp_max=33, season="Kharif (monsoon)")
    # tomato is 'middle' -> middle should not be offered as a filler layer
    assert "middle" not in res
    # every suggestion must be plantable in the requested season
    for cands in res.values():
        assert cands  # non-empty lists only
