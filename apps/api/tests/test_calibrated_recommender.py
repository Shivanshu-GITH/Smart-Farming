"""Calibrated crop recommender (research Paper 1, deployed).

Assertions are agronomic sanity checks (orderings, top-k membership) rather
than exact scores, so they hold across re-exports of the model.
"""
import pytest

from app.agronomy import calibrated
from app.agronomy.catalogue import get_crop
from app.agronomy.recommend import recommend, score_crop
from app.land_intel.weather import seasonal_means

pytestmark = pytest.mark.skipif(not calibrated.available(),
                                reason="calibrated_model.json not exported")

PUNJAB = dict(state="Punjab", ph=7.8, texture="Loam / Silt loam", rainfall=700,
              tmean={"kharif": 30.5, "rabi": 16.5, "zaid": 30.0})
BIKANER = dict(state="Rajasthan", ph=7.8, texture="Sandy loam", rainfall=270,
               tmean={"kharif": 32.0, "rabi": 19.0, "zaid": 33.0})
KOCHI = dict(state="Kerala", ph=5.2, texture="Sandy loam", rainfall=2900,
             tmean={"kharif": 27.0, "rabi": 27.5, "zaid": 29.0})


def ids(recs, k=3):
    return [r["crop_id"] for r in recs[:k]]


def rank(recs, crop_id):
    return [r["crop_id"] for r in recs].index(crop_id)


def test_response_shape():
    r = recommend(season="Rabi (winter)", limit=5, **PUNJAB)[0]
    for key in ("crop_id", "score", "level", "suitability", "calibrated",
                "needs_irrigation", "reasons"):
        assert key in r
    assert 0.0 <= r["score"] <= 1.0


def test_punjab_seasons():
    assert "wheat" in ids(recommend(season="Rabi (winter)", **PUNJAB))
    assert "paddy" in ids(recommend(season="Kharif (monsoon)", **PUNJAB))


def test_desert_rainfed_prefers_millet_over_paddy():
    recs = recommend(season="Kharif (monsoon)", irrigated=False, limit=24, **BIKANER)
    assert rank(recs, "bajra") < rank(recs, "paddy")


def test_irrigation_flag_only_on_a_deficit():
    dry = {r["crop_id"]: r for r in recommend(season="Kharif (monsoon)", limit=24, **BIKANER)}
    wet = {r["crop_id"]: r for r in recommend(season="Kharif (monsoon)", limit=24, **KOCHI)}
    assert dry["paddy"]["needs_irrigation"]            # 270 mm < paddy's 1000 mm
    assert not wet["paddy"]["needs_irrigation"]        # excess rain is not a deficit


def test_state_names_match_across_spellings():
    a = recommend(season="Rabi (winter)", limit=5, **{**PUNJAB, "state": "Jammu and Kashmir"})
    b = recommend(season="Rabi (winter)", limit=5, **{**PUNJAB, "state": "Jammu And Kashmir"})
    assert [r["score"] for r in a] == [r["score"] for r in b]


def test_expert_only_crops_follow_validated_ones():
    recs = recommend(season="Kharif (monsoon)", system="monoculture", limit=24, **KOCHI)
    flags = [r["calibrated"] for r in recs]
    assert flags == sorted(flags, reverse=True)      # every validated crop first
    assert flags.count(False) <= 2
    assert next(r for r in recs if r["crop_id"] == "paddy")["calibrated"] is True


def test_multilayer_uses_expert_rules():
    # the statistics say nothing about multi-strata systems
    recs = recommend(season="Kharif (monsoon)", system="multilayer", limit=8, **KOCHI)
    assert recs and all("calibrated" not in r for r in recs)


