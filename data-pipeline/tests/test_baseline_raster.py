"""
Offline tests for `src/baseline_raster.py` -- the Level B (per-cell) TEST
baseline over the study polygon. No Earth Engine session is required or
contacted.

What is exercised and what is not:

  - `cell_baseline_params`, `polygon_id` and `cells_from_grid` are pure and
    executed in production; they are tested directly.
  - `build_cell_baseline` is tested through its `_fetch` seam with a stub
    that returns a structured NPY-shaped grid, so only the network call is
    replaced. `_fetch_cell_stats` -- the only function in the module that
    touches `ee` -- is deliberately NOT run here: an `ee.Image` expression
    cannot be evaluated offline. Its logic was verified live by the Task 11
    spike (27 s per season window), not by this suite.
"""

import json

import numpy as np
import pytest

import src
from src import baseline_raster, history, raster, sentinel2
from src.study_area import STUDY_AREA_POLYGON_LATLNG

GRID_DTYPE = [
    ("median", "<f4"),
    ("mad", "<f4"),
    ("n", "<i4"),
    ("longitude", "<f8"),
    ("latitude", "<f8"),
]

DEG = 200 / 111319.49079327357


def grid(rows):
    """A structured grid from (median, mad, n, lng, lat) tuples, shape (1, N)."""
    return np.array([rows], dtype=GRID_DTYPE)


class FakeFetch:
    """Returns ``result_grid`` and, unless given, three dates per season month, 2018-2025."""

    def __init__(self, result_grid, dates=None):
        self.result_grid = result_grid
        self.dates = dates
        self.calls = []

    def __call__(self, polygon, months, start, end, scale_m):
        self.calls.append((polygon, months, start, end, scale_m))
        dates = self.dates if self.dates is not None else [
            f"{y}-{m:02d}-{d:02d}" for y in range(2018, 2026) for m in months for d in (5, 15, 25)
        ]
        return self.result_grid, list(dates)


# --------------------------------------------------------------------------
# cell_baseline_params
# --------------------------------------------------------------------------


def test_params_carry_the_documented_keys_from_live_constants():
    params = baseline_raster.cell_baseline_params()
    for key in (
        "collection", "bands", "cloud_classes", "min_water_occurrence_pct", "scale_m",
        "sampling", "index", "per_day_reduction", "statistic", "polygon_id",
    ):
        assert key in params, key
    assert params["collection"] == history.S2_COLLECTION
    assert params["bands"] == list(sentinel2.BANDS)
    assert params["cloud_classes"] == list(sentinel2.DEFAULT_CLOUD_CLASSES)
    assert params["min_water_occurrence_pct"] == sentinel2.DEFAULT_MIN_WATER_OCCURRENCE_PCT
    assert params["scale_m"] == raster.DEFAULT_RASTER_SCALE_M == 200
    assert params["sampling"] == "raster-nearest-native-pixel-per-day-mosaic"
    assert params["index"] == history.NDCI_DEFINITION
    assert params["polygon_id"] == baseline_raster.polygon_id(STUDY_AREA_POLYGON_LATLNG)


def test_params_are_plain_json_and_fresh_each_call():
    a = baseline_raster.cell_baseline_params()
    json.dumps(a, allow_nan=False)  # plain JSON types only
    a["bands"].append("B99")
    assert "B99" not in baseline_raster.cell_baseline_params()["bands"]


def test_params_differ_from_the_site_history_params():
    """Site rows are point-buffer means; cells are single sampled pixels."""
    cell = baseline_raster.cell_baseline_params()
    site = history.preprocessing_params()
    assert cell != site
    assert cell["sampling"] != site["sampling"]


def test_params_change_with_scale_masking_and_polygon(monkeypatch):
    base = baseline_raster.cell_baseline_params()
    assert baseline_raster.cell_baseline_params(scale_m=100) != base
    assert baseline_raster.cell_baseline_params(scale_m=100)["scale_m"] == 100

    other_polygon = ((13.0, 100.0), (13.1, 100.5), (12.9, 100.4))
    assert baseline_raster.cell_baseline_params(polygon_latlng=other_polygon)["polygon_id"] != base["polygon_id"]

    monkeypatch.setattr(sentinel2, "DEFAULT_CLOUD_CLASSES", (0, 3, 8, 9))
    assert baseline_raster.cell_baseline_params()["cloud_classes"] == [0, 3, 8, 9]
    monkeypatch.undo()

    monkeypatch.setattr(sentinel2, "DEFAULT_MIN_WATER_OCCURRENCE_PCT", 60.0)
    assert baseline_raster.cell_baseline_params()["min_water_occurrence_pct"] == 60.0


