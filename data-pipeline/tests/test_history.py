"""
Offline tests for `src/history.py` -- the per-site NDCI history extraction
that feeds the TEST baseline. No Earth Engine session is required or
contacted.

What is exercised and what is not:

  - `rows_from_stats` and `preprocessing_params` are pure and executed in
    production. They parse the plain feature dicts that
    `FeatureCollection.getInfo()["features"]` returns (numbers, strings and
    None -- no `ee` objects), the same typed boundary
    `test_sentinel2_masking.py` relies on.
  - `get_ndci_history` is tested through its `_fetch` seam with a stub, so
    the only thing replaced is the network call. `_fetch_features` -- the
    only function in `history.py` that touches `ee` -- is deliberately NOT
    run here: an `ee.Image` expression cannot be evaluated offline, and no
    test in this file claims otherwise.
"""

import math

import pytest

from src import history, sentinel2
from src.sentinel2 import BANDS

# 2026-09-04T03:30:00Z in milliseconds since the epoch.
T_20260904 = 1788492600000


def props(
    *,
    t=T_20260904,
    scene_id="20260904T033000_X",
    cloud_mean=0.0,
    cloud_count=28,
    b4=400.0,
    b5=500.0,
    band_count=28,
):
    """A synthetic feature `properties` dict shaped like the one
    `sentinel2._candidate_stats` / `history._fetch_features` produce."""
    out = {
        "cloud_flag_mean": cloud_mean,
        "cloud_flag_count": cloud_count,
        "t": t,
        "scene_id": scene_id,
    }
    for band in BANDS:
        out[f"{band}_mean"] = 450.0
        out[f"{band}_count"] = band_count
    out["B4_mean"] = b4
    out["B5_mean"] = b5
    return out


def feature(**kwargs):
    return {"type": "Feature", "geometry": None, "properties": props(**kwargs)}


# --------------------------------------------------------------------------
# rows_from_stats
# --------------------------------------------------------------------------


def test_clear_scene_yields_row_with_exact_ndci():
    rows = history.rows_from_stats([feature(b4=400.0, b5=500.0, cloud_mean=0.1)])
    assert rows == [
        {
            "acquisition_date": "2026-09-04",
            "ndci": (500.0 - 400.0) / (500.0 + 400.0),
            "cloud_fraction": pytest.approx(0.1),
            "scene_id": "20260904T033000_X",
        }
    ]
    assert rows[0]["ndci"] == (500.0 - 400.0) / (500.0 + 400.0)


def test_ndci_is_negative_when_b4_exceeds_b5():
    rows = history.rows_from_stats([feature(b4=600.0, b5=300.0)])
    assert rows[0]["ndci"] == (300.0 - 600.0) / (300.0 + 600.0)
    assert rows[0]["ndci"] < 0


def test_cloudy_scene_is_skipped():
    assert history.rows_from_stats([feature(cloud_mean=0.6)]) == []


def test_cloud_fraction_at_threshold_is_kept():
    """Same comparison `_resolve_sentinel2_scene` uses: reject only when
    strictly greater than the threshold."""
    rows = history.rows_from_stats([feature(cloud_mean=0.5)])
    assert len(rows) == 1


def test_explicit_max_cloud_fraction_overrides_default():
    cloudy = feature(cloud_mean=0.3)
    assert history.rows_from_stats([cloudy], max_cloud_fraction=0.2) == []
    assert len(history.rows_from_stats([cloudy], max_cloud_fraction=0.4)) == 1


def test_default_threshold_is_read_live_not_frozen_at_import(monkeypatch):
    """`preprocessing_params()` reports the live constant, so the filter
    must use the live constant too -- otherwise the signature would name a
    threshold the rows were not actually filtered with."""
    scene = feature(cloud_mean=0.3)
    assert len(history.rows_from_stats([scene])) == 1  # 0.3 <= default 0.5
    monkeypatch.setattr(sentinel2, "DEFAULT_MAX_CLOUD_FRACTION", 0.2)
    assert history.rows_from_stats([scene]) == []


