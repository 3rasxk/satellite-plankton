"""
Unit tests for the GEE-free cloud/land-water masking logic in
`src/sentinel2.py`, exercised entirely with synthetic pixel arrays — no
Earth Engine session required or contacted.
"""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.sentinel2 import (
    NoWaterPixelsError,
    compute_cloud_fraction,
    masked_band_mean,
    water_pixel_mask,
)


def test_cloud_fraction_all_clear():
    # SCL=6 is water (not in the cloud-class list) -> 0% cloud.
    scl = np.array([6, 6, 6, 6])
    assert compute_cloud_fraction(scl) == 0.0


def test_cloud_fraction_all_cloud():
    # SCL=9 is high-probability cloud.
    scl = np.array([9, 9, 9, 9])
    assert compute_cloud_fraction(scl) == 1.0


def test_cloud_fraction_mixed():
    scl = np.array([6, 6, 9, 3])  # 2 water, 1 cloud, 1 cloud-shadow
    assert compute_cloud_fraction(scl) == pytest.approx(0.5)


def test_cloud_fraction_empty_array_is_fully_unusable():
    assert compute_cloud_fraction(np.array([])) == 1.0


def test_water_pixel_mask_threshold():
    occurrence = np.array([0, 20, 49, 50, 80, 100])
    mask = water_pixel_mask(occurrence, min_occurrence_pct=50.0)
    assert list(mask) == [False, False, False, True, True, True]


def test_water_pixel_mask_treats_nan_as_land():
    occurrence = np.array([np.nan, 100.0])
    mask = water_pixel_mask(occurrence, min_occurrence_pct=50.0)
    assert list(mask) == [False, True]


def test_masked_band_mean_basic():
    band = np.array([100.0, 200.0, 300.0, 400.0])
    mask = np.array([True, False, True, False])
    assert masked_band_mean(band, mask) == pytest.approx(200.0)  # mean(100, 300)


def test_masked_band_mean_all_excluded_raises():
    band = np.array([100.0, 200.0])
    mask = np.array([False, False])
    with pytest.raises(NoWaterPixelsError):
        masked_band_mean(band, mask)


def test_masked_band_mean_shape_mismatch_raises():
    with pytest.raises(ValueError):
        masked_band_mean(np.array([1.0, 2.0]), np.array([True]))


def test_combined_cloud_and_water_mask_realistic_buffer():
    """Simulate a 3x3 buffer straddling a river mouth: some land, some
    cloud, some clear water — only the clear-water pixels should survive.
    """
    scl = np.array([6, 6, 9, 4, 6, 6, 6, 3, 6])  # index 2=cloud, 3=veg(land), 7=shadow
    occurrence = np.array([90, 85, 90, 5, 95, 88, 92, 90, 91])
    band = np.array([120, 130, 999, 999, 140, 135, 128, 999, 132], dtype=float)

    cloud_mask = ~np.isin(scl, (0, 1, 3, 7, 8, 9, 10))
    water_mask = water_pixel_mask(occurrence, 50.0)
    combined = cloud_mask & water_mask

    # Expect indices 0,1,4,5,6,8 to survive (6 pixels); 2 (cloud), 3 (land),
    # 7 (shadow) excluded.
    assert combined.sum() == 6
    mean_val = masked_band_mean(band, combined)
    expected = np.mean([120, 130, 140, 135, 128, 132])
    assert mean_val == pytest.approx(expected)
