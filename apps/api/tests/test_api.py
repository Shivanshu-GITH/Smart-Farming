"""Endpoint smoke tests that don't touch external networks.

Deliberately avoids /fields/summary and /land-intel/{soil,climate,report,ndvi
w/creds} because those call live upstream APIs.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_and_root():
    assert client.get("/health").json() == {"status": "ok"}
    body = client.get("/").json()
    assert body["name"] and "persistence" in body


def test_crops_catalogue():
    body = client.get("/agronomy/crops").json()
    assert len(body["crops"]) == 24
    assert "underground" in body["layers"]


def test_systems_catalogue():
    body = client.get("/agronomy/systems").json()
    ids = {s["id"] for s in body["systems"]}
    assert ids == {"monoculture", "intercrop", "multilayer"}


def test_recommend_respects_system_filter():
    r = client.post("/agronomy/recommend",
                    json={"system": "multilayer", "limit": 30}).json()
    ids = {x["crop_id"] for x in r["recommendations"]}
    assert "paddy" not in ids       # monoculture-only crop
    assert "turmeric" in ids

    r = client.post("/agronomy/recommend",
                    json={"system": "monoculture", "limit": 30}).json()
    assert any(x["crop_id"] == "paddy" for x in r["recommendations"])


def test_google_auth_disabled_without_client_id():
    assert client.post("/auth/google", json={"credential": "x"}).status_code == 503


def test_geo_search_validates_query():
    assert client.get("/geo/search").status_code == 422       # q required
    assert client.get("/geo/search", params={"q": "a"}).status_code == 422  # too short


def test_layered_location_finder():
    states = client.get("/geo/states").json()["states"]
    assert len(states) == 36 and "Uttar Pradesh" in states
    up = client.get("/geo/districts", params={"state": "uttar pradesh"}).json()
    assert len(up["districts"]) == 75 and "Barabanki" in up["districts"]
    assert client.get("/geo/districts", params={"state": "Nowhere"}).status_code == 404


def test_economics_scales_to_planting_area():
    body = {"crop_ids": ["banana"], "area_m2": 10000, "use_mandi": False}
    gross = client.post("/economics/estimate", json=body).json()
    ml = client.post("/economics/estimate", json={**body, "system": "multilayer"}).json()
    assert ml["usable_fraction"] == 0.8
    assert ml["totals"]["cost"] == pytest.approx(gross["totals"]["cost"] * 0.8, rel=0.01)


def test_validate_endpoint():
    r = client.post("/agronomy/validate", json={"crop_ids": ["tomato", "spinach"]})
    assert r.status_code == 200
    assert r.json()["compatible"] is True


def test_design_endpoint():
    r = client.post("/agronomy/design", json={"season": "Kharif (monsoon)", "ph": 6.8})
    assert r.status_code == 200
    assert r.json()["count"] >= 1


def test_economics_endpoint():
    r = client.post("/economics/estimate",
                    json={"crop_ids": ["tomato"], "area_m2": 10000, "use_mandi": False})
    assert r.status_code == 200
    assert r.json()["crops"][0]["cost"]["total"] == 88200


def test_layout_endpoint_requires_crop():
    assert client.post("/layout", json={
        "geometry": {"type": "Polygon", "coordinates": [[[80.6, 16.5], [80.61, 16.5],
                     [80.61, 16.51], [80.6, 16.51], [80.6, 16.5]]]},
        "crop_ids": []}).status_code == 422


def test_advisory_status_unconfigured():
    body = client.get("/advisory/status").json()
    assert body["configured"] is False and body["provider"] is None


def test_ndvi_graceful_without_credentials():
    r = client.post("/land-intel/ndvi", json={
        "geometry": {"type": "Polygon", "coordinates": [[[80.6, 16.5], [80.61, 16.5],
                     [80.61, 16.51], [80.6, 16.51], [80.6, 16.5]]]}})
    assert r.status_code == 200 and r.json()["configured"] is False


def test_protected_route_without_token_is_403():
    assert client.get("/fields").status_code == 403


def test_otp_request_returns_dev_code():
    body = client.post("/auth/otp/request", json={"phone": "+919000000009"}).json()
    assert body["sent"] and body["dev_code"]


def test_schemes_national_and_state_filter():
    national = client.get("/resources/schemes").json()
    assert national["count"] >= 8
    ap = client.get("/resources/schemes", params={"state": "Andhra Pradesh"}).json()
    ids = {r["id"] for r in ap["resources"]}
    assert "ap-rythu-bharosa" in ids  # state entry
    assert "pm-kisan" in ids          # national entries still included


def test_ndvi_series_graceful_without_credentials():
    r = client.post("/land-intel/ndvi-series", json={
        "geometry": {"type": "Polygon", "coordinates": [[[80.6, 16.5], [80.61, 16.5],
                     [80.61, 16.51], [80.6, 16.51], [80.6, 16.5]]]}})
    assert r.status_code == 200 and r.json()["configured"] is False


def test_admin_and_sso_disabled_by_default():
    assert client.get("/admin/stats").status_code == 503
    assert client.post("/auth/sso", json={"token": "x"}).status_code == 503


def test_diagnose_requires_key():
    r = client.post("/advisory/diagnose",
                    json={"image_base64": "aaaaaaaaaaaaaaaa", "media_type": "image/png"})
    assert r.status_code == 503


def test_saved_plans_and_layouts_require_auth():
    assert client.post("/fields/x/plans", json={"data": {}}).status_code == 403
    assert client.get("/fields/x/plans").status_code == 403
    assert client.post("/fields/x/layouts", json={"data": {}}).status_code == 403
    assert client.get("/fields/x/layouts").status_code == 403


def test_elevation_route_registered():
    # network-free assertion: the route exists and validates its query params
    assert client.get("/land-intel/elevation").status_code == 422  # missing lat/lon
