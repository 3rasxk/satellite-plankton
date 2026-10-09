"""Pure-logic tests for the Level B (per-cell) helpers in detection/src/baseline.py.

No GEE, no files. Covers: the cell key (grid identity shared by the baseline
and the production raster), the scalar and vectorised cell assessments (the
robust z of ``signal_anomaly`` with its unchanged floors and boundaries), the
per-season summary, and the ``level_b`` manifest block and its validation.
"""

from datetime import date
import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import baseline as b  # noqa: E402
import signal_anomaly as sa  # noqa: E402

DEG = 200 / 111319.49079327357

# Real pixelLonLat values Earth Engine returned for the production raster
# (backend/data/rasters/5/cells.npz, read at scale 200 on 2026-10-09).
REAL_PRODUCTION_CELLS = [
    (13.61396813083135, 100.22773119506738),
    (13.61396813083135, 100.33193576802525),
    (12.50544707022786, 99.91332084562555),
    (12.50544707022786, 101.02543516736552),
]


# --------------------------------------------------------------------------
# cell_key
# --------------------------------------------------------------------------


def test_cell_size_is_the_earth_engine_metre_to_degree_conversion():
    assert b.cell_size_deg(200) == DEG
    assert b.cell_size_deg(100) == 100 / 111319.49079327357
    with pytest.raises(ValueError):
        b.cell_size_deg(0)


def test_cell_key_of_a_cell_centre_is_its_integer_grid_index():
    for row, col in ((6960, 55600), (7577, 55800), (0, 0), (-3, -7)):
        lat = (row + 0.5) * DEG
        lng = (col + 0.5) * DEG
        assert b.cell_key(lat, lng, 200) == (row, col)


def test_cell_key_is_stable_under_float_noise_on_both_sides():
    rng = np.random.default_rng(7)
    rows = rng.integers(6950, 7600, 2000)
    cols = rng.integers(55550, 56200, 2000)
    lat = (rows + 0.5) * DEG
    lng = (cols + 0.5) * DEG
    for _ in range(3):
        noisy_a = (lat + rng.uniform(-1e-7, 1e-7, lat.size), lng + rng.uniform(-1e-7, 1e-7, lng.size))
        noisy_b = (lat + rng.uniform(-1e-7, 1e-7, lat.size), lng + rng.uniform(-1e-7, 1e-7, lng.size))
        keys_a = [b.cell_key(y, x, 200) for y, x in zip(*noisy_a)]
        keys_b = [b.cell_key(y, x, 200) for y, x in zip(*noisy_b)]
        assert keys_a == keys_b == list(zip(rows.tolist(), cols.tolist()))


def test_neighbouring_cells_have_distinct_keys():
    lat0, lng0 = (7000 + 0.5) * DEG, (55800 + 0.5) * DEG
    centre = b.cell_key(lat0, lng0, 200)
    neighbours = {
        b.cell_key(lat0 + dy * DEG + 1e-7, lng0 + dx * DEG - 1e-7, 200)
        for dy in (-1, 0, 1) for dx in (-1, 0, 1)
    }
    assert len(neighbours) == 9
    assert centre in neighbours


def test_half_cell_tolerance():
    lat0, lng0 = (7000 + 0.5) * DEG, (55800 + 0.5) * DEG
    assert b.cell_key(lat0 + 0.49 * DEG, lng0 - 0.49 * DEG, 200) == (7000, 55800)
    assert b.cell_key(lat0 + 0.51 * DEG, lng0, 200) == (7001, 55800)
    assert b.cell_key(lat0, lng0 - 0.51 * DEG, 200) == (7000, 55799)


def test_real_production_coordinates_sit_on_cell_centres():
    """The stored raster's pixelLonLat values are exactly on the key grid's centres."""
    lat = np.array([c[0] for c in REAL_PRODUCTION_CELLS])
    lng = np.array([c[1] for c in REAL_PRODUCTION_CELLS])
    assert b.grid_offset_cells(lat, lng, 200) < 1e-6
    keys = [b.cell_key(y, x, 200) for y, x in REAL_PRODUCTION_CELLS]
    assert len(set(keys)) == len(keys)
    # Same row for the first two, as their latitudes are identical.
    assert keys[0][0] == keys[1][0]


