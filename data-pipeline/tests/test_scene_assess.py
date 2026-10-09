"""
Offline tests for `src/scene_assess.py` -- the per-date cloud/water decision
behind the latest-scene policy. No Earth Engine session is required or
contacted.

What is exercised and what is not:

  - `decide`, `combine_tiles`, `tile_stats_from_features` and
    `scene_thresholds` are pure and executed in production. They work on
    plain numbers and the plain feature dicts that
    `FeatureCollection.getInfo()["features"]` returns.
  - `assess_new_scenes` is tested through its `_fetch` seam with stubs, so
    the only thing replaced is the network call.
  - `_scene_count_image` (the per-scene 0/1 stack) is run against a small
    numpy double together with the REAL `sentinel2._cloud_flag_image`, so
    the cloud-flag-over-water-only rule and the partition of observed
    water into cloud + clear are checked as production code.
  - `_fetch_scene_stats` (the only `getInfo`) is checked structurally with
    a recording mock: which reducer, `bestEffort`, `maxPixels`, scale,
    geometry and skip filter it asks Earth Engine for. That is not evidence
    of how real Earth Engine evaluates those requests -- only a live call
    is (see the task report's live check).
"""

import dataclasses
from unittest.mock import MagicMock

import numpy as np
import pytest

from src import scene_assess, sentinel2
from src.auth import GEEConfigError

CLOUD_VAR = "RASTER_SCENE_MAX_CLOUD_FRACTION"
WATER_VAR = "RASTER_SCENE_MIN_WATER_PIXELS"

POLYGON = ((13.5, 99.9), (13.6, 101.0), (12.7, 101.0), (12.5, 99.9))


@pytest.fixture(autouse=True)
def _no_threshold_env(monkeypatch):
    """A developer shell or a loaded .env must not leak into these tests."""
    monkeypatch.delenv(CLOUD_VAR, raising=False)
    monkeypatch.delenv(WATER_VAR, raising=False)


def tile(date, *, cloud, valid, scene_id=None):
    """One per-scene partial-sum dict, shaped like `_fetch` returns."""
    out = {
        "date": date,
        "cloud_count": cloud,
        "valid_count": valid,
        "water_count": cloud + valid,
    }
    if scene_id is not None:
        out["scene_id"] = scene_id
    return out


def stub_fetch(tiles, seen=None):
    def fetch(polygon, since_date, scale_m, *, skip_dates):
        if seen is not None:
            seen.append((polygon, since_date, scale_m, skip_dates))
        return [dict(t) for t in tiles]

    return fetch


def decide(cloud_fraction, water_pixels, max_cloud_fraction=0.5, min_water_pixels=1000):
    return scene_assess.decide(
        cloud_fraction=cloud_fraction,
        water_pixels=water_pixels,
        max_cloud_fraction=max_cloud_fraction,
        min_water_pixels=min_water_pixels,
    )


# --------------------------------------------------------------------------
# decide -- truth table
# --------------------------------------------------------------------------


def test_clear_scene_with_enough_water_passes():
    assert decide(0.1, 5000) == ("passed", None)


def test_cloud_exactly_at_threshold_passes():
    """Reject only when strictly greater -- the same comparison the point
    path (`_resolve_sentinel2_scene`) and history rows use."""
    assert decide(0.5, 5000) == ("passed", None)


def test_cloud_above_threshold_is_rejected_with_measured_fraction():
    assert decide(0.83, 5000) == ("rejected_cloud", "cloud 83% > 50%")


def test_fully_clouded_scene_is_rejected_for_cloud_not_for_water():
    """A 100%-cloud day over the whole polygon saw plenty of water; its
    cause is weather, and the reason must say so."""
    assert decide(1.0, 49_000) == ("rejected_cloud", "cloud 100% > 50%")


def test_water_below_minimum_is_rejected():
    assert decide(0.0, 999) == (
        "rejected_no_water",
        "999 unmasked water pixels < 1000",
    )


def test_water_exactly_at_minimum_passes():
    assert decide(0.0, 1000) == ("passed", None)


def test_water_check_comes_before_cloud_check():
    assert decide(0.9, 10) == ("rejected_no_water", "10 unmasked water pixels < 1000")


