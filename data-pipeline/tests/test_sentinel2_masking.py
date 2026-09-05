"""
Unit tests for the GEE-free cloud/land-water masking logic in
`src/sentinel2.py`, exercised entirely with synthetic pixel arrays and
synthetic `reduceRegion` result dicts — no Earth Engine session required
or contacted.

Two kinds of function are covered here, and the distinction matters when
reading a failure:

  - `cloud_fraction_from_stats` / `band_means_from_stats` are *executed in
    production*. They parse the plain dict `reduceRegion(...).getInfo()`
    returns (numbers, strings and None — no `ee` objects), which is the
    typed boundary CLAUDE.md §7 relies on to keep these suites offline. A
    failure here is a real production bug.
  - `compute_cloud_fraction` / `water_pixel_mask` are plain-numpy
    *reference implementations* of the two masking rules the pipeline now
    evaluates server-side as `ee.Image` expressions. A failure here means
    the stated rule is broken; it does not by itself prove the `ee`
    expression is broken, because the two are written separately (see
    `sentinel2.py`'s module docstring — the drift risk is acknowledged
    there). The rule is the thing worth testing, and an `ee` expression
    cannot be evaluated without a live session.

The 499-point fixture gate for the water rule lives in
`test_water_mask_fixture.py`.
"""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.sentinel2 import (
    BANDS,
    NoWaterPixelsError,
    band_means_from_stats,
    cloud_fraction_from_stats,
    compute_cloud_fraction,
    water_pixel_mask,
)

NAN = float("nan")


# --------------------------------------------------------------------------
# compute_cloud_fraction — reference implementation of the SCL cloud rule.
# --------------------------------------------------------------------------


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

    Still stated over SCL pixel arrays even though the pipeline now
    computes the same ratio server-side, because the finding is about the
    *rule* applied to two different pixel sets -- which is exactly what
    this reference implementation expresses.
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


# --------------------------------------------------------------------------
# water_pixel_mask — reference implementation of the JRC-else-ETOPO1 rule.
# --------------------------------------------------------------------------


def test_water_mask_jrc_present_and_water():
    """JRC has data and says water (>= 50% occurrence) -> water. ETOPO1
    is not consulted, even when it disagrees."""
    occurrence = np.array([50.0, 80.0, 100.0])
    etopo = np.array([5.0, 5.0, 5.0])  # ETOPO1 says land at all three
    assert list(water_pixel_mask(occurrence, etopo)) == [True, True, True]


def test_water_mask_jrc_present_and_land():
    """JRC has data and says land (< 50%) -> land, even where ETOPO1 says
    below sea level. JRC is authoritative wherever it has an opinion --
    near shore is exactly where a 30 m water product beats a ~1.85 km
    bathymetry grid."""
    occurrence = np.array([0.0, 20.0, 49.0])
    etopo = np.array([-30.0, -30.0, -30.0])  # ETOPO1 says water at all three
    assert list(water_pixel_mask(occurrence, etopo)) == [False, False, False]


def test_water_mask_threshold_is_inclusive_at_fifty():
    occurrence = np.array([0, 20, 49, 50, 80, 100], dtype=float)
    mask = water_pixel_mask(occurrence, None, min_occurrence_pct=50.0)
    assert list(mask) == [False, False, False, True, True, True]


def test_water_mask_jrc_absent_and_etopo_negative_is_water():
    """THE NEW PATH. JRC Global Surface Water is a Landsat-derived
    *surface water* product with no data over open ocean; reading its
    silence as "land" discarded ~19% of the upper-Gulf scan grid, and the
    further offshore a point sat the more certainly it was thrown away.
    Where JRC has nothing, ETOPO1 below sea level means water."""
    occurrence = np.array([NAN, NAN, NAN])
    etopo = np.array([-1.0, -7.0, -60.0])
    assert list(water_pixel_mask(occurrence, etopo)) == [True, True, True]


def test_water_mask_jrc_absent_and_etopo_positive_is_land():
    """JRC silent inland/on a beach: ETOPO1 above sea level -> land. Sea
    level itself (0 m) is land, not water -- the test is strictly < 0."""
    occurrence = np.array([NAN, NAN, NAN])
    etopo = np.array([0.0, 8.0, 40.0])
    assert list(water_pixel_mask(occurrence, etopo)) == [False, False, False]


def test_water_mask_partial_jrc_coverage_decides_per_pixel():
    """Partial JRC coverage across one buffer -- 24 of the 499 fixture
    points look like this. The JRC-covered pixels are decided by JRC, the
    uncovered ones by ETOPO1, independently. This is the documented
    per-pixel choice: a buffer-level rule would let the two JRC-covered
    pixels here decide the fate of the two JRC has never seen."""
    occurrence = np.array([90.0, 10.0, NAN, NAN])
    etopo = np.array([-5.0, -5.0, -5.0, 12.0])
    #                  ^JRC water  ^JRC land  ^ETOPO water  ^ETOPO land
    assert list(water_pixel_mask(occurrence, etopo)) == [True, False, True, False]


def test_water_mask_etopo_none_falls_back_to_land():
    """No bathymetry available at all (etopo_values=None) -> JRC's
    no-data pixels are land, i.e. exactly the pre-fallback behaviour.
    Missing data never invents water."""
    occurrence = np.array([90.0, NAN, 10.0])
    assert list(water_pixel_mask(occurrence, None)) == [True, False, False]


