"""
Unit tests for the pure spectral-index math in `src/indices.py` — no GEE
session required or contacted (these functions take a plain `bands` dict
and never call out to data-pipeline).
"""

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.indices import (  # noqa: E402
    b2_b3_ratio,
    compute_all_indices,
    ndci,
    three_bda,
    to_reflectance,
    two_bda,
)


# --------------------------------------------------------------------------
# to_reflectance
# --------------------------------------------------------------------------


def test_to_reflectance_basic():
    assert to_reflectance(5000.0) == pytest.approx(0.5)


def test_to_reflectance_zero():
    assert to_reflectance(0.0) == pytest.approx(0.0)


# --------------------------------------------------------------------------
# ndci -- (B5 - B4) / (B5 + B4), returns 0.0 when B5+B4 == 0
# --------------------------------------------------------------------------


def test_ndci_normal_value():
    bands = {"B4": 100.0, "B5": 300.0}
    assert ndci(bands) == pytest.approx((300.0 - 100.0) / (300.0 + 100.0))


def test_ndci_negative_when_b4_greater_than_b5():
    bands = {"B4": 300.0, "B5": 100.0}
    assert ndci(bands) == pytest.approx(-0.5)


def test_ndci_degenerate_zero_denominator_returns_zero():
    bands = {"B4": 0.0, "B5": 0.0}
    assert ndci(bands) == 0.0


# --------------------------------------------------------------------------
# two_bda -- B5 / B4, returns math.inf when B4 == 0
# --------------------------------------------------------------------------


def test_two_bda_normal_value():
    bands = {"B4": 100.0, "B5": 300.0}
    assert two_bda(bands) == pytest.approx(3.0)


def test_two_bda_degenerate_zero_b4_returns_inf():
    bands = {"B4": 0.0, "B5": 300.0}
    assert two_bda(bands) == math.inf


def test_two_bda_zero_b4_and_b5_still_returns_inf():
    # B4 == 0 is checked first regardless of B5's value.
    bands = {"B4": 0.0, "B5": 0.0}
    assert two_bda(bands) == math.inf


# --------------------------------------------------------------------------
# three_bda -- (1/B4 - 1/B5) * B6, returns math.inf if B4 == 0 or B5 == 0
# --------------------------------------------------------------------------


def test_three_bda_normal_value():
    bands = {"B4": 100.0, "B5": 200.0, "B6": 50.0}
    expected = (1.0 / 100.0 - 1.0 / 200.0) * 50.0
    assert three_bda(bands) == pytest.approx(expected)


def test_three_bda_degenerate_zero_b4_returns_inf():
    bands = {"B4": 0.0, "B5": 200.0, "B6": 50.0}
    assert three_bda(bands) == math.inf


def test_three_bda_degenerate_zero_b5_returns_inf():
    bands = {"B4": 100.0, "B5": 0.0, "B6": 50.0}
    assert three_bda(bands) == math.inf


# --------------------------------------------------------------------------
# b2_b3_ratio -- B2 / B3, returns math.inf if B3 == 0
# --------------------------------------------------------------------------


def test_b2_b3_ratio_normal_value():
    bands = {"B2": 100.0, "B3": 200.0}
    assert b2_b3_ratio(bands) == pytest.approx(0.5)


def test_b2_b3_ratio_degenerate_zero_b3_returns_inf():
    bands = {"B2": 100.0, "B3": 0.0}
    assert b2_b3_ratio(bands) == math.inf


# --------------------------------------------------------------------------
# compute_all_indices -- all four indices, keyed correctly, extra keys
# in `bands` (e.g. cloud_fraction, actual_date from get_sentinel2_bands)
# ignored.
# --------------------------------------------------------------------------


def test_compute_all_indices_keys_and_values():
    bands = {
        "B2": 100.0,
        "B3": 200.0,
        "B4": 100.0,
        "B5": 300.0,
        "B6": 50.0,
        "cloud_fraction": 0.05,  # extra key, must be ignored
        "actual_date": "2024-01-15",  # extra key, must be ignored
    }
    result = compute_all_indices(bands)

    assert set(result.keys()) == {"ndci", "2bda", "3bda", "b2_b3_ratio"}
    assert result["ndci"] == pytest.approx(ndci(bands))
    assert result["2bda"] == pytest.approx(two_bda(bands))
    assert result["3bda"] == pytest.approx(three_bda(bands))
    assert result["b2_b3_ratio"] == pytest.approx(b2_b3_ratio(bands))


def test_compute_all_indices_degenerate_bands_all_inf_or_zero():
    bands = {"B2": 0.0, "B3": 0.0, "B4": 0.0, "B5": 0.0, "B6": 0.0}
    result = compute_all_indices(bands)

    assert result["ndci"] == 0.0
    assert result["2bda"] == math.inf
    assert result["3bda"] == math.inf
    assert result["b2_b3_ratio"] == math.inf