def test_reason_uses_the_thresholds_given():
    assert decide(0.3, 5000, max_cloud_fraction=0.2) == (
        "rejected_cloud",
        "cloud 30% > 20%",
    )
    assert decide(0.0, 4999, min_water_pixels=5000) == (
        "rejected_no_water",
        "4999 unmasked water pixels < 5000",
    )


def test_none_cloud_with_zero_water_is_no_water():
    assert decide(None, 0) == ("rejected_no_water", "0 unmasked water pixels < 1000")


@pytest.mark.parametrize("water_pixels", [1, 999, 1000, 50_000])
def test_none_cloud_with_some_water_raises_never_defaults(water_pixels):
    """A fraction is undefined only when nothing was observed. Any other
    None is a broken input, not a decision."""
    with pytest.raises(ValueError, match="cloud_fraction"):
        decide(None, water_pixels)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -0.01, 1.01, True])
def test_invalid_cloud_fraction_raises(bad):
    """NaN in particular: `nan > 0.5` is False, so without this guard a NaN
    fraction would silently pass."""
    with pytest.raises(ValueError, match="cloud_fraction"):
        decide(bad, 5000)


@pytest.mark.parametrize("bad", [-1, 1.5, "100", None, True])
def test_invalid_water_pixels_raises(bad):
    with pytest.raises(ValueError, match="water_pixels"):
        decide(0.1, bad)


@pytest.mark.parametrize("bad", [0, -0.1, 1.5, float("nan")])
def test_invalid_max_cloud_fraction_raises(bad):
    with pytest.raises(ValueError, match="max_cloud_fraction"):
        decide(0.1, 5000, max_cloud_fraction=bad)


@pytest.mark.parametrize("bad", [0, -5, 10.0, True])
def test_invalid_min_water_pixels_raises(bad):
    with pytest.raises(ValueError, match="min_water_pixels"):
        decide(0.1, 5000, min_water_pixels=bad)


def test_decide_is_keyword_only():
    with pytest.raises(TypeError):
        scene_assess.decide(0.1, 5000, 0.5, 1000)


# --------------------------------------------------------------------------
# combine_tiles -- partial sums, never a mean of means
# --------------------------------------------------------------------------


def test_combine_tiles_weights_by_pixel_count_not_mean_of_means():
    clear_small = tile("2026-10-08", cloud=0, valid=100)  # 100 px @ 0.0
    cloudy_big = tile("2026-10-08", cloud=900, valid=0)  # 900 px @ 1.0
    combined = scene_assess.combine_tiles([clear_small, cloudy_big])
    assert combined["cloud_fraction"] == pytest.approx(0.9)
    assert combined["cloud_fraction"] != pytest.approx(0.5)
    assert combined["water_pixels"] == 1000


def test_combine_tiles_sums_every_partial():
    combined = scene_assess.combine_tiles(
        [tile("2026-10-08", cloud=30, valid=70), tile("2026-10-08", cloud=10, valid=390)]
    )
    assert combined["cloud_count"] == 40
    assert combined["valid_count"] == 460
    assert combined["water_count"] == 500
    assert combined["water_pixels"] == 500
    assert combined["cloud_fraction"] == pytest.approx(40 / 500)


def test_single_tile_is_its_own_fraction():
    combined = scene_assess.combine_tiles([tile("2026-10-08", cloud=25, valid=75)])
    assert combined["cloud_fraction"] == pytest.approx(0.25)
    assert combined["water_pixels"] == 100


def test_tile_that_saw_no_water_contributes_nothing():
    combined = scene_assess.combine_tiles(
        [tile("2026-10-08", cloud=0, valid=0), tile("2026-10-08", cloud=20, valid=80)]
    )
    assert combined["cloud_fraction"] == pytest.approx(0.2)
    assert combined["water_pixels"] == 100


def test_no_observed_water_anywhere_gives_none_fraction():
    combined = scene_assess.combine_tiles(
        [tile("2026-10-08", cloud=0, valid=0), tile("2026-10-08", cloud=0, valid=0)]
    )
    assert combined["cloud_fraction"] is None
    assert combined["water_pixels"] == 0


def test_combine_tiles_does_not_mutate_input():
    tiles = [tile("2026-10-08", cloud=1, valid=2)]
    before = [dict(t) for t in tiles]
    scene_assess.combine_tiles(tiles)
    assert tiles == before


