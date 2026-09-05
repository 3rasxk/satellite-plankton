"""
Acceptance gate for the Sentinel-2 buffer water mask, driven by the
499-point ground-truth fixture `data/validation/water_mask_truth.json`.

Runs entirely offline. The fixture stores, per grid point, everything the
water rule needs as plain numbers -- `buffer_px`, `jrc_occ_valid`,
`jrc_occ_water`, `etopo_m` -- so the rule can be replayed pixel by pixel
without an Earth Engine session. `is_water` (NDWI > 0 from a Cloud Score+
clearest-pixel composite) is the truth column: 400 water, 99 land.

What this file is for: showing that widening the mask does not let land
in. A recovery count alone would be easy to inflate by simply admitting
more pixels; the binding assertion here is the negative set.

What it is NOT: it does not exercise the `ee.Image` expression in
`sentinel2._water_mask_image`, only the numpy reference implementation
`water_pixel_mask` that states the same rule. See `sentinel2.py`'s module
docstring on that split and its accepted drift risk.

`23_10` (Chao Phraya river mouth) is the one land point the mask admits.
It is NDWI -0.220 while JRC itself reports 30 of 30 buffer pixels as
water -- a real tidal mudflat, the exact turbid river-mouth case the
module docstring warns about. It leaked before this change and it leaks
after it; it is asserted explicitly below so it can never become an
unnoticed regression.

`23_18` and `23_19` are two further land points the mask admits, and
they are NEW here. They are not caused by the ETOPO1 fallback -- both
have ETOPO1 +2 m, so bathymetry calls them land. They are admitted
because JRC itself reports 5-of-16 and 2-of-13 buffer pixels as >= 50%
water, and the old code only excluded them as a side effect of the
`toList` length-mismatch guard that this change deleted as the root
cause of the offshore discards. See
`test_new_land_leaks_come_from_deleting_the_zip_not_from_etopo1`, which
pins that attribution down rather than leaving it as a claim.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.sentinel2 import DEFAULT_MIN_WATER_OCCURRENCE_PCT, water_pixel_mask

FIXTURE_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "data"
    / "validation"
    / "water_mask_truth.json"
)

# The single pre-existing leak, expected to keep leaking.
KNOWN_PREEXISTING_LEAK = "23_10"

# Land points admitted only because the toList length-mismatch guard was
# deleted. Enumerated, not tolerated silently.
LEAKS_FROM_DELETING_THE_ZIP = {"23_18", "23_19"}


@pytest.fixture(scope="module")
def fixture_points():
    with FIXTURE_PATH.open() as handle:
        return json.load(handle)["points"]


def _buffer_occurrence(point):
    """Per-pixel JRC occurrence array for one point's sample buffer.

    Reconstructed from the fixture's counts, which is all the information
    JRC contributes to the decision:
      - `jrc_occ_water` pixels JRC says are water (occurrence >= 50)
      - `jrc_occ_valid - jrc_occ_water` pixels JRC says are land
      - `buffer_px - jrc_occ_valid` pixels JRC has no data for (NaN)
    The values 100.0 / 0.0 stand in for "above" and "below" the threshold;
    only their side of it is meaningful.
    """
    buffer_px = point["buffer_px"]
    valid = point["jrc_occ_valid"]
    water = point["jrc_occ_water"]
    assert 0 <= water <= valid <= buffer_px, point["point_id"]
    return np.concatenate(
        [
            np.full(water, 100.0),
            np.full(valid - water, 0.0),
            np.full(buffer_px - valid, np.nan),
        ]
    )


def _keeps_point(point, etopo_enabled=True):
    """True if at least one buffer pixel survives the water mask.

    That is exactly the condition under which `_resolve_sentinel2_scene`
    returns a reading instead of raising NoWaterPixelsError -- one
    surviving pixel is enough for `reduceRegion` to report a non-null
    mean and a non-zero count.
    """
    etopo = point["etopo_m"] if etopo_enabled else None
    mask = water_pixel_mask(
        _buffer_occurrence(point), etopo, DEFAULT_MIN_WATER_OCCURRENCE_PCT
    )
    return bool(mask.any())


def _confusion(points, etopo_enabled=True):
    kept_water, leaked_land, missed_water = [], [], []
    for point in points:
        keeps = _keeps_point(point, etopo_enabled)
        if point["is_water"]:
            (kept_water if keeps else missed_water).append(point["point_id"])
        elif keeps:
            leaked_land.append(point["point_id"])
    return kept_water, leaked_land, missed_water


# --------------------------------------------------------------------------
# Fixture integrity — if these fail the gate below means nothing.
# --------------------------------------------------------------------------


def test_fixture_has_the_expected_shape(fixture_points):
    assert len(fixture_points) == 499
    assert sum(1 for p in fixture_points if p["is_water"]) == 400
    assert sum(1 for p in fixture_points if not p["is_water"]) == 99


def test_jrc_has_no_data_over_a_fifth_of_the_grid(fixture_points):
    """The measured premise of this whole change: JRC Global Surface
    Water simply has nothing to say over open ocean, and the old mask
    read that silence as land."""
    zero = [p for p in fixture_points if p["jrc_occ_valid"] == 0]
    partial = [
        p for p in fixture_points if 0 < p["jrc_occ_valid"] < p["buffer_px"]
    ]
    assert len(zero) == 170
    assert len(partial) == 24

    open_water_jrc_cannot_see = [p for p in zero if p["is_water"]]
    assert len(open_water_jrc_cannot_see) == 97  # 19.4% of the grid


# --------------------------------------------------------------------------
# The gate.
# --------------------------------------------------------------------------


def test_no_land_point_is_admitted_beyond_the_enumerated_ones(fixture_points):
    """THE BINDING ASSERTION. Every one of the 99 land points must stay
    out, except the pre-existing Chao Phraya mudflat leak and the two
    points the deleted zip guard used to exclude by accident. Any other
    land point admitted is a failure -- an unreviewed one especially, so
    this asserts the exact set rather than a count."""
    _, leaked_land, _ = _confusion(fixture_points)
    expected = {KNOWN_PREEXISTING_LEAK} | LEAKS_FROM_DELETING_THE_ZIP
    assert set(leaked_land) == expected


def test_the_known_chao_phraya_mudflat_still_leaks_and_is_not_papered_over(
    fixture_points,
):
    """23_10 is NDWI -0.220 but JRC reports 30/30 water. Documented, not
    resolved: the mask has no way to disagree with JRC there, and nudging
    a threshold to exclude one point would be fitting to the fixture."""
    point = next(p for p in fixture_points if p["point_id"] == KNOWN_PREEXISTING_LEAK)
    assert point["is_water"] is False
    assert point["jrc_occ_water"] == point["buffer_px"] == 30
    assert _keeps_point(point) is True


def test_new_land_leaks_come_from_deleting_the_zip_not_from_etopo1(fixture_points):
    """Attribution, not excuse. Both 23_18 and 23_19 sit above sea level
    per ETOPO1, so the fallback calls them land; they are admitted purely
    on JRC's own partial-coverage verdict, which the old length-mismatch
    guard used to discard along with everything else in a partly-covered
    buffer. Turning the fallback off does not exclude them."""
    for point_id in sorted(LEAKS_FROM_DELETING_THE_ZIP):
        point = next(p for p in fixture_points if p["point_id"] == point_id)
        assert point["is_water"] is False
        assert point["etopo_m"] > 0, point_id  # bathymetry says land
        assert point["jrc_occ_water"] > 0, point_id  # JRC says some water
        assert 0 < point["jrc_occ_valid"] < point["buffer_px"], point_id  # partial
        assert _keeps_point(point, etopo_enabled=True) is True
        assert _keeps_point(point, etopo_enabled=False) is True  # not ETOPO1's doing


def test_etopo1_fallback_adds_no_land_leak_at_all(fixture_points):
    """The fallback's whole cost, measured: zero. Same land set admitted
    with and without it."""
    _, leaked_with, _ = _confusion(fixture_points, etopo_enabled=True)
    _, leaked_without, _ = _confusion(fixture_points, etopo_enabled=False)
    assert set(leaked_with) == set(leaked_without)


def test_measured_confusion_numbers(fixture_points):
    """The recovery half of the gate, pinned to exact counts so a later
    change has to restate them.

    JRC-only with the old length-mismatch guard scored 295/400 water kept,
    1/99 land leaked, 105 missed. This implementation scores 395/400
    kept, 3/99 leaked, 5 missed: +100 real open-water points recovered,
    +2 land points admitted (both attributed above)."""
    kept_water, leaked_land, missed_water = _confusion(fixture_points)
    assert len(kept_water) == 395
    assert len(leaked_land) == 3
    assert len(missed_water) == 5
    assert len(kept_water) + len(missed_water) == 400
    # The five still missed are named, not just counted: 23_16 is JRC-blind
    # and ETOPO1 +3 m; the other four have JRC coverage that says land
    # (14_3 and 23_4 partial, 19_1 and 23_7 full) and are above sea level
    # too, so no layer calls them water.
    assert sorted(missed_water) == ["14_3", "19_1", "23_16", "23_4", "23_7"]


def test_open_water_points_jrc_cannot_see_are_now_recovered(fixture_points):
    """The 97 water points JRC has zero coverage for -- 19.4% of the grid
    -- were all discarded before this change. Every one ETOPO1 places
    below sea level is now kept."""
    blind_spots = [
        p for p in fixture_points if p["is_water"] and p["jrc_occ_valid"] == 0
    ]
    assert len(blind_spots) == 97
    recovered = [p for p in blind_spots if _keeps_point(p)]
    still_missed = [p["point_id"] for p in blind_spots if not _keeps_point(p)]
    assert len(recovered) == 96
    # The one that stays out is genuinely above sea level per ETOPO1
    # (+3 m at 23_16, in the Chao Phraya delta) -- a ~1.85 km bathymetry
    # cell disagreeing with a 10 m NDWI reading near shore, not a rule
    # failure. Named so the residue is visible rather than hidden inside
    # a count.
    assert still_missed == ["23_16"]
    for point in blind_spots:
        if not _keeps_point(point):
            assert point["etopo_m"] >= 0


def test_no_point_is_kept_without_a_layer_actually_saying_water(fixture_points):
    """Nothing is admitted by default. Every kept point has either a JRC
    water pixel or a JRC-blind pixel that ETOPO1 puts below sea level --
    no third path exists."""
    kept_water, leaked_land, _ = _confusion(fixture_points)
    by_id = {p["point_id"]: p for p in fixture_points}
    for point_id in kept_water + leaked_land:
        point = by_id[point_id]
        jrc_says_water = point["jrc_occ_water"] > 0
        etopo_says_water = (
            point["jrc_occ_valid"] < point["buffer_px"] and point["etopo_m"] < 0
        )
        assert jrc_says_water or etopo_says_water, point_id
