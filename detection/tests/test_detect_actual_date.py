"""
`detect()`'s `actual_date` -- the real Sentinel-2 scene date behind one
reading, which is NOT the date that was requested.

`get_sentinel2_bands` resolves the nearest cloud-free scene within a
search window (data-pipeline/src/sentinel2.py), so a caller that scans
many points on one target date routinely gets readings backed by scenes
several days apart. Until this field existed, `detect()` computed that
scene date and then discarded it, leaving every consumer to either omit
it or re-derive it with a second GEE round-trip
(backend/src/satellite_meta.py).

GEE is never touched here: `get_sentinel2_bands` is monkeypatched at the
typed boundary. Real index math runs; climatology and z-score calls are
forbidden because no dimensionally valid index baseline exists.

The safety rule under test: `actual_date` is either a real scene date or
None. The requested date is never substituted for a missing one.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import prediction  # noqa: E402
from src.prediction import detect, load_config  # noqa: E402

REQUESTED_DATE = "2026-06-15"
SCENE_DATE = "2026-06-09"  # 6 days before the request -- a realistic offset

# Shape returned by get_sentinel2_bands (data-pipeline/src/sentinel2.py
# docstring): the five reflectance bands plus scene metadata.
_BANDS = {
    "B2": 0.05,
    "B3": 0.08,
    "B4": 0.06,
    "B5": 0.07,
    "B6": 0.04,
    "cloud_fraction": 0.02,
    "actual_date": SCENE_DATE,
}

@pytest.fixture(scope="module")
def config():
    """The real config.yaml -- pinned to what actually ships, same as
    test_prediction.py's escalation_rules fixture."""
    return load_config()


def _patch_bands(monkeypatch, bands: dict) -> None:
    monkeypatch.setattr(
        prediction, "get_sentinel2_bands", lambda lat, lng, date: dict(bands)
    )


def _patch_bands_raising(monkeypatch, exc: Exception) -> None:
    def _raise(lat, lng, date):
        raise exc

    monkeypatch.setattr(prediction, "get_sentinel2_bands", _raise)


# --------------------------------------------------------------------------
# status == 'ok' -- imagery resolved, so a real scene date must come back.
# --------------------------------------------------------------------------


def test_detect_ok_returns_the_real_scene_date_not_the_requested_date(monkeypatch, config):
    _patch_bands(monkeypatch, _BANDS)

    result = detect(13.4, 100.6, REQUESTED_DATE, config)

    assert result["status"] == "ok"
    assert result["actual_date"] == SCENE_DATE
    # The whole point: this is a measurement, not an echo of the input.
    assert result["actual_date"] != REQUESTED_DATE


# --------------------------------------------------------------------------
# No baseline is consulted; successful imagery remains a real index reading.
# --------------------------------------------------------------------------


def test_detect_never_calls_climatology_or_z_score(monkeypatch, config):
    _patch_bands(monkeypatch, _BANDS)

    def forbidden(*args, **kwargs):
        pytest.fail("detect must not compute an index anomaly")

    # raising=False also catches accidentally reintroducing either old call.
    monkeypatch.setattr(prediction, "build_climatology", forbidden, raising=False)
    monkeypatch.setattr(prediction, "z_score", forbidden, raising=False)

    result = detect(13.4, 100.6, REQUESTED_DATE, config)

    assert result["status"] == "ok"
    assert "anomaly_z" not in result
    assert "spatial_anomaly_z" not in result
    assert "detected" not in result
    assert result["index_values"] is not None
    assert result["actual_date"] == SCENE_DATE


def test_detect_needs_only_index_configuration(monkeypatch):
    _patch_bands(monkeypatch, _BANDS)
    result = detect(13.4, 100.6, REQUESTED_DATE, {"indices": {"primary": "ndci"}})
    assert result["status"] == "ok"
    assert result["reason"] is None
    assert result["index_values"]["ndci"] == pytest.approx((0.07 - 0.06) / (0.07 + 0.06))
    assert result["actual_date"] == SCENE_DATE


# --------------------------------------------------------------------------
# The two statuses where no imagery was ever obtained -- must be None,
# never the requested date relabelled as a scene.
# --------------------------------------------------------------------------


def test_detect_no_imagery_returns_null_scene_date(monkeypatch, config):
    _patch_bands_raising(
        monkeypatch, prediction.NoCloudFreeImageryError("forced for test")
    )

    result = detect(13.4, 100.6, REQUESTED_DATE, config)

    assert result["status"] == "no_imagery"
    assert result["actual_date"] is None
    assert result["actual_date"] != REQUESTED_DATE


def test_detect_no_water_pixels_returns_null_scene_date(monkeypatch, config):
    _patch_bands_raising(monkeypatch, prediction.NoWaterPixelsError("forced for test"))

    result = detect(13.4, 100.6, REQUESTED_DATE, config)

    assert result["status"] == "no_water_pixels"
    assert result["actual_date"] is None
    assert result["actual_date"] != REQUESTED_DATE


# --------------------------------------------------------------------------
# Every return path carries the key -- a consumer must never have to tell
# "no scene" apart from "this build of detect() forgot the field".
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "expected_status,bands_setup",
    [
        ("ok", "ok"),
        ("no_imagery", "no_imagery"),
        ("no_water_pixels", "no_water_pixels"),
    ],
)
def test_every_detect_return_path_includes_actual_date(
    monkeypatch, config, expected_status, bands_setup
):
    if bands_setup == "no_imagery":
        _patch_bands_raising(
            monkeypatch, prediction.NoCloudFreeImageryError("forced for test")
        )
    elif bands_setup == "no_water_pixels":
        _patch_bands_raising(monkeypatch, prediction.NoWaterPixelsError("forced for test"))
    else:
        _patch_bands(monkeypatch, _BANDS)

    result = detect(13.4, 100.6, REQUESTED_DATE, config)

    assert result["status"] == expected_status
    assert "actual_date" in result
    assert "detected" not in result
    assert "anomaly_z" not in result
    assert "spatial_anomaly_z" not in result