def test_combine_tiles_rejects_empty_input():
    with pytest.raises(ValueError):
        scene_assess.combine_tiles([])


def test_combine_tiles_rejects_inconsistent_partition():
    """cloud + clear must equal observed water: both are sums over the same
    masked pixels, so a mismatch means the partial sums are broken."""
    broken = {"date": "2026-10-08", "cloud_count": 10, "valid_count": 10, "water_count": 30}
    with pytest.raises(ValueError, match="water_count"):
        scene_assess.combine_tiles([broken])


@pytest.mark.parametrize(
    "key, value",
    [
        ("cloud_count", -1),
        ("valid_count", 1.5),
        ("water_count", "30"),
        ("cloud_count", True),
        ("valid_count", None),
    ],
)
def test_combine_tiles_rejects_non_count_values(key, value):
    bad = tile("2026-10-08", cloud=10, valid=20)
    bad[key] = value
    with pytest.raises(ValueError, match=key):
        scene_assess.combine_tiles([bad])


def test_combine_tiles_rejects_missing_key():
    bad = tile("2026-10-08", cloud=10, valid=20)
    del bad["water_count"]
    with pytest.raises(ValueError, match="water_count"):
        scene_assess.combine_tiles([bad])


def test_combine_tiles_refuses_to_mix_dates():
    with pytest.raises(ValueError, match="date"):
        scene_assess.combine_tiles(
            [tile("2026-10-08", cloud=1, valid=1), tile("2026-10-07", cloud=1, valid=1)]
        )


# --------------------------------------------------------------------------
# tile_stats_from_features -- parsing the getInfo boundary
# --------------------------------------------------------------------------


def feature(**properties):
    return {"type": "Feature", "geometry": None, "properties": properties}


def test_features_parse_to_integer_partial_sums():
    tiles = scene_assess.tile_stats_from_features(
        [
            feature(
                date="2026-10-08",
                cloud_count=12.0,
                valid_count=88,
                water_count=100.0,
                scene_id="20261008T033541_20261008T034500_T47PPR",
            )
        ]
    )
    assert tiles == [
        {
            "date": "2026-10-08",
            "cloud_count": 12,
            "valid_count": 88,
            "water_count": 100,
            "scene_id": "20261008T033541_20261008T034500_T47PPR",
        }
    ]
    assert all(type(tiles[0][k]) is int for k in scene_assess.COUNT_KEYS)


def test_null_or_dropped_sum_reads_as_zero_pixels():
    """A sum over zero pixels: Earth Engine may return 0 or null, and
    getInfo drops null properties. Either way nothing was observed."""
    tiles = scene_assess.tile_stats_from_features(
        [feature(date="2026-10-08", cloud_count=None, valid_count=None)]
    )
    assert [tiles[0][k] for k in scene_assess.COUNT_KEYS] == [0, 0, 0]
    assert tiles[0]["scene_id"] is None


@pytest.mark.parametrize("bad", [12.5, -1, "12", True])
def test_non_count_sum_is_refused(bad):
    """A fractional sum means a weighted reducer slipped in: refuse it."""
    with pytest.raises(ValueError, match="cloud_count"):
        scene_assess.tile_stats_from_features(
            [feature(date="2026-10-08", cloud_count=bad, valid_count=0, water_count=0)]
        )


@pytest.mark.parametrize("bad", [None, "", "2026-10-8", "08/10/2026", 1791000000000])
def test_feature_without_a_usable_date_is_refused_never_guessed(bad):
    props = {"cloud_count": 0, "valid_count": 1, "water_count": 1}
    if bad is not None:
        props["date"] = bad
    with pytest.raises(ValueError, match="date"):
        scene_assess.tile_stats_from_features([feature(**props)])


def test_parse_keys_are_the_documented_partial_sum_keys():
    assert scene_assess.COUNT_KEYS == ("cloud_count", "valid_count", "water_count")
    assert scene_assess.DATE_KEY == "date"


# --------------------------------------------------------------------------
# scene_thresholds -- env, read at call time
# --------------------------------------------------------------------------


def test_thresholds_default_to_the_system_cloud_constant_and_1000():
    assert scene_assess.scene_thresholds() == (sentinel2.DEFAULT_MAX_CLOUD_FRACTION, 1000)


