"""
Unit tests for `src/climatology.py`'s pure `z_score` function only.

`build_climatology` is NOT tested here -- it makes a real, live GEE call
(`get_modis_chlorophyll_history`) via `_data_pipeline.py` and is out of
scope for offline unit tests. Importing `src.climatology` itself is safe
without GEE auth: it only imports `_data_pipeline` for names at module
load time (no `ee.Initialize()` call happens on import), so this test
module requires no live GEE session or credentials.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.climatology import z_score  # noqa: E402


def test_z_score_normal_case():
    climatology = {"mean": 5.0, "std": 2.0, "n": 20, "reliable": True}
    result = z_score(10.0, climatology)
    assert result["z"] == pytest.approx((10.0 - 5.0) / 2.0)
    assert result["reason"] is None


def test_z_score_below_mean_is_negative():
    climatology = {"mean": 5.0, "std": 2.0, "n": 20, "reliable": True}
    result = z_score(1.0, climatology)
    assert result["z"] == pytest.approx(-2.0)
    assert result["reason"] is None


def test_z_score_climatology_none_returns_none_with_reason():
    result = z_score(10.0, None)
    assert result["z"] is None
    assert result["reason"] == "no_climatology_data_for_this_location_and_window"


def test_z_score_zero_std_returns_none_with_reason():
    climatology = {"mean": 5.0, "std": 0.0, "n": 3, "reliable": False}
    result = z_score(10.0, climatology)
    assert result["z"] is None
    assert result["reason"] == "zero_historical_variance_z_undefined"


def test_z_score_zero_std_even_when_value_equals_mean():
    # std == 0 must short-circuit to None regardless of whether value
    # happens to equal the (degenerate, flat) mean.
    climatology = {"mean": 5.0, "std": 0.0, "n": 3, "reliable": False}
    result = z_score(5.0, climatology)
    assert result["z"] is None
    assert result["reason"] == "zero_historical_variance_z_undefined"