def test_a_grid_anchored_half_a_cell_away_is_detected():
    lat = (np.arange(7000, 7010) + 0.5) * DEG
    lng = (np.arange(55800, 55810) + 0.5) * DEG
    assert b.grid_offset_cells(lat, lng, 200) < 1e-9
    assert b.grid_offset_cells(lat + 0.5 * DEG, lng, 200) == pytest.approx(0.5, abs=1e-6)
    assert b.grid_offset_cells(lat, lng + 0.2 * DEG, 200) == pytest.approx(0.2, abs=1e-6)
    assert b.grid_offset_cells(np.array([]), np.array([]), 200) == 0.0


def test_vectorised_cell_keys_equal_the_scalar_key():
    rng = np.random.default_rng(3)
    lat = rng.uniform(12.4, 13.7, 3000)
    lng = rng.uniform(99.8, 101.1, 3000)
    rows, cols = b.cell_keys(lat, lng, 200)
    assert rows.dtype == np.int64 and cols.dtype == np.int64
    assert list(zip(rows.tolist(), cols.tolist())) == [b.cell_key(y, x, 200) for y, x in zip(lat, lng)]


def test_the_key_depends_on_the_scale():
    lat, lng = (7000 + 0.5) * DEG, (55800 + 0.5) * DEG
    assert b.cell_key(lat, lng, 200) != b.cell_key(lat, lng, 100)


def test_cell_key_refuses_non_finite_coordinates():
    with pytest.raises(ValueError):
        b.cell_key(float("nan"), 100.0, 200)
    with pytest.raises(ValueError):
        b.cell_keys(np.array([13.0, np.inf]), np.array([100.0, 100.0]), 200)


# --------------------------------------------------------------------------
# assess_cell / assess_cells
# --------------------------------------------------------------------------


def _exact_z_case(z: float) -> tuple[float, float, float, float]:
    """``(ndci_at, ndci_below, median, mad)``: robust z, computed exactly as
    signal_anomaly does, is ``z`` at ``ndci_at`` and strictly below ``z`` at
    ``ndci_below`` (the next float down that leaves the boundary)."""
    for median in (0.0, 0.04, -0.03):
        for mad in (0.02, 0.0125, 0.03, 0.017):
            scale = sa.MAD_SCALE * mad
            ndci = median + z * scale
            for _ in range(60):
                ndci = math.nextafter(ndci, -math.inf)
            for _ in range(120):
                if (ndci - median) / scale == z:
                    below = ndci
                    while (below - median) / scale >= z:
                        below = math.nextafter(below, -math.inf)
                    return ndci, below, median, mad
                ndci = math.nextafter(ndci, math.inf)
    raise AssertionError(f"no float gives z == {z} exactly")


def test_assess_cell_is_the_signal_anomaly_formula():
    out = b.assess_cell(0.15, 0.04, 0.02, 45)
    z = (0.15 - 0.04) / (1.4826 * 0.02)
    assert z > 3
    assert out == {"level": "high", "robust_z": z, "reason": None}
    watch = b.assess_cell(0.10, 0.04, 0.02, 45)
    assert watch == {"level": "watch", "robust_z": (0.10 - 0.04) / (1.4826 * 0.02), "reason": None}
    assert b.assess_cell(0.04, 0.04, 0.02, 45) == {"level": "normal", "robust_z": 0.0, "reason": None}


def test_z_boundaries_are_inclusive_like_classify_robust_z():
    at_two, below_two, median, mad = _exact_z_case(2.0)
    assert b.assess_cell(at_two, median, mad, 30) == {"level": "watch", "robust_z": 2.0, "reason": None}
    assert b.assess_cell(below_two, median, mad, 30)["level"] == "normal"
    at_three, below_three, median, mad = _exact_z_case(3.0)
    assert b.assess_cell(at_three, median, mad, 30) == {"level": "high", "robust_z": 3.0, "reason": None}
    assert b.assess_cell(below_three, median, mad, 30)["level"] == "watch"