def test_default_cloud_threshold_is_read_live_not_frozen(monkeypatch):
    monkeypatch.setattr(sentinel2, "DEFAULT_MAX_CLOUD_FRACTION", 0.3)
    assert scene_assess.scene_thresholds() == (0.3, 1000)


def test_thresholds_read_env_at_call_time(monkeypatch):
    monkeypatch.setenv(CLOUD_VAR, "0.2")
    monkeypatch.setenv(WATER_VAR, "2500")
    assert scene_assess.scene_thresholds() == (0.2, 2500)
    monkeypatch.setenv(CLOUD_VAR, " 1 ")
    monkeypatch.setenv(WATER_VAR, " 1 ")
    assert scene_assess.scene_thresholds() == (1.0, 1)


def test_blank_env_uses_defaults(monkeypatch):
    monkeypatch.setenv(CLOUD_VAR, "  ")
    monkeypatch.setenv(WATER_VAR, "")
    assert scene_assess.scene_thresholds() == (sentinel2.DEFAULT_MAX_CLOUD_FRACTION, 1000)


@pytest.mark.parametrize("raw", ["abc", "0", "-0.1", "1.5", "nan", "inf", "50%"])
def test_invalid_cloud_env_raises_naming_the_variable(monkeypatch, raw):
    monkeypatch.setenv(CLOUD_VAR, raw)
    with pytest.raises(ValueError, match=CLOUD_VAR) as excinfo:
        scene_assess.scene_thresholds()
    assert isinstance(excinfo.value, GEEConfigError)


@pytest.mark.parametrize("raw", ["abc", "0", "-5", "10.5", "1e3", "1000.0"])
def test_invalid_water_env_raises_naming_the_variable(monkeypatch, raw):
    monkeypatch.setenv(WATER_VAR, raw)
    with pytest.raises(ValueError, match=WATER_VAR) as excinfo:
        scene_assess.scene_thresholds()
    assert isinstance(excinfo.value, GEEConfigError)


# --------------------------------------------------------------------------
# assess_new_scenes -- through the _fetch seam
# --------------------------------------------------------------------------


def test_tiles_of_one_date_merge_into_one_weighted_assessment():
    tiles = [
        tile("2026-10-08", cloud=0, valid=100, scene_id="a"),
        tile("2026-10-08", cloud=900, valid=0, scene_id="b"),
    ]
    result = scene_assess.assess_new_scenes(
        POLYGON, "2026-10-01", min_water_pixels=500, _fetch=stub_fetch(tiles)
    )
    assert len(result) == 1
    only = result[0]
    assert only.acquisition_date == "2026-10-08"
    assert only.cloud_fraction == pytest.approx(0.9)
    assert only.water_pixels == 1000
    assert only.decision == "rejected_cloud"
    assert only.reason == "cloud 90% > 50%"


def test_assessments_are_newest_date_first():
    tiles = [
        tile("2026-10-03", cloud=0, valid=2000),
        tile("2026-10-08", cloud=0, valid=2000),
        tile("2026-09-28", cloud=0, valid=2000),
        tile("2026-10-08", cloud=0, valid=500),
    ]
    result = scene_assess.assess_new_scenes(POLYGON, "2026-09-25", _fetch=stub_fetch(tiles))
    assert [a.acquisition_date for a in result] == ["2026-10-08", "2026-10-03", "2026-09-28"]
    assert result[0].water_pixels == 2500


def test_mixed_decisions_are_each_recorded():
    tiles = [
        tile("2026-10-08", cloud=1700, valid=300),  # 85% cloud
        tile("2026-10-06", cloud=0, valid=40),  # grazes the polygon
        tile("2026-10-03", cloud=200, valid=1800),  # 10% cloud
    ]
    result = scene_assess.assess_new_scenes(POLYGON, "2026-10-01", _fetch=stub_fetch(tiles))
    assert [(a.acquisition_date, a.decision, a.reason) for a in result] == [
        ("2026-10-08", "rejected_cloud", "cloud 85% > 50%"),
        ("2026-10-06", "rejected_no_water", "40 unmasked water pixels < 1000"),
        ("2026-10-03", "passed", None),
    ]