def test_water_mask_etopo_nan_pixel_falls_back_to_land():
    """Per-pixel missing bathymetry (NaN) is land too -- a pixel neither
    layer covers is excluded, not admitted."""
    occurrence = np.array([NAN, NAN])
    etopo = np.array([NAN, -5.0])
    assert list(water_pixel_mask(occurrence, etopo)) == [False, True]


def test_water_mask_accepts_a_scalar_etopo_for_the_whole_buffer():
    """The validation fixture stores one ETOPO1 elevation per grid point,
    not one per pixel; a scalar broadcasts across the buffer."""
    occurrence = np.array([NAN, 90.0, 10.0, NAN])
    assert list(water_pixel_mask(occurrence, -7)) == [True, True, False, True]


def test_water_mask_every_pixel_masked_out():
    """All-land buffer: the mask is all-False. Producing the empty mask is
    this function's job; turning it into NoWaterPixelsError is
    `band_means_from_stats`'s (server-side: count == 0)."""
    occurrence = np.array([0.0, NAN, 10.0])
    etopo = np.array([3.0, 8.0, 2.0])
    mask = water_pixel_mask(occurrence, etopo)
    assert not mask.any()


def test_water_mask_shape_mismatch_is_a_caller_error_not_a_data_condition():
    """A mis-shaped ETOPO1 array is a programming mistake, so it raises
    ValueError. It must NOT be laundered into NoWaterPixelsError -- that
    conflation (a length mismatch reported as "this buffer is land") is
    the exact bug this rewrite removed."""
    with pytest.raises(ValueError):
        water_pixel_mask(np.array([90.0, 10.0]), np.array([-5.0]))


def test_water_mask_no_length_coupling_between_layers_remains():
    """There is no longer any "same number of pixels" contract between
    the cloud layer and the water layer: the mask is built server-side as
    an image, so a JRC-empty buffer is just a buffer ETOPO1 answers for.
    A 30-pixel buffer JRC knows nothing about now yields 30 water pixels
    offshore -- where the old parallel-list code raised
    NoWaterPixelsError purely because occurrence's list came back empty."""
    occurrence = np.full(30, NAN)
    mask = water_pixel_mask(occurrence, -12.0)
    assert mask.sum() == 30


# --------------------------------------------------------------------------
# cloud_fraction_from_stats — executed in production.
# --------------------------------------------------------------------------


def _stats(cloud_mean=0.0, cloud_count=28, band_mean=500.0, band_count=28):
    """A synthetic `reduceRegion(mean.combine(count)).getInfo()` result."""
    out = {"cloud_flag_mean": cloud_mean, "cloud_flag_count": cloud_count}
    for band in BANDS:
        out[f"{band}_mean"] = band_mean
        out[f"{band}_count"] = band_count
    return out


def test_cloud_fraction_from_stats_reads_the_mean_of_the_flag_band():
    assert cloud_fraction_from_stats(_stats(cloud_mean=0.25)) == pytest.approx(0.25)


def test_cloud_fraction_from_stats_zero_count_is_fully_unusable():
    """No valid SCL pixel in the buffer -> 1.0, the same "can't trust this
    reading" answer `compute_cloud_fraction` gives for an empty array. The
    candidate loop then rejects the scene on max_cloud_fraction."""
    assert cloud_fraction_from_stats(_stats(cloud_mean=None, cloud_count=0)) == 1.0


def test_cloud_fraction_from_stats_null_mean_is_fully_unusable():
    """GEE returns null (None) for a mean over zero pixels."""
    assert cloud_fraction_from_stats(_stats(cloud_mean=None, cloud_count=12)) == 1.0


def test_cloud_fraction_from_stats_missing_keys_are_fully_unusable():
    assert cloud_fraction_from_stats({}) == 1.0


def test_cloud_fraction_from_stats_clamps_into_zero_one():
    assert cloud_fraction_from_stats(_stats(cloud_mean=1.0000001)) == 1.0
    assert cloud_fraction_from_stats(_stats(cloud_mean=-1e-9)) == 0.0


# --------------------------------------------------------------------------
# band_means_from_stats — executed in production.
# --------------------------------------------------------------------------


def test_band_means_from_stats_returns_all_five_bands():
    means = band_means_from_stats(_stats(band_mean=421.5))
    assert set(means) == set(BANDS)
    assert all(v == pytest.approx(421.5) for v in means.values())


def test_band_means_from_stats_zero_surviving_pixels_raises_typed_error():
    """The all-land buffer. `updateMask` left nothing, so GEE reports
    count 0 and a null mean, and this must be NoWaterPixelsError --
    `no_water_pixels` is a real API status and the candidate loop's
    continue-on-failure depends on the type."""
    with pytest.raises(NoWaterPixelsError):
        band_means_from_stats(_stats(band_mean=None, band_count=0))


def test_band_means_from_stats_one_bad_band_still_raises():
    """B5/B6 are 20 m bands resampled to 10 m; if any single band came
    back empty the reading is not trustworthy, so it fails as a whole
    rather than returning four bands and a hole."""
    stats = _stats()
    stats["B5_mean"] = None
    stats["B5_count"] = 0
    with pytest.raises(NoWaterPixelsError):
        band_means_from_stats(stats)


def test_band_means_from_stats_missing_keys_raise_typed_error():
    with pytest.raises(NoWaterPixelsError):
        band_means_from_stats({})


def test_band_means_from_stats_reports_which_band_failed():
    stats = _stats()
    stats["B4_mean"] = None
    stats["B4_count"] = 0
    with pytest.raises(NoWaterPixelsError, match="B4"):
        band_means_from_stats(stats)