def test_polygon_id_is_stable_and_order_sensitive():
    poly = STUDY_AREA_POLYGON_LATLNG
    assert baseline_raster.polygon_id(poly) == baseline_raster.polygon_id(tuple(poly))
    assert baseline_raster.polygon_id(poly) == baseline_raster.polygon_id([list(v) for v in poly])
    assert baseline_raster.polygon_id(poly) != baseline_raster.polygon_id(poly[::-1])
    assert len(baseline_raster.polygon_id(poly)) == 16


# --------------------------------------------------------------------------
# build_cell_baseline via the _fetch seam
# --------------------------------------------------------------------------


def test_build_returns_flat_arrays_with_storage_dtypes():
    fetch = FakeFetch(grid([
        (0.04, 0.02, 31, 100.0 + 0.5 * DEG, 13.0 + 0.5 * DEG),
        (0.05, 0.03, 3, 100.0 + 1.5 * DEG, 13.0 + 0.5 * DEG),
    ]))
    out = baseline_raster.build_cell_baseline(
        STUDY_AREA_POLYGON_LATLNG, (9, 10, 11), "2017-03-28", "2026-09-24", _fetch=fetch,
    )
    assert out["lat"].dtype == np.float64 and out["lng"].dtype == np.float64
    assert out["median"].dtype == np.float32 and out["mad"].dtype == np.float32
    assert out["n"].dtype == np.uint16
    assert all(out[k].ndim == 1 and out[k].size == 2 for k in ("lat", "lng", "median", "mad", "n"))
    assert out["n"].tolist() == [31, 3]
    assert out["lng"].tolist() == [100.0 + 0.5 * DEG, 100.0 + 1.5 * DEG]
    assert out["median"][0] == np.float32(0.04)
    assert out["scale_m"] == 200
    assert out["months"] == [9, 10, 11]
    assert out["start"] == "2017-03-28" and out["end"] == "2026-09-24"
    assert out["n_dates"] == 72
    assert out["first_date"] == "2018-09-05" and out["last_date"] == "2025-11-25"


def test_build_passes_its_arguments_to_the_fetch():
    fetch = FakeFetch(grid([(0.04, 0.02, 31, 100.0, 13.0)]))
    baseline_raster.build_cell_baseline(
        [list(v) for v in STUDY_AREA_POLYGON_LATLNG], [12, 1, 2], "2017-03-28", "2026-09-24", 100,
        _fetch=fetch,
    )
    [(polygon, months, start, end, scale_m)] = fetch.calls
    assert polygon == STUDY_AREA_POLYGON_LATLNG
    assert months == (12, 1, 2)
    assert (start, end, scale_m) == ("2017-03-28", "2026-09-24", 100)


def test_cells_without_observations_or_with_non_finite_stats_are_dropped():
    fetch = FakeFetch(grid([
        (0.0, 0.0, 0, 100.0, 13.0),             # masked: NPY writes 0 in every band
        (np.nan, 0.01, 12, 100.1, 13.0),        # NaN median
        (0.03, np.nan, 12, 100.2, 13.0),        # NaN mad
        (0.0, 0.02, 30, 100.3, 13.0),           # a real reading of exactly 0.0 -- kept
        (0.02, 0.01, 1, 100.4, 13.0),           # n = 1 -- kept
        (0.02, -0.01, 30, 100.5, 13.0),         # negative MAD cannot be a MAD -- dropped
    ]))
    out = baseline_raster.build_cell_baseline(
        STUDY_AREA_POLYGON_LATLNG, (1, 2, 3), "2017-03-28", "2026-09-24", _fetch=fetch,
    )
    assert out["lng"].tolist() == [100.3, 100.4]
    assert out["median"].tolist() == [0.0, np.float32(0.02)]
    assert out["n"].tolist() == [30, 1]


def test_a_two_dimensional_grid_is_flattened_in_row_major_order():
    g = np.zeros((2, 2), dtype=GRID_DTYPE)
    for i in range(2):
        for j in range(2):
            g[i, j] = (0.01 * (2 * i + j), 0.01, 30, 100.0 + j, 13.0 - i)
    out = baseline_raster.cells_from_grid(g)
    assert out["lat"].tolist() == [13.0, 13.0, 12.0, 12.0]
    assert out["lng"].tolist() == [100.0, 101.0, 100.0, 101.0]