def test_date_with_no_observed_water_is_rejected_with_none_fraction():
    tiles = [tile("2026-10-08", cloud=0, valid=0)]
    (only,) = scene_assess.assess_new_scenes(POLYGON, "2026-10-01", _fetch=stub_fetch(tiles))
    assert only.cloud_fraction is None
    assert only.water_pixels == 0
    assert only.decision == "rejected_no_water"


def test_skip_dates_are_not_assessed_and_are_passed_to_the_fetch():
    tiles = [
        tile("2026-10-08", cloud=0, valid=2000),
        tile("2026-10-06", cloud=0, valid=2000),
        tile("2026-10-03", cloud=0, valid=2000),
    ]
    seen = []
    result = scene_assess.assess_new_scenes(
        POLYGON,
        "2026-10-01",
        skip_dates={"2026-10-08", "2026-10-03"},
        _fetch=stub_fetch(tiles, seen),
    )
    assert [a.acquisition_date for a in result] == ["2026-10-06"]
    assert seen[0][3] == frozenset({"2026-10-08", "2026-10-03"})


def test_fetch_receives_polygon_since_date_and_default_raster_scale():
    seen = []
    scene_assess.assess_new_scenes(POLYGON, "2026-10-01", _fetch=stub_fetch([], seen))
    assert seen == [(POLYGON, "2026-10-01", 200, frozenset())]


def test_scale_is_passed_through():
    seen = []
    scene_assess.assess_new_scenes(
        POLYGON, "2026-10-01", scale_m=100, _fetch=stub_fetch([], seen)
    )
    assert seen[0][2] == 100


def test_no_scenes_is_an_empty_list():
    assert scene_assess.assess_new_scenes(POLYGON, "2026-10-01", _fetch=stub_fetch([])) == []


def test_env_thresholds_are_used_when_not_given(monkeypatch):
    tiles = [tile("2026-10-08", cloud=600, valid=1400)]  # 30% cloud, 2000 px
    (default,) = scene_assess.assess_new_scenes(POLYGON, "2026-10-01", _fetch=stub_fetch(tiles))
    assert default.decision == "passed"

    monkeypatch.setenv(CLOUD_VAR, "0.2")
    (stricter_cloud,) = scene_assess.assess_new_scenes(
        POLYGON, "2026-10-01", _fetch=stub_fetch(tiles)
    )
    assert (stricter_cloud.decision, stricter_cloud.reason) == (
        "rejected_cloud",
        "cloud 30% > 20%",
    )

    monkeypatch.delenv(CLOUD_VAR)
    monkeypatch.setenv(WATER_VAR, "5000")
    (stricter_water,) = scene_assess.assess_new_scenes(
        POLYGON, "2026-10-01", _fetch=stub_fetch(tiles)
    )
    assert (stricter_water.decision, stricter_water.reason) == (
        "rejected_no_water",
        "2000 unmasked water pixels < 5000",
    )


def test_explicit_thresholds_override_env(monkeypatch):
    monkeypatch.setenv(CLOUD_VAR, "0.1")
    monkeypatch.setenv(WATER_VAR, "100000")
    tiles = [tile("2026-10-08", cloud=600, valid=1400)]
    (only,) = scene_assess.assess_new_scenes(
        POLYGON,
        "2026-10-01",
        max_cloud_fraction=0.5,
        min_water_pixels=1000,
        _fetch=stub_fetch(tiles),
    )
    assert only.decision == "passed"


@pytest.mark.parametrize("var, raw", [(CLOUD_VAR, "lots"), (WATER_VAR, "-1")])
def test_invalid_env_raises_named_error_before_any_fetch(monkeypatch, var, raw):
    monkeypatch.setenv(var, raw)
    seen = []
    with pytest.raises(ValueError, match=var):
        scene_assess.assess_new_scenes(POLYGON, "2026-10-01", _fetch=stub_fetch([], seen))
    assert seen == []


def test_invalid_explicit_threshold_raises():
    with pytest.raises(ValueError, match="max_cloud_fraction"):
        scene_assess.assess_new_scenes(
            POLYGON, "2026-10-01", max_cloud_fraction=0.0, _fetch=stub_fetch([])
        )
    with pytest.raises(ValueError, match="min_water_pixels"):
        scene_assess.assess_new_scenes(
            POLYGON, "2026-10-01", min_water_pixels=0, _fetch=stub_fetch([])
        )


