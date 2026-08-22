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
    build_water_cloud_mask,
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


def test_tight_buffer_cloud_fraction_can_be_zero_while_wider_region_has_real_cloud():
    """Regression/documentation test for a human-audit finding (project
    orchestrator, 2026-08-19/23): `get_sentinel2_bands` (this module)
    computes cloud_fraction over a tight ~30 m buffer (DEFAULT_BUFFER_M),
    while `imagery.py`'s `get_true_color_image`/`get_ndci_heatmap` render
    their thumbnail over a much wider ~500 m buffer
    (DEFAULT_IMAGE_REGION_BUFFER_M) around the same center point on the
    same resolved scene (imagery.py's own module docstring, "Visualization
    region vs. numeric sample region"). Live-confirmed for the Cha-am grid
    site (12.75, 100.05): 30 m and 150 m buffers both read
    cloud_fraction=0.0 on the resolved scene (actual_date=2026-08-18),
    while that same scene's actual 500 m image-rendering buffer reads
    cloud_fraction=0.1666 (16.7%). That is NOT a bug -- the tight buffer
    genuinely never saw the cloud, because the cloud sits entirely outside
    its (smaller) sampled ground area. This test locks that shape in with
    synthetic SCL pixels so it can't silently regress into looking like a
    calculation bug later.
    """
    # Tight ~30 m buffer sample: entirely clear water (SCL=6, not a
    # cloud class).
    tight_scl = np.array([6, 6, 6, 6, 6, 6, 6, 6, 6])
    assert compute_cloud_fraction(tight_scl) == 0.0

    # Wide ~500 m buffer sample: a strict superset of the tight buffer's
    # own pixels (still all clear) PLUS additional pixels that exist only
    # in the wider ground area -- some of which are real cloud (SCL=9).
    # This mirrors the real geometric relationship: the 500 m render
    # region contains the 30 m sample region, not a disjoint area.
    outside_tight_buffer = np.array([9, 9, 6, 6, 6, 6])  # 2 of 6 extra pixels are cloud
    wide_scl = np.concatenate([tight_scl, outside_tight_buffer])

    wide_cloud_fraction = compute_cloud_fraction(wide_scl)
    assert wide_cloud_fraction > 0.0
    assert wide_cloud_fraction == pytest.approx(2 / 15)

    # The tight buffer's own reading is unaffected by pixels it never
    # sampled -- same array, same result as at the top of this test.
    assert compute_cloud_fraction(tight_scl) == 0.0


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


def test_build_water_cloud_mask_empty_occurrence_raises_typed_error():
    """Regression test for a live bug: a land/beach point returns a
    full-length SCL list (GEE's per-band toList reducer still classifies
    every pixel) but an EMPTY occurrence list, because JRC Global Surface
    Water has no data outside historically-water pixels. The old code did
    `cloud_mask & water_mask[: cloud_mask.size]`, which numpy cannot
    broadcast when water_mask is shorter (e.g. shape (30,) vs (0,)),
    crashing with a raw ValueError instead of the typed
    NoWaterPixelsError the docstring already promises for an all-land
    buffer. This must raise NoWaterPixelsError, not ValueError.
    """
    scl = np.array([6] * 30)  # 30 pixels, all "water" per SCL classification
    occurrence = np.array([])  # JRC occurrence band returned nothing at all

    with pytest.raises(NoWaterPixelsError):
        build_water_cloud_mask(scl, occurrence)


def test_build_water_cloud_mask_shorter_occurrence_raises_typed_error():
    """Same gotcha, but occurrence returns some pixels -- just fewer than
    SCL, rather than zero. Any length mismatch is untrustworthy (no valid
    positional correspondence between the two independently-reduced
    lists), so this must also raise NoWaterPixelsError, not silently
    truncate/broadcast or raise a bare ValueError.
    """
    scl = np.array([6] * 30)
    occurrence = np.array([90.0] * 12)  # shorter than scl, not empty

    with pytest.raises(NoWaterPixelsError):
        build_water_cloud_mask(scl, occurrence)


def test_build_water_cloud_mask_matched_lengths_still_works():
    """Sanity check: when SCL and occurrence lists are the same length
    (the normal/expected case), build_water_cloud_mask still produces the
    correct combined boolean mask instead of always raising.
    """
    scl = np.array([6, 6, 9, 6])  # index 2 = cloud
    occurrence = np.array([90.0, 20.0, 95.0, 80.0])  # index 1 = land (<50%)

    mask = build_water_cloud_mask(scl, occurrence)
    assert list(mask) == [True, False, False, True]
