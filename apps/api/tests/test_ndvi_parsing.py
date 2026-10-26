"""NDVI request and response handling (no network)."""
import math

from app.land_intel import ndvi


def _interval(date, mean, samples, nodata):
    return {"interval": {"from": f"{date}T00:00:00Z"},
            "outputs": {"ndvi": {"bands": {"B0": {"stats": {
                "mean": mean, "min": mean, "max": mean,
                "sampleCount": samples, "noDataCount": nodata}}}}}}


def test_resolution_is_about_10_m_in_degrees():
    # The request CRS is EPSG:4326, so resx/resy are degrees; "10" meant a
    # single ~1,100 km pixel per field.
    rx, ry = ndvi._resolution_deg(30.0)
    assert math.isclose(rx * 111_320 * math.cos(math.radians(30.0)), 10.0, rel_tol=1e-6)
    assert math.isclose(ry * 110_574, 10.0, rel_tol=1e-6)


def test_evalscript_masks_clouds_and_returns_floats():
    assert '"FLOAT32"' in ndvi._EVALSCRIPT
    assert "SCL" in ndvi._EVALSCRIPT


def test_latest_valid_skips_mostly_cloudy_passes():
    data = [_interval("2026-08-29", 0.486, 957, 548),   # 43% clear -> usable
            _interval("2026-09-13", 0.096, 957, 738)]   # 23% clear -> skipped
    date, stats = ndvi._latest_valid(data)
    assert date == "2026-08-29" and stats["mean"] == 0.486


def test_latest_valid_skips_nan_intervals():
    data = [_interval("2026-07-30", -0.12, 1056, 24), _interval("2026-08-14", "NaN", 1056, 1056)]
    assert ndvi._latest_valid(data)[0] == "2026-07-30"
    assert ndvi._latest_valid([_interval("2026-08-14", "NaN", 10, 10)]) is None