def test_zero_water_pixels_scene_is_skipped():
    scene = feature(band_count=0)
    for band in BANDS:
        scene["properties"][f"{band}_mean"] = None
    assert history.rows_from_stats([scene]) == []


def test_single_empty_band_scene_is_skipped():
    """Same all-bands-or-nothing rule as `band_means_from_stats`: the row
    set is exactly the scenes `get_sentinel2_bands` would have accepted."""
    scene = feature()
    scene["properties"]["B6_mean"] = None
    scene["properties"]["B6_count"] = 0
    assert history.rows_from_stats([scene]) == []


def test_zero_denominator_is_skipped():
    assert history.rows_from_stats([feature(b4=0.0, b5=0.0)]) == []


def test_nonfinite_ndci_is_never_emitted():
    rows = history.rows_from_stats(
        [feature(b4=float("nan"), b5=500.0), feature(b4=float("inf"), b5=500.0)]
    )
    assert rows == []


def test_utc_date_from_epoch_milliseconds():
    assert history.rows_from_stats([feature(t=T_20260904)])[0][
        "acquisition_date"
    ] == "2026-09-04"


def test_date_is_utc_not_local_at_day_boundaries():
    # 23:59:59.000Z on the 4th and 00:00:00.000Z on the 5th.
    rows = history.rows_from_stats(
        [feature(t=1788566399000, scene_id="a"), feature(t=1788566400000, scene_id="b")]
    )
    assert [r["acquisition_date"] for r in rows] == ["2026-09-04", "2026-09-05"]


def test_feature_without_timestamp_is_skipped_never_dated():
    """A row with no acquisition time cannot be placed in a season; it is
    dropped, not given a made-up date."""
    assert history.rows_from_stats([feature(t=None)]) == []
    no_t = feature()
    del no_t["properties"]["t"]
    assert history.rows_from_stats([no_t]) == []


def test_missing_scene_id_is_none():
    scene = feature()
    del scene["properties"]["scene_id"]
    assert history.rows_from_stats([scene])[0]["scene_id"] is None


def test_output_is_sorted_by_date():
    day = 86_400_000
    features = [
        feature(t=T_20260904 + 2 * day, scene_id="c"),
        feature(t=T_20260904, scene_id="a"),
        feature(t=T_20260904 + day, scene_id="b"),
    ]
    rows = history.rows_from_stats(features)
    assert [r["acquisition_date"] for r in rows] == [
        "2026-09-04",
        "2026-09-05",
        "2026-09-06",
    ]
    assert [r["scene_id"] for r in rows] == ["a", "b", "c"]


def test_several_tiles_on_one_date_are_all_kept():
    """Reduction to one value per day is `assess_signal_anomaly`'s job, not
    this module's."""
    rows = history.rows_from_stats(
        [
            feature(t=T_20260904, scene_id="tile1", b5=500.0),
            feature(t=T_20260904 + 60_000, scene_id="tile2", b5=520.0),
        ]
    )
    assert len(rows) == 2
    assert {r["acquisition_date"] for r in rows} == {"2026-09-04"}
    assert [r["scene_id"] for r in rows] == ["tile1", "tile2"]


def test_empty_input_is_empty_output():
    assert history.rows_from_stats([]) == []


def test_rows_carry_only_the_documented_keys():
    row = history.rows_from_stats([feature()])[0]
    assert set(row) == {"acquisition_date", "ndci", "cloud_fraction", "scene_id"}
    assert math.isfinite(row["ndci"])


# --------------------------------------------------------------------------
# get_ndci_history -- the GEE seam
# --------------------------------------------------------------------------


def test_get_ndci_history_returns_rows_from_the_fetched_features():
    features = [feature(), feature(cloud_mean=0.9, scene_id="cloudy")]
    seen = []

    def fake_fetch(lat, lng, start, end):
        seen.append((lat, lng, start, end))
        return features

    rows = history.get_ndci_history(
        13.1, 100.9, "2017-03-28", "2026-10-10", _fetch=fake_fetch
    )
    assert rows == history.rows_from_stats(features)
    assert len(rows) == 1
    assert seen == [(13.1, 100.9, "2017-03-28", "2026-10-10")]