def test_empty_window_returns_zero_cells():
    empty = np.zeros(0, dtype=GRID_DTYPE)
    out = baseline_raster.build_cell_baseline(
        STUDY_AREA_POLYGON_LATLNG, (6, 7, 8), "2017-03-28", "2026-09-24",
        _fetch=FakeFetch(empty, dates=[]),
    )
    assert out["n"].size == 0 and out["n"].dtype == np.uint16
    assert out["n_dates"] == 0 and out["first_date"] is None and out["last_date"] is None


@pytest.mark.parametrize(
    "months",
    [(1, 2), (0, 1, 2), (11, 12, 13), (1, 1, 2), ("1", 2, 3), (1.0, 2, 3), (True, 2, 3)],
)
def test_bad_season_months_are_refused(months):
    with pytest.raises(ValueError):
        baseline_raster.build_cell_baseline(
            STUDY_AREA_POLYGON_LATLNG, months, "2017-03-28", "2026-09-24",
            _fetch=FakeFetch(grid([(0.0, 0.0, 0, 0.0, 0.0)])),
        )


@pytest.mark.parametrize("start,end", [("2026-01-01", "2026-01-01"), ("2026-02-01", "2026-01-01"), ("x", "2026-01-01")])
def test_bad_window_is_refused(start, end):
    with pytest.raises(ValueError):
        baseline_raster.build_cell_baseline(
            STUDY_AREA_POLYGON_LATLNG, (1, 2, 3), start, end,
            _fetch=FakeFetch(grid([(0.0, 0.0, 0, 0.0, 0.0)])),
        )


def test_a_reported_date_outside_the_window_is_refused():
    """end is exclusive: a date on or after it would leak the future into the baseline."""
    fetch = FakeFetch(grid([(0.04, 0.02, 1, 100.0, 13.0)]), dates=["2026-09-24"])
    with pytest.raises(ValueError, match="window"):
        baseline_raster.build_cell_baseline(
            STUDY_AREA_POLYGON_LATLNG, (8, 9, 10), "2017-03-28", "2026-09-24", _fetch=fetch,
        )


def test_a_reported_date_outside_the_season_months_is_refused():
    fetch = FakeFetch(grid([(0.04, 0.02, 1, 100.0, 13.0)]), dates=["2020-05-01"])
    with pytest.raises(ValueError, match="month"):
        baseline_raster.build_cell_baseline(
            STUDY_AREA_POLYGON_LATLNG, (8, 9, 10), "2017-03-28", "2026-09-24", _fetch=fetch,
        )


def test_a_cell_count_above_the_number_of_dates_is_refused():
    fetch = FakeFetch(grid([(0.04, 0.02, 4, 100.0, 13.0)]), dates=["2019-01-05", "2019-02-05", "2019-12-05"])
    with pytest.raises(ValueError, match="dates"):
        baseline_raster.build_cell_baseline(
            STUDY_AREA_POLYGON_LATLNG, (1, 2, 12), "2017-03-28", "2026-09-24", _fetch=fetch,
        )


def test_non_integral_or_huge_counts_are_refused():
    float_grid = np.array(
        [[(0.04, 0.02, 2.5, 100.0, 13.0)]],
        dtype=[("median", "<f4"), ("mad", "<f4"), ("n", "<f4"), ("longitude", "<f8"), ("latitude", "<f8")],
    )
    with pytest.raises(ValueError):
        baseline_raster.cells_from_grid(float_grid)
    with pytest.raises(ValueError):
        baseline_raster.cells_from_grid(grid([(0.04, 0.02, 70000, 100.0, 13.0)]))


def test_a_grid_missing_a_field_is_refused():
    bad = np.zeros(2, dtype=[("median", "<f4"), ("mad", "<f4"), ("n", "<i4"), ("longitude", "<f8")])
    with pytest.raises(ValueError, match="latitude"):
        baseline_raster.cells_from_grid(bad)


def test_default_fetch_is_the_earth_engine_function():
    assert baseline_raster.build_cell_baseline.__kwdefaults__["_fetch"] is None
    assert callable(baseline_raster._fetch_cell_stats)


def test_package_re_exports_the_public_names():
    assert src.build_cell_baseline is baseline_raster.build_cell_baseline
    assert src.cell_baseline_params is baseline_raster.cell_baseline_params
    assert "build_cell_baseline" in src.__all__ and "cell_baseline_params" in src.__all__