def test_expert_only_crops_are_labelled_by_the_rules():
    recs = recommend(season="Rabi (winter)", system="monoculture", limit=24, **PUNJAB)
    expert = [r for r in recs if not r["calibrated"]]
    for r in expert:
        rule = score_crop(get_crop(r["crop_id"]), ph=PUNJAB["ph"], texture=PUNJAB["texture"],
                          rainfall=PUNJAB["rainfall"], temp_max=None, season="Rabi (winter)",
                          tmean=PUNJAB["tmean"])
        assert r["suitability"] == rule["suitability"]
        assert r["level"] in ("high", "ok")


def test_falls_back_to_rules_without_model(monkeypatch):
    monkeypatch.setattr(calibrated, "load_model", lambda: None)
    r = recommend(season="Rabi (winter)", limit=3, ph=7.8, texture="Loam / Silt loam",
                  rainfall=700, temp_max=31.0)[0]
    assert "calibrated" not in r and "suitability" in r


def test_score_crop_uses_seasonal_mean_temperature():
    wheat = get_crop("wheat")
    # annual mean daily max 31 C is outside wheat's 10-25 C range; Rabi mean 17 C is inside
    annual = score_crop(wheat, ph=7.5, texture=None, rainfall=700, temp_max=31.0,
                        season="Rabi (winter)")
    seasonal = score_crop(wheat, ph=7.5, texture=None, rainfall=700, temp_max=31.0,
                          season="Rabi (winter)", tmean={"rabi": 17.0})
    assert seasonal["score"] > annual["score"]


def test_normals_from_power_daily_payload():
    from app.land_intel.weather import normals_from_power
    param = {"T2M": {"20110115": 14.0, "20110715": 30.0, "20110515": 33.0, "20120115": 16.0,
                     "20120715": -999.0},
             "PRECTOTCORR": {"20110715": 10.0, "20110716": 4.0, "20120101": 6.0,
                             "20120102": -999.0}}
    out = normals_from_power(param)
    assert out["tmean_rabi_c"] == 15.0 and out["tmean_kharif_c"] == 30.0   # -999 skipped
    assert out["annual_rainfall_normal_mm"] == 10.0                        # 20 mm / 2 years


def test_seasonal_means_from_daily_series():
    dates = ["2025-01-15", "2025-07-15", "2025-05-15", "2025-12-01"]
    out = seasonal_means(dates, [15.0, None, 32.0, 17.0], [0, 34.0, 0, 0], [0, 26.0, 0, 0])
    assert out["tmean_rabi_c"] == 16.0      # Jan + Dec
    assert out["tmean_kharif_c"] == 30.0    # Jul, from (max + min) / 2
    assert out["tmean_zaid_c"] == 32.0


INDORE = dict(state="Madhya Pradesh", ph=7.6, texture="Clay", rainfall=950,
              tmean={"kharif": 27.0, "rabi": 19.5, "zaid": 31.0})
JUNAGADH = dict(state="Gujarat", ph=7.9, texture="Clay", rainfall=850,
                tmean={"kharif": 28.5, "rabi": 23.5, "zaid": 30.0})


@pytest.mark.parametrize("site,crop,with_state", [
    (BIKANER, "bajra", True), (BIKANER, "bajra", False),
    (INDORE, "soybean", True), (INDORE, "soybean", False),
    # climate + soil alone place groundnut in the top 5 for only ~44% of its
    # districts (per_crop_annual_A.csv); the state prior carries Saurashtra
    (JUNAGADH, "groundnut", True)])
def test_regional_crops_are_not_crowded_out_by_popular_ones(site, crop, with_state):
    # The range-envelope model never ranked these in any top 5 (popularity bias).
    kw = site if with_state else {k: v for k, v in site.items() if k != "state"}
    assert crop in ids(recommend(season="Kharif (monsoon)", system="monoculture", **kw))


def test_unknown_inputs_are_no_evidence():
    m = calibrated.load_model()
    if "bins" not in m["seasonal"]:
        pytest.skip("envelope-form model")
    e = calibrated._entry(m["seasonal"], get_crop("wheat"))
    assert calibrated._ratio(m["seasonal"], e, "ph", None) == 0.0