def test_negative_z_is_normal_not_an_anomaly_tier():
    out = b.assess_cell(-0.5, 0.04, 0.02, 40)
    assert out["level"] == "normal" and out["robust_z"] < -3


@pytest.mark.parametrize(
    "ndci,median,mad,n,reason",
    [
        (0.1, 0.04, 0.02, 29, "insufficient_independent_dates"),
        (0.1, 0.04, 0.02, 0, "insufficient_independent_dates"),
        (0.1, 0.04, 0.0, 30, "zero_mad"),
        (1.5, 0.04, 0.02, 30, "invalid_ndci"),
        (-1.0001, 0.04, 0.02, 30, "invalid_ndci"),
        (float("nan"), 0.04, 0.02, 30, "invalid_ndci"),
        (None, 0.04, 0.02, 30, "invalid_ndci"),
        (float("inf"), 0.04, 0.02, 30, "invalid_ndci"),
        (0.1, float("nan"), 0.02, 30, "no_baseline"),
        (0.1, 0.04, float("nan"), 30, "no_baseline"),
        (0.1, 0.04, -0.01, 30, "no_baseline"),
        (0.1, None, 0.02, 30, "no_baseline"),
        (0.1, 0.04, 0.02, None, "insufficient_independent_dates"),
        (0.1, 0.04, 0.02, float("nan"), "insufficient_independent_dates"),
    ],
)
def test_assess_cell_reasons(ndci, median, mad, n, reason):
    assert b.assess_cell(ndci, median, mad, n) == {"level": None, "robust_z": None, "reason": reason}


def test_reason_precedence_follows_signal_anomaly():
    # observation first, then baseline presence, then the date floor, then MAD
    assert b.assess_cell(2.0, float("nan"), 0.0, 5)["reason"] == "invalid_ndci"
    assert b.assess_cell(0.1, float("nan"), 0.0, 5)["reason"] == "no_baseline"
    assert b.assess_cell(0.1, 0.04, 0.0, 5)["reason"] == "insufficient_independent_dates"


def test_ndci_at_exactly_minus_one_and_one_is_valid():
    assert b.assess_cell(1.0, 0.04, 0.02, 30)["level"] == "high"
    assert b.assess_cell(-1.0, 0.04, 0.02, 30)["level"] == "normal"


def test_a_stricter_declared_floor_is_honoured():
    assert b.assess_cell(0.15, 0.04, 0.02, 35, min_dates=40)["reason"] == "insufficient_independent_dates"
    assert b.assess_cell(0.15, 0.04, 0.02, 40, min_dates=40)["level"] == "high"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"min_dates": 29},
        {"mad_scale": 1.0},
        {"watch_at_z": 1.5},
        {"high_at_z": 2.5},
    ],
)
def test_loosened_parameters_are_refused(kwargs):
    with pytest.raises(ValueError):
        b.assess_cell(0.1, 0.04, 0.02, 45, **kwargs)
    with pytest.raises(ValueError):
        b.assess_cells(np.array([0.1]), np.array([0.04]), np.array([0.02]), np.array([45]), **kwargs)


def _case_grid():
    ndcis = [0.04, 0.05, 0.1, 0.15, -0.2, 1.0, -1.0, 1.5, -1.5, float("nan"), float("inf")]
    medians = [0.04, 0.0, -0.03, float("nan")]
    mads = [0.02, 0.0, 0.005, float("nan"), -0.01]
    ns = [0, 1, 29, 30, 31, 400]
    cases = [
        (ndci, med, m, n)
        for ndci in ndcis for med in medians for m in mads for n in ns
    ]
    # The exact z = 2 and z = 3 boundaries, and the float just below each.
    for z in (2.0, 3.0):
        at, below, median, mad = _exact_z_case(z)
        cases += [(at, median, mad, 30), (below, median, mad, 30), (at, median, mad, 29)]
    return cases