@pytest.mark.parametrize("bad", ["2026-10-1", "yesterday", ""])
def test_invalid_since_date_raises_before_fetch(bad):
    seen = []
    with pytest.raises(ValueError, match="since_date"):
        scene_assess.assess_new_scenes(POLYGON, bad, _fetch=stub_fetch([], seen))
    assert seen == []


@pytest.mark.parametrize("bad", [0, -200, 2.5, True])
def test_invalid_scale_raises(bad):
    with pytest.raises(ValueError, match="scale_m"):
        scene_assess.assess_new_scenes(
            POLYGON, "2026-10-01", scale_m=bad, _fetch=stub_fetch([])
        )


def test_fetch_failure_propagates_and_is_never_a_decision():
    class EEException(Exception):
        pass

    def failing_fetch(polygon, since_date, scale_m, *, skip_dates):
        raise EEException("Computation timed out.")

    with pytest.raises(EEException, match="timed out"):
        scene_assess.assess_new_scenes(POLYGON, "2026-10-01", _fetch=failing_fetch)


def test_broken_tile_from_fetch_raises_rather_than_deciding():
    broken = {"date": "2026-10-08", "cloud_count": 5, "valid_count": 5, "water_count": 99}
    with pytest.raises(ValueError):
        scene_assess.assess_new_scenes(POLYGON, "2026-10-01", _fetch=stub_fetch([broken]))


def test_tile_with_bad_date_from_fetch_raises():
    bad = tile("2026/10/08", cloud=0, valid=2000)
    with pytest.raises(ValueError, match="date"):
        scene_assess.assess_new_scenes(POLYGON, "2026-10-01", _fetch=stub_fetch([bad]))


def test_scene_assessment_is_frozen_with_the_documented_fields():
    (only,) = scene_assess.assess_new_scenes(
        POLYGON, "2026-10-01", _fetch=stub_fetch([tile("2026-10-08", cloud=0, valid=2000)])
    )
    assert isinstance(only, scene_assess.SceneAssessment)
    assert [f.name for f in dataclasses.fields(only)] == [
        "acquisition_date",
        "cloud_fraction",
        "water_pixels",
        "decision",
        "reason",
    ]
    with pytest.raises(dataclasses.FrozenInstanceError):
        only.decision = "rejected_cloud"


