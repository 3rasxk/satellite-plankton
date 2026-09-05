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

GEE is never touched here: `get_sentinel2_bands` and
`build_climatology` are monkeypatched on the `src.prediction` module
namespace -- the same typed boundary the rest of this suite avoids
crossing. `compute_all_indices` and `z_score` are left REAL, so the
tests exercise the actual code path, not a stub of it.

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

_CLIMATOLOGY = {"mean": 0.0, "std": 0.1, "n": 20, "reliable": True}


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


def _patch_climatology(monkeypatch, climatology) -> None:
    monkeypatch.setattr(
        prediction, "build_climatology", lambda lat, lng, date, window_days: climatology
    )


# --------------------------------------------------------------------------
# status == 'ok' -- imagery resolved, so a real scene date must come back.
# --------------------------------------------------------------------------


def test_detect_ok_returns_the_real_scene_date_not_the_requested_date(monkeypatch, config):
    _patch_bands(monkeypatch, _BANDS)
    _patch_climatology(monkeypatch, _CLIMATOLOGY)

    result = detect(13.4, 100.6, REQUESTED_DATE, config)

    assert result["status"] == "ok"
    assert result["actual_date"] == SCENE_DATE
    # The whole point: this is a measurement, not an echo of the input.
    assert result["actual_date"] != REQUESTED_DATE


# --------------------------------------------------------------------------
# status == 'no_climatology' -- Sentinel-2 DID resolve; only the MODIS
# baseline is missing. This path must still carry the real scene date.
# --------------------------------------------------------------------------


def test_detect_no_climatology_still_carries_the_scene_date(monkeypatch, config):
    # build_climatology returning None is what z_score converts into
    # z=None / reason='no_climatology_data_for_this_location_and_window'.
    _patch_bands(monkeypatch, _BANDS)
    _patch_climatology(monkeypatch, None)

    result = detect(13.4, 100.6, REQUESTED_DATE, config)

    assert result["status"] == "no_climatology"
    assert result["anomaly_z"] is None
    # Imagery succeeded on this path, so index_values and the scene date
    # behind them are both real -- only the anomaly baseline is missing.
    assert result["index_values"] is not None
    assert result["actual_date"] == SCENE_DATE


def test_detect_zero_variance_climatology_also_carries_the_scene_date(monkeypatch, config):
    # The other route into 'no_climatology': a degenerate baseline with
    # std == 0 (z undefined). Imagery still resolved.
    _patch_bands(monkeypatch, _BANDS)
    _patch_climatology(monkeypatch, {"mean": 0.05, "std": 0.0, "n": 3, "reliable": False})

    result = detect(13.4, 100.6, REQUESTED_DATE, config)

    assert result["status"] == "no_climatology"
    assert result["reason"] == "zero_historical_variance_z_undefined"
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
        ("no_climatology", "no_climatology"),
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
        _patch_climatology(
            monkeypatch, None if bands_setup == "no_climatology" else _CLIMATOLOGY
        )

    result = detect(13.4, 100.6, REQUESTED_DATE, config)

    assert result["status"] == expected_status
    assert "actual_date" in result