def test_assess_cells_equals_assess_cell_elementwise():
    cases = _case_grid()
    ndci = np.array([c[0] for c in cases], dtype=np.float64)
    median = np.array([c[1] for c in cases], dtype=np.float64)
    mad = np.array([c[2] for c in cases], dtype=np.float64)
    n = np.array([c[3] for c in cases], dtype=np.int64)

    z, level, reason = b.assess_cells(ndci, median, mad, n)
    assert z.dtype == np.float32 and level.dtype == np.uint8 and reason.dtype == np.uint8
    assert z.shape == level.shape == reason.shape == (len(cases),)

    seen_levels, seen_reasons = set(), set()
    for i, case in enumerate(cases):
        scalar = b.assess_cell(*case)
        assert b.LEVEL_CODES[int(level[i])] == scalar["level"], case
        assert b.REASON_CODES[int(reason[i])] == scalar["reason"], case
        if scalar["robust_z"] is None:
            assert math.isnan(z[i]), case
        else:
            assert z[i] == np.float32(scalar["robust_z"]), case
        seen_levels.add(scalar["level"])
        seen_reasons.add(scalar["reason"])
    # The grid really exercises every outcome.
    assert seen_levels == {None, "normal", "watch", "high"}
    assert seen_reasons == {None, "invalid_ndci", "no_baseline", "insufficient_independent_dates", "zero_mad"}


def test_assess_cells_on_storage_dtypes():
    """float32 NDCI/median/MAD and uint16 n, as the stored arrays are."""
    ndci = np.array([0.15, 0.05, 0.3], dtype=np.float32)
    median = np.array([0.04, 0.04, 0.04], dtype=np.float32)
    mad = np.array([0.02, 0.02, 0.0], dtype=np.float32)
    n = np.array([45, 12, 45], dtype=np.uint16)
    z, level, reason = b.assess_cells(ndci, median, mad, n)
    expected = b.assess_cell(float(ndci[0]), float(median[0]), float(mad[0]), int(n[0]))
    assert z[0] == np.float32(expected["robust_z"])
    assert level.tolist() == [b.LEVEL_CODE["high"], 0, 0]
    assert reason.tolist() == [0, b.REASON_CODE["insufficient_independent_dates"], b.REASON_CODE["zero_mad"]]


def test_code_tables_are_documented_and_inverse():
    assert b.LEVEL_CODES == {0: None, 1: "normal", 2: "watch", 3: "high"}
    assert b.REASON_CODES == {
        0: None, 1: "invalid_ndci", 2: "no_baseline", 3: "insufficient_independent_dates", 4: "zero_mad",
    }
    assert all(b.LEVEL_CODE[v] == k for k, v in b.LEVEL_CODES.items() if v is not None)
    assert all(b.REASON_CODE[v] == k for k, v in b.REASON_CODES.items() if v is not None)


def test_assess_cells_refuses_mismatched_shapes():
    with pytest.raises(ValueError):
        b.assess_cells(np.array([0.1, 0.2]), np.array([0.04]), np.array([0.02]), np.array([30]))


# --------------------------------------------------------------------------
# Season summary
# --------------------------------------------------------------------------


def test_cell_season_summary_counts_and_percentiles():
    n = np.array([10, 30, 31, 45, 60], dtype=np.uint16)
    mad = np.array([0.5, 0.01, 0.02, 0.03, 0.04], dtype=np.float32)
    s = b.cell_season_summary(n, mad)
    assert s["cells"] == 5
    assert s["cells_n_ge_floor"] == 4
    assert s["share_n_ge_floor"] == pytest.approx(0.8)
    assert (s["n_min"], s["n_median"], s["n_max"]) == (10, 31, 60)
    # MAD percentiles are over the cells that can be assessed (n >= floor).
    assert s["mad_p50"] == pytest.approx(float(np.percentile(mad[1:].astype(np.float64), 50)))
    assert s["mad_p05"] <= s["mad_p50"] <= s["mad_p95"] < 0.5
    assert all(isinstance(s[k], int) for k in ("cells", "cells_n_ge_floor", "n_min", "n_max"))


def test_cell_season_summary_of_nothing_has_no_numbers_to_invent():
    s = b.cell_season_summary(np.array([], dtype=np.uint16), np.array([], dtype=np.float32))
    assert s["cells"] == 0 and s["cells_n_ge_floor"] == 0
    assert s["share_n_ge_floor"] == 0.0
    assert s["n_median"] is None and s["mad_p50"] is None