def test_stub_fetch_never_touches_earth_engine(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("Earth Engine must not be contacted when _fetch is given")

    monkeypatch.setattr(scene_assess, "_fetch_scene_stats", boom)
    monkeypatch.setattr(scene_assess, "initialize_ee", boom)
    assert scene_assess.assess_new_scenes(POLYGON, "2026-10-01", _fetch=stub_fetch([])) == []


def test_default_fetch_is_the_gee_seam(monkeypatch):
    seen = []
    monkeypatch.setattr(
        scene_assess,
        "_fetch_scene_stats",
        stub_fetch([tile("2026-10-08", cloud=0, valid=2000)], seen),
    )
    (only,) = scene_assess.assess_new_scenes(POLYGON, "2026-10-01")
    assert only.decision == "passed"
    assert seen == [(POLYGON, "2026-10-01", 200, frozenset())]


# --------------------------------------------------------------------------
# _scene_count_image -- the per-scene 0/1 stack, against a numpy double and
# the REAL sentinel2._cloud_flag_image
# --------------------------------------------------------------------------


class NpImage:
    """Minimal numpy stand-in for `ee.Image`: band -> float array, NaN =
    masked. Implements only the operations the stack and the real
    `sentinel2._cloud_flag_image` use."""

    def __init__(self, bands):
        self.bands = {name: np.asarray(arr, dtype=float) for name, arr in bands.items()}

    def _only(self):
        assert len(self.bands) == 1
        return next(iter(self.bands.items()))

    def _each(self, fn):
        return NpImage({n: np.where(np.isnan(a), np.nan, fn(a)) for n, a in self.bands.items()})

    def select(self, name):
        return NpImage({name: self.bands[name]})

    def remap(self, from_values, to_values, default_value):
        name, arr = self._only()
        out = np.full(arr.shape, float(default_value))
        for src, dst in zip(from_values, to_values):
            out[arr == src] = dst
        return NpImage({name: np.where(np.isnan(arr), np.nan, out)})

    def rename(self, name):
        _, arr = self._only()
        return NpImage({name: arr})

    def updateMask(self, mask):  # noqa: N802 -- ee API name
        _, m = mask._only()
        drop = np.isnan(m) | (m == 0)
        return NpImage({n: np.where(drop, np.nan, a) for n, a in self.bands.items()})

    def Not(self):  # noqa: N802 -- ee API name
        return self._each(lambda a: (a == 0).astype(float))

    def gte(self, value):
        return self._each(lambda a: (a >= value).astype(float))

    def addBands(self, other):  # noqa: N802 -- ee API name
        merged = dict(self.bands)
        assert not set(merged) & set(other.bands), "duplicate band names"
        merged.update(other.bands)
        return NpImage(merged)

    def unmask(self, value):
        return NpImage({n: np.where(np.isnan(a), value, a) for n, a in self.bands.items()})


NAN = float("nan")


def unweighted_sums(image):
    return {name: int(np.nansum(arr)) for name, arr in image.bands.items()}


def test_stack_counts_cloud_only_over_observed_water():
    # SCL codes: 4 vegetation, 6 water (clear), 8/9 cloud, 0 no-data
    # (counted as unusable, like production), NaN = outside the footprint.
    scl = np.array(
        [
            [6, 6, 9, 4],
            [6, 8, 6, 9],
            [0, 6, NAN, NAN],
        ]
    )
    water = np.array(
        [
            [1, 1, 1, 0],
            [1, 1, 1, 0],
            [1, 1, 1, 1],
        ]
    )
    stack = scene_assess._scene_count_image(
        NpImage({"SCL": scl}),
        NpImage({"water_mask": water}),
        tuple(sentinel2.DEFAULT_CLOUD_CLASSES),
    )
    sums = unweighted_sums(stack)
    # Observed water: every water pixel with an SCL value -> 8 (the two
    # NaN-SCL water pixels are outside the footprint; land is ignored,
    # including the cloudy land pixel at [1, 3]).
    assert sums["water_count"] == 8
    # Cloud-flagged among them: 9 at [0,2], 8 at [1,1], no-data 0 at [2,0].
    assert sums["cloud_count"] == 3
    assert sums["valid_count"] == 5
    assert sums["cloud_count"] + sums["valid_count"] == sums["water_count"]
    assert set(stack.bands) == set(scene_assess.COUNT_KEYS)


def test_stack_has_no_observed_water_over_land_only_scene():
    scl = np.array([[9, 4], [6, 6]])
    water = np.zeros((2, 2))
    sums = unweighted_sums(
        scene_assess._scene_count_image(
            NpImage({"SCL": scl}),
            NpImage({"water_mask": water}),
            tuple(sentinel2.DEFAULT_CLOUD_CLASSES),
        )
    )
    assert sums == {"cloud_count": 0, "valid_count": 0, "water_count": 0}


def test_stack_uses_the_given_cloud_classes():
    scl = np.array([[3, 6]])  # 3 = cloud shadow
    water = np.ones((1, 2))
    with_shadow = unweighted_sums(
        scene_assess._scene_count_image(
            NpImage({"SCL": scl}), NpImage({"water_mask": water}), (3, 8, 9)
        )
    )
    without_shadow = unweighted_sums(
        scene_assess._scene_count_image(
            NpImage({"SCL": scl}), NpImage({"water_mask": water}), (8, 9)
        )
    )
    assert with_shadow["cloud_count"] == 1
    assert without_shadow["cloud_count"] == 0


# --------------------------------------------------------------------------
# _fetch_scene_stats -- structural check of the one Earth Engine request
# --------------------------------------------------------------------------


@pytest.fixture
def recording_ee(monkeypatch):
    fake_ee = MagicMock(name="ee")
    monkeypatch.setattr(scene_assess, "ee", fake_ee)
    monkeypatch.setattr(scene_assess, "initialize_ee", lambda: None)
    water = MagicMock(name="water_mask")
    water_calls = []

    def fake_water_mask(pct):
        water_calls.append(pct)
        return water

    monkeypatch.setattr(sentinel2, "_water_mask_image", fake_water_mask)
    stack = MagicMock(name="stack")
    stack_calls = []

    def fake_stack(image, water_mask, cloud_classes):
        stack_calls.append((image, water_mask, cloud_classes))
        return stack

    monkeypatch.setattr(scene_assess, "_scene_count_image", fake_stack)
    fake_ee.FeatureCollection.return_value.getInfo.return_value = {
        "features": [
            feature(
                date="2026-10-08",
                cloud_count=1,
                valid_count=2,
                water_count=3,
                scene_id="x",
            )
        ]
    }
    return {
        "ee": fake_ee,
        "water": water,
        "water_calls": water_calls,
        "stack": stack,
        "stack_calls": stack_calls,
    }


def _per_scene_function(fake_ee, skipped):
    dated = (
        fake_ee.ImageCollection.return_value.filterBounds.return_value.filterDate.return_value.map.return_value
    )
    kept = dated.filter.return_value if skipped else dated
    return kept.map.call_args.args[0]


def test_default_fetch_asks_for_unweighted_sums_over_the_polygon(recording_ee):
    fake_ee = recording_ee["ee"]
    tiles = scene_assess._fetch_scene_stats(POLYGON, "2026-10-01", 200, skip_dates=frozenset())

    fake_ee.Geometry.Polygon.assert_called_once_with([[[lng, lat] for lat, lng in POLYGON]])
    region = fake_ee.Geometry.Polygon.return_value
    fake_ee.ImageCollection.assert_called_once_with("COPERNICUS/S2_SR_HARMONIZED")
    collection = fake_ee.ImageCollection.return_value
    collection.filterBounds.assert_called_once_with(region)
    start, end = collection.filterBounds.return_value.filterDate.call_args.args
    assert start == "2026-10-01"
    assert end > start  # exclusive end bound after today, as in scene_poll.py
    fake_ee.Filter.inList.assert_not_called()

    scene_fn = _per_scene_function(fake_ee, skipped=False)
    scene_fn(MagicMock(name="image"))

    assert recording_ee["water_calls"] == [sentinel2.DEFAULT_MIN_WATER_OCCURRENCE_PCT]
    (_, water_mask, classes), = recording_ee["stack_calls"]
    assert water_mask is recording_ee["water"]
    assert classes == tuple(sentinel2.DEFAULT_CLOUD_CLASSES)

    kwargs = recording_ee["stack"].reduceRegion.call_args.kwargs
    assert kwargs["reducer"] is fake_ee.Reducer.sum.return_value.unweighted.return_value
    assert kwargs["geometry"] is region
    assert kwargs["scale"] == 200
    assert kwargs["bestEffort"] is False
    assert kwargs["maxPixels"] >= 1e10

    fake_ee.FeatureCollection.return_value.getInfo.assert_called_once_with()
    assert tiles == [
        {"date": "2026-10-08", "cloud_count": 1, "valid_count": 2, "water_count": 3, "scene_id": "x"}
    ]


def test_default_fetch_excludes_skipped_dates_server_side(recording_ee):
    fake_ee = recording_ee["ee"]
    scene_assess._fetch_scene_stats(
        POLYGON, "2026-10-01", 100, skip_dates=frozenset({"2026-10-08", "2026-10-03"})
    )
    fake_ee.Filter.inList.assert_called_once_with("date", ["2026-10-03", "2026-10-08"])
    dated = (
        fake_ee.ImageCollection.return_value.filterBounds.return_value.filterDate.return_value.map.return_value
    )
    dated.filter.assert_called_once_with(fake_ee.Filter.inList.return_value.Not.return_value)

    _per_scene_function(fake_ee, skipped=True)(MagicMock(name="image"))
    assert recording_ee["stack"].reduceRegion.call_args.kwargs["scale"] == 100


def test_default_fetch_dates_scenes_in_utc(recording_ee):
    fake_ee = recording_ee["ee"]
    scene_assess._fetch_scene_stats(POLYGON, "2026-10-01", 200, skip_dates=frozenset())
    date_fn = (
        fake_ee.ImageCollection.return_value.filterBounds.return_value.filterDate.return_value.map.call_args.args[0]
    )
    date_fn(MagicMock(name="image"))
    fake_ee.Image.return_value.date.return_value.format.assert_called_once_with(
        "YYYY-MM-dd", "UTC"
    )


def test_cloud_fraction_reason_formatting_is_percent_without_decimals():
    """Pinned because the dashboard text echoes it."""
    _, reason = decide(0.123, 5000, max_cloud_fraction=0.1)
    assert reason == "cloud 12% > 10%"