def test_get_ndci_history_applies_max_cloud_fraction():
    features = [feature(cloud_mean=0.3)]
    stub = lambda *args: features  # noqa: E731
    assert history.get_ndci_history(1, 2, "a", "b", _fetch=stub) != []
    assert (
        history.get_ndci_history(1, 2, "a", "b", max_cloud_fraction=0.2, _fetch=stub)
        == []
    )


def test_get_ndci_history_with_stub_never_touches_earth_engine(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("Earth Engine must not be contacted when _fetch is given")

    monkeypatch.setattr(history, "_fetch_features", boom)
    monkeypatch.setattr(history, "initialize_ee", boom, raising=False)
    assert history.get_ndci_history(1, 2, "a", "b", _fetch=lambda *a: []) == []


def test_get_ndci_history_defaults_to_the_gee_fetch(monkeypatch):
    calls = []

    def fake_fetch_features(lat, lng, start, end):
        calls.append((lat, lng, start, end))
        return [feature()]

    monkeypatch.setattr(history, "_fetch_features", fake_fetch_features)
    rows = history.get_ndci_history(13.1, 100.9, "2020-01-01", "2020-02-01")
    assert calls == [(13.1, 100.9, "2020-01-01", "2020-02-01")]
    assert len(rows) == 1


# --------------------------------------------------------------------------
# preprocessing_params
# --------------------------------------------------------------------------


def test_preprocessing_params_reflects_live_constants():
    params = history.preprocessing_params()
    assert params == {
        "collection": "COPERNICUS/S2_SR_HARMONIZED",
        "bands": list(sentinel2.BANDS),
        "cloud_classes": list(sentinel2.DEFAULT_CLOUD_CLASSES),
        "max_cloud_fraction": sentinel2.DEFAULT_MAX_CLOUD_FRACTION,
        "min_water_occurrence_pct": sentinel2.DEFAULT_MIN_WATER_OCCURRENCE_PCT,
        "buffer_m": sentinel2.DEFAULT_BUFFER_M,
        "scale_m": sentinel2.DEFAULT_SCALE_M,
        "sampling": "point-buffer-mean",
        "index": "ndci=(B5-B4)/(B5+B4)",
    }


def test_preprocessing_params_is_json_serialisable_plain_types():
    """Lists, not tuples: the baseline signature hashes canonical JSON and
    the manifest stores a copy, so the dict must round-trip unchanged."""
    import json

    params = history.preprocessing_params()
    assert json.loads(json.dumps(params)) == params
    assert isinstance(params["bands"], list)
    assert isinstance(params["cloud_classes"], list)


def test_preprocessing_params_returns_a_fresh_dict_each_call():
    first = history.preprocessing_params()
    first["bands"].append("B99")
    first["buffer_m"] = -1
    assert history.preprocessing_params()["bands"] == list(sentinel2.BANDS)
    assert history.preprocessing_params()["buffer_m"] == sentinel2.DEFAULT_BUFFER_M


@pytest.mark.parametrize(
    "constant, new_value",
    [
        ("DEFAULT_BUFFER_M", 90),
        ("DEFAULT_SCALE_M", 20),
        ("DEFAULT_MAX_CLOUD_FRACTION", 0.25),
        ("DEFAULT_MIN_WATER_OCCURRENCE_PCT", 75.0),
        ("DEFAULT_CLOUD_CLASSES", (3, 8, 9)),
        ("BANDS", ("B2", "B3", "B4", "B5")),
    ],
)
def test_preprocessing_params_change_when_a_constant_changes(
    monkeypatch, constant, new_value
):
    """Signature sensitivity: a different preprocessing setting must yield a
    different params dict (hence a different baseline signature), so history
    built under old settings is never silently mixed with new."""
    before = history.preprocessing_params()
    monkeypatch.setattr(sentinel2, constant, new_value)
    after = history.preprocessing_params()
    assert after != before