# --------------------------------------------------------------------------
# level_b manifest block
# --------------------------------------------------------------------------

SIG = "c" * 16
TODAY = date(2026, 10, 9)


def _season(month: int, cells: int = 100, ge: int = 95) -> dict:
    return {
        "file": b.cells_file_name(month),
        "months": list(b.season_months(month)),
        "cells": cells,
        "cells_n_ge_floor": ge,
        "share_n_ge_floor": ge / cells if cells else 0.0,
        "n_median": 40.0,
        "n_min": 3,
        "n_max": 60,
        "mad_p05": 0.02,
        "mad_p50": 0.03,
        "mad_p95": 0.05,
        "n_dates": 140,
        "first_date": "2017-12-13",
        "last_date": "2026-09-20",
    }


def _level_b(**overrides) -> dict:
    block = b.build_level_b(
        scale_m=200,
        cell_preprocessing_signature=SIG,
        cell_preprocessing_params={"scale_m": 200},
        built_at="2026-10-09T01:00:00+00:00",
        query_start="2017-03-28",
        query_end_exclusive="2026-09-24",
        seasons={b.season_key(m): _season(m) for m in range(1, 13)},
    )
    block.update(overrides)
    return block


def test_cells_file_name():
    assert b.cells_file_name(1) == "cells_m01.npz"
    assert b.cells_file_name(12) == "cells_m12.npz"
    with pytest.raises(ValueError):
        b.cells_file_name(13)


def test_level_b_block_shape():
    block = _level_b()
    for key in ("scale_m", "cell_preprocessing_signature", "history_start", "history_end", "seasons"):
        assert key in block
    assert block["history_end"] == "2026-09-23"  # the day before the exclusive query end
    assert block["history_start"] == "2017-12-13"  # earliest acquisition in any season
    assert block["query_end_exclusive"] == "2026-09-24"
    assert block["min_independent_dates"] == sa.MIN_INDEPENDENT_DATES
    assert block["min_cell_share"] == b.LEVEL_B_MIN_CELL_SHARE == 0.9
    assert set(block["seasons"]) == {b.season_key(m) for m in range(1, 13)}
    for key, info in block["seasons"].items():
        for field in ("file", "months", "cells", "cells_n_ge_floor", "n_median", "n_min", "n_max",
                      "mad_p05", "mad_p50", "mad_p95"):
            assert field in info, (key, field)
    assert block["cell_key"]["deg_per_cell"] == DEG
    b.validate_level_b(block, live_cell_signature=SIG, today=TODAY)


def test_level_b_signature_mismatch_is_invalid():
    with pytest.raises(b.BaselineInvalid, match="^cell_signature_mismatch$"):
        b.validate_level_b(_level_b(), live_cell_signature="d" * 16, today=TODAY)


def test_level_b_history_end_after_today_is_invalid():
    with pytest.raises(b.BaselineInvalid, match="^level_b_history_in_future$"):
        b.validate_level_b(_level_b(history_end="2026-10-10"), live_cell_signature=SIG, today=TODAY)


@pytest.mark.parametrize("field", ["scale_m", "cell_preprocessing_signature", "history_start", "history_end", "seasons"])
def test_level_b_missing_field(field):
    block = _level_b()
    del block[field]
    with pytest.raises(b.BaselineInvalid, match=f"^missing_field:level_b.{field}$"):
        b.validate_level_b(block, live_cell_signature=SIG, today=TODAY)


def test_level_b_not_a_dict():
    with pytest.raises(b.BaselineInvalid, match="^missing_field:level_b$"):
        b.validate_level_b(["no"], live_cell_signature=SIG, today=TODAY)


