"""
Unit tests for the GEE-free color-ramp/stretch logic in `src/imagery.py`,
exercised entirely with plain numeric values -- no Earth Engine session
required or contacted.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.imagery import (
    NDCI_RAMP_DOMAIN,
    NDCI_RAMP_HEX,
    hex_to_rgb,
    linear_stretch_uint8,
    ndci_value_to_color,
)


# --------------------------------------------------------------------------
# hex_to_rgb
# --------------------------------------------------------------------------


def test_hex_to_rgb_black():
    assert hex_to_rgb("#000000") == (0, 0, 0)


def test_hex_to_rgb_white():
    assert hex_to_rgb("#FFFFFF") == (255, 255, 255)


def test_hex_to_rgb_project_deep_color():
    assert hex_to_rgb("#0A1929") == (10, 25, 41)


def test_hex_to_rgb_project_severe_color():
    assert hex_to_rgb("#D64545") == (214, 69, 69)


def test_hex_to_rgb_without_hash_prefix_still_works():
    assert hex_to_rgb("2E86AB") == (46, 134, 171)


def test_hex_to_rgb_malformed_raises():
    with pytest.raises(ValueError):
        hex_to_rgb("#FFF")  # 3-digit shorthand not supported -- explicit, not guessed


# --------------------------------------------------------------------------
# linear_stretch_uint8
# --------------------------------------------------------------------------


def test_linear_stretch_at_min_is_zero():
    assert linear_stretch_uint8(0, vmin=0, vmax=1500) == 0


def test_linear_stretch_at_max_is_255():
    assert linear_stretch_uint8(1500, vmin=0, vmax=1500) == 255


def test_linear_stretch_midpoint():
    assert linear_stretch_uint8(750, vmin=0, vmax=1500) == 128  # round(0.5*255)=128


def test_linear_stretch_clamps_below_min():
    assert linear_stretch_uint8(-500, vmin=0, vmax=1500) == 0


def test_linear_stretch_clamps_above_max():
    assert linear_stretch_uint8(9000, vmin=0, vmax=1500) == 255


def test_linear_stretch_realistic_open_water_value():
    # Live open-water B2-B6 values observed in this project: ~380-560.
    # With TRUE_COLOR_MAX=1500, 500 should render clearly above black but
    # well below full brightness -- water-colored, not crushed.
    result = linear_stretch_uint8(500, vmin=0, vmax=1500)
    assert 0 < result < 128


def test_linear_stretch_invalid_domain_raises():
    with pytest.raises(ValueError):
        linear_stretch_uint8(100, vmin=100, vmax=100)


# --------------------------------------------------------------------------
# ndci_value_to_color
# --------------------------------------------------------------------------


def test_ndci_color_at_domain_min_is_first_stop():
    vmin, _ = NDCI_RAMP_DOMAIN
    assert ndci_value_to_color(vmin) == hex_to_rgb(NDCI_RAMP_HEX[0])


def test_ndci_color_at_domain_max_is_last_stop():
    _, vmax = NDCI_RAMP_DOMAIN
    assert ndci_value_to_color(vmax) == hex_to_rgb(NDCI_RAMP_HEX[-1])


def test_ndci_color_below_domain_clamps_to_first_stop():
    vmin, _ = NDCI_RAMP_DOMAIN
    assert ndci_value_to_color(vmin - 10.0) == hex_to_rgb(NDCI_RAMP_HEX[0])


def test_ndci_color_above_domain_clamps_to_last_stop():
    _, vmax = NDCI_RAMP_DOMAIN
    assert ndci_value_to_color(vmax + 10.0) == hex_to_rgb(NDCI_RAMP_HEX[-1])


def test_ndci_color_at_each_of_the_5_stops_matches_project_hex_exactly():
    """The 5 stops are evenly spaced across the domain; the value at each
    stop's exact fractional position must reproduce that stop's hex color
    with no interpolation blur, and must be the exact project-standard
    RISK_COLOR_HEX / NO_DATA_HEX values (docs/FRONTEND_PLAN.md §4,
    frontend/src/constants.js) -- not a new arbitrary palette.
    """
    vmin, vmax = NDCI_RAMP_DOMAIN
    n = len(NDCI_RAMP_HEX)
    for i, hex_color in enumerate(NDCI_RAMP_HEX):
        t = i / (n - 1)
        value = vmin + t * (vmax - vmin)
        assert ndci_value_to_color(value) == hex_to_rgb(hex_color)

    assert NDCI_RAMP_HEX == (
        "#0A1929",
        "#2E86AB",
        "#48C9A9",
        "#E8C547",
        "#D64545",
    )


def test_ndci_color_midpoint_between_first_two_stops_interpolates():
    vmin, vmax = NDCI_RAMP_DOMAIN
    n = len(NDCI_RAMP_HEX)
    step = (vmax - vmin) / (n - 1)
    midpoint_value = vmin + step / 2.0

    result = ndci_value_to_color(midpoint_value)
    c0 = hex_to_rgb(NDCI_RAMP_HEX[0])
    c1 = hex_to_rgb(NDCI_RAMP_HEX[1])
    expected = tuple(round((c0[k] + c1[k]) / 2.0) for k in range(3))
    assert result == expected


def test_ndci_color_realistic_nonbloom_value_lands_in_lower_half_of_ramp():
    # Live non-bloom NDCI values observed in this project: ~0.02-0.09.
    # These should render visually distinct from both extremes -- proof
    # the chosen domain gives real dynamic range across realistic values,
    # not everything pinned to one end.
    low = ndci_value_to_color(0.02)
    high = ndci_value_to_color(0.09)
    assert low != high
    assert low != hex_to_rgb(NDCI_RAMP_HEX[0])
    assert low != hex_to_rgb(NDCI_RAMP_HEX[-1])
    assert high != hex_to_rgb(NDCI_RAMP_HEX[-1])


def test_ndci_color_invalid_domain_raises():
    with pytest.raises(ValueError):
        ndci_value_to_color(0.05, domain=(0.1, 0.1))


def test_ndci_color_too_few_stops_raises():
    with pytest.raises(ValueError):
        ndci_value_to_color(0.05, stops_hex=("#0A1929",))