def test_level_b_needs_all_twelve_seasons():
    block = _level_b()
    del block["seasons"][b.season_key(7)]
    with pytest.raises(b.BaselineInvalid, match="^level_b_seasons_incomplete$"):
        b.validate_level_b(block, live_cell_signature=SIG, today=TODAY)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s: s.update(file="../sites.json"),
        lambda s: s.update(file="cells_m02.npz"),
        lambda s: s.update(months=[1, 2, 3]),
        lambda s: s.update(cells=-1),
        lambda s: s.update(cells_n_ge_floor=101),
        lambda s: s.update(cells="100"),
        lambda s: s.pop("cells_n_ge_floor"),
    ],
)
def test_level_b_malformed_season_is_invalid(mutate):
    block = _level_b()
    mutate(block["seasons"]["m01+-1"])
    with pytest.raises(b.BaselineInvalid, match=r"^level_b_bad_season:m01\+-1$"):
        b.validate_level_b(block, live_cell_signature=SIG, today=TODAY)


def test_level_b_season_below_the_cell_share_floor_is_invalid():
    block = _level_b()
    block["seasons"]["m08+-1"] = _season(8, cells=100, ge=89)
    with pytest.raises(b.BaselineInvalid, match=r"^level_b_below_floor:m08\+-1$"):
        b.validate_level_b(block, live_cell_signature=SIG, today=TODAY)


def test_level_b_cannot_declare_a_looser_floor():
    with pytest.raises(b.BaselineInvalid, match="^level_b_below_floor$"):
        b.validate_level_b(_level_b(min_independent_dates=20), live_cell_signature=SIG, today=TODAY)
    with pytest.raises(b.BaselineInvalid, match="^level_b_below_floor$"):
        b.validate_level_b(_level_b(min_cell_share=0.5), live_cell_signature=SIG, today=TODAY)


def test_level_b_history_start_after_end_is_invalid():
    with pytest.raises(b.BaselineInvalid, match="^level_b_bad_history$"):
        b.validate_level_b(_level_b(history_start="2026-09-30"), live_cell_signature=SIG, today=TODAY)


def test_level_b_bad_scale_is_invalid():
    with pytest.raises(b.BaselineInvalid, match="^level_b_bad_scale$"):
        b.validate_level_b(_level_b(scale_m=0), live_cell_signature=SIG, today=TODAY)


# --------------------------------------------------------------------------
# validate_manifest and level_b
# --------------------------------------------------------------------------


def _manifest_a(**extra) -> dict:
    manifest = b.build_manifest(
        baseline_version="TEST-20261009-aaaaaaaa",
        built_at="2026-10-09T01:00:00+00:00",
        history_start="2017-12-13",
        history_end="2026-10-07",
        preprocessing_signature="a" * 16,
        preprocessing_params={},
        locations={"x": {"n_dates": 300, "min_season_dates": 35, "first": "2017-12-13", "last": "2026-10-07"}},
        self_check={"total": {}},
        builder_git_sha=None,
    )
    manifest.update(extra)
    return manifest


def test_validate_manifest_checks_level_b_only_when_asked():
    broken = _manifest_a(level_b={"nonsense": True})
    # The Level A gate never passes a cell signature: a broken Level B block
    # must not switch off the site baseline.
    b.validate_manifest(broken, live_signature="a" * 16, today=TODAY)
    with pytest.raises(b.BaselineInvalid, match="^missing_field:level_b.scale_m$"):
        b.validate_manifest(broken, live_signature="a" * 16, today=TODAY, live_cell_signature=SIG)


def test_validate_manifest_with_a_cell_signature_requires_level_b():
    with pytest.raises(b.BaselineInvalid, match="^missing_field:level_b$"):
        b.validate_manifest(_manifest_a(), live_signature="a" * 16, today=TODAY, live_cell_signature=SIG)


def test_validate_manifest_accepts_a_good_level_b_and_rejects_a_stale_one():
    manifest = _manifest_a(level_b=_level_b())
    b.validate_manifest(manifest, live_signature="a" * 16, today=TODAY, live_cell_signature=SIG)
    with pytest.raises(b.BaselineInvalid, match="^cell_signature_mismatch$"):
        b.validate_manifest(manifest, live_signature="a" * 16, today=TODAY, live_cell_signature="e" * 16)


def test_level_a_problems_still_win_first():
    manifest = _manifest_a(level_b=_level_b())
    with pytest.raises(b.BaselineInvalid, match="^signature_mismatch$"):
        b.validate_manifest(manifest, live_signature="z" * 16, today=TODAY, live_cell_signature=SIG)
