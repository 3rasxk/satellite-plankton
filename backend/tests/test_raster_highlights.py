"""Highlight pins -- the top-N measured cells of one stored run by NDCI.

Pure ranking on synthetic grids: no GEE, no database, no files. Every
grid here is an `OverlayGrid` built by hand (20 x 20 pixels at a fake
1 km scale over real upper-Gulf coordinates), with stored cells placed
just off their pixel centres so the observation coordinate and the drawn
square's centre are never accidentally the same number.

What these tests defend:

    the cohort      -- only cells the overlay paints (state "reading":
                       date-valid, finite NDCI, pixel centre inside the
                       polygon, last cell per pixel) are ranked; a masked
                       export's 0.0 never is
    the order       -- NDCI descending, then lower row, then lower column,
                       independent of the order cells were stored in
    de-duplication  -- greedy non-maximum suppression by great-circle
                       distance, checked against an independent brute-force
                       reference written with `math`, not numpy
    the facts       -- percentile over the same cohort, edge_of_no_data
                       with the polygon-boundary rule, null secondary
                       indices, honest empty / fewer-than-n reasons
    no tier         -- risk_tier is null on every pin and no source line
                       can set it to anything else
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import numpy as np
import pytest

from src import _detection as bridge
from src.raster_scan import highlights, pixel, render
from src.raster_scan.render import OverlayGrid

NEW_MS = 1788492600000  # 2026-09-04T03:30:00Z, a real upper-Gulf pass time
DATE_BAND = bridge.RASTER_DATE_BAND
INDEX_BANDS = bridge.RASTER_INDEX_BANDS

# Fake scale: 1 km pixels, so a 20 x 20 grid spans ~20 km and a 3 km
# separation is a few pixels -- small enough to see, large enough to bite.
STEP = 1000 / render.METRES_PER_DEGREE
NORTH, WEST = 13.20, 100.20
ROWS = COLS = 20

PIN_FIELDS = {
    "rank", "cell_lat", "cell_lng", "pixel_centre_lat", "pixel_centre_lng",
    "index_values", "percentile", "date_ms", "acquired_date", "acquired_at",
    "edge_of_no_data", "metric_value", "risk_tier",
}


def synthetic_grid(rows: int = ROWS, cols: int = COLS) -> OverlayGrid:
    return OverlayGrid(
        north=NORTH, south=NORTH - rows * STEP, west=WEST, east=WEST + cols * STEP,
        rows=rows, cols=cols, pixel_deg_lat=STEP, pixel_deg_lng=STEP,
        pixel_size_source="test",
    )


def rect_polygon(north, south, west, east):
    return ((south, west), (north, west), (north, east), (south, east))


def whole_grid_polygon(grid: OverlayGrid):
    """Every pixel centre clearly inside; every off-grid centre outside."""
    return rect_polygon(grid.north, grid.south, grid.west, grid.east)


def f32(value: float) -> float:
    """What a stored float32 reading reads back as."""
    return float(np.float32(value))


def build_cells(grid, field, *, absent=(), masked=(), dates=None, extra=None):
    """One stored cell per pixel of `field` (rows x cols NDCI values).

    absent -- (row, col) pixels with no stored cell at all.
    masked -- (row, col) pixels stored the way GEE's NPY export writes a
              masked pixel: date 0 and 0.0 in every band (the 0.0 trap).
    extra  -- {band: {(row, col): value}} per-cell overrides.
    Cells sit 0.1 pixel north-east of their pixel centre.
    """
    centre_lats, centre_lngs = grid.pixel_centres()
    absent, masked = set(absent), set(masked)
    extra = extra or {}
    rows_out = {"lat": [], "lng": [], DATE_BAND: [], **{b: [] for b in INDEX_BANDS}}
    for r in range(grid.rows):
        for c in range(grid.cols):
            if (r, c) in absent:
                continue
            rows_out["lat"].append(centre_lats[r] + 0.1 * grid.pixel_deg_lat)
            rows_out["lng"].append(centre_lngs[c] + 0.1 * grid.pixel_deg_lng)
            if (r, c) in masked:
                rows_out[DATE_BAND].append(0)
                for band in INDEX_BANDS:
                    rows_out[band].append(0.0)
                continue
            rows_out[DATE_BAND].append(NEW_MS if dates is None else dates[r][c])
            rows_out["ndci"].append(field[r][c])
            rows_out["bda2"].append(extra.get("bda2", {}).get((r, c), 1.0 + field[r][c]))
            rows_out["bda3"].append(extra.get("bda3", {}).get((r, c), 0.3))
            rows_out["b2_b3"].append(extra.get("b2_b3", {}).get((r, c), 0.8))
    return {
        "lat": np.asarray(rows_out["lat"], dtype=np.float64),
        "lng": np.asarray(rows_out["lng"], dtype=np.float64),
        DATE_BAND: np.asarray(rows_out[DATE_BAND], dtype=np.int64),
        **{b: np.asarray(rows_out[b], dtype=np.float32) for b in INDEX_BANDS},
    }


def pin_pixel(grid, pin):
    return grid.locate(pin["pixel_centre_lat"], pin["pixel_centre_lng"])


def rank(cells, grid, *, n=5, sep=3000, polygon=None):
    return highlights.rank_cells(
        cells, grid=grid, n=n, min_separation_m=sep,
        polygon=polygon if polygon is not None else whole_grid_polygon(grid),
    )


def haversine_m_reference(lat1, lng1, lat2, lng2):
    """Independent scalar great-circle distance (data-pipeline rainfall.py's
    formula and radius), so the ranking's numpy version is checked against
    a second implementation rather than against itself."""
    r_m = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r_m * math.asin(math.sqrt(a))


# --------------------------------------------------------------------------
# Ordering and de-duplication
# --------------------------------------------------------------------------


def test_pins_are_ordered_by_ndci_descending_with_ranks_from_one():
    grid = synthetic_grid()
    field = np.full((ROWS, COLS), 0.01)
    peaks = {(2, 2): 0.09, (2, 15): 0.12, (10, 8): 0.05, (17, 3): 0.11, (17, 17): 0.07}
    for (r, c), v in peaks.items():
        field[r, c] = v
    result = rank(build_cells(grid, field), grid, n=5, sep=3000)

    pins = result["pins"]
    assert [p["rank"] for p in pins] == [1, 2, 3, 4, 5]
    assert [p["metric_value"] for p in pins] == [f32(v) for v in (0.12, 0.11, 0.09, 0.07, 0.05)]
    assert [pin_pixel(grid, p) for p in pins] == [(2, 15), (17, 3), (2, 2), (17, 17), (10, 8)]
    assert all(p["metric_value"] == p["index_values"]["ndci"] for p in pins)
    assert result["cohort_size"] == ROWS * COLS
    assert result["reason"] is None


def test_every_pin_carries_exactly_the_specified_fields():
    grid = synthetic_grid()
    field = np.full((ROWS, COLS), 0.02)
    field[5, 5] = 0.08
    pin = rank(build_cells(grid, field), grid, n=3)["pins"][0]
    assert set(pin) == PIN_FIELDS
    assert set(pin["index_values"]) == set(INDEX_BANDS)
    assert pin["date_ms"] == NEW_MS
    assert pin["acquired_date"] == "2026-09-04"
    assert pin["acquired_at"] == "2026-09-04T03:30:00Z"
    # Observation coordinate and drawn-square centre are different numbers.
    assert pin["cell_lat"] != pin["pixel_centre_lat"]
    assert pin["cell_lng"] != pin["pixel_centre_lng"]


def test_nms_skips_cells_within_the_separation_of_a_higher_pin():
    grid = synthetic_grid()
    field = np.zeros((ROWS, COLS))
    field[5, 5] = 0.10
    field[5, 6] = 0.09   # adjacent east, ~973 m: suppressed
    field[6, 5] = 0.085  # adjacent south, ~999 m: suppressed
    field[7, 7] = 0.084  # diagonal 2 px, ~2.8 km: suppressed at 3000 m
    field[5, 9] = 0.08   # 4 px east, ~3.9 km: kept
    pins = rank(build_cells(grid, field), grid, n=3, sep=3000)["pins"]

    chosen = [pin_pixel(grid, p) for p in pins]
    assert chosen[:2] == [(5, 5), (5, 9)]
    for skipped in [(5, 6), (6, 5), (7, 7)]:
        assert skipped not in chosen
    # The third is a genuine dated 0.0 reading, chosen by the tie-break
    # (lowest row, then lowest column) among cells far enough from both.
    assert chosen[2] == (0, 0)
    assert pins[2]["metric_value"] == 0.0


def test_the_separation_is_great_circle_metres_between_cell_coordinates():
    """Just under the real gap keeps the second pin; just over drops it --
    so the distance used is the haversine gap between the two observation
    coordinates, to within a metre, not a pixel count or a degree delta."""
    grid = synthetic_grid()
    field = np.full((ROWS, COLS), -0.05)
    field[5, 5], field[5, 9] = 0.10, 0.09
    cells = build_cells(grid, field)
    pins = {pin_pixel(grid, p): p for p in rank(cells, grid, n=3, sep=1000)["pins"]}
    a, b = pins[(5, 5)], pins[(5, 9)]
    gap = haversine_m_reference(a["cell_lat"], a["cell_lng"], b["cell_lat"], b["cell_lng"])
    assert 3800 < gap < 4000  # 4 columns of ~973 m at 13.1 N

    under = rank(cells, grid, n=2, sep=gap - 1.0)["pins"]
    assert [pin_pixel(grid, p) for p in under] == [(5, 5), (5, 9)]
    over = rank(cells, grid, n=2, sep=gap + 1.0)["pins"]
    assert (5, 9) not in [pin_pixel(grid, p) for p in over]


def _reference_pins(grid, field, n, sep):
    """Brute-force greedy NMS over a full field: sort by (-v, row, col),
    keep a candidate unless within `sep` metres of an already-kept one."""
    centre_lats, centre_lngs = grid.pixel_centres()
    candidates = sorted(
        ((-f32(field[r, c]), r, c) for r in range(grid.rows) for c in range(grid.cols))
    )
    kept: list[tuple[int, int, float, float]] = []
    for _neg, r, c in candidates:
        lat = centre_lats[r] + 0.1 * grid.pixel_deg_lat
        lng = centre_lngs[c] + 0.1 * grid.pixel_deg_lng
        if all(haversine_m_reference(lat, lng, klat, klng) >= sep for _, _, klat, klng in kept):
            kept.append((r, c, lat, lng))
        if len(kept) == n:
            break
    return [(r, c) for r, c, _, _ in kept]


@pytest.mark.parametrize("seed", [0, 1, 2, 3])
@pytest.mark.parametrize("n,sep", [(5, 3000), (10, 1000), (10, 10000), (3, 2500)])
def test_ranking_matches_an_independent_brute_force_reference(seed, n, sep):
    """Reference: `_reference_pins`, a plain-Python greedy NMS with a
    `math` haversine. EXHAUSTIVE over each 400-cell field. Values are
    quantised so ties are common and the tie-break is exercised."""
    grid = synthetic_grid()
    rng = np.random.default_rng(seed)
    field = np.round(rng.uniform(-0.04, 0.14, size=(ROWS, COLS)), 2)
    pins = rank(build_cells(grid, field), grid, n=n, sep=sep)["pins"]
    assert [pin_pixel(grid, p) for p in pins] == _reference_pins(grid, field, n, sep)
    for i, a in enumerate(pins):
        for b in pins[i + 1:]:
            assert haversine_m_reference(a["cell_lat"], a["cell_lng"],
                                         b["cell_lat"], b["cell_lng"]) >= sep


def test_ties_break_by_lower_row_then_lower_column_whatever_the_storage_order():
    grid = synthetic_grid()
    field = np.full((ROWS, COLS), -0.02)
    for rc in [(12, 4), (3, 15), (3, 2), (12, 1)]:
        field[rc] = 0.05
    cells = build_cells(grid, field)
    expected = [(3, 2), (3, 15), (12, 1), (12, 4)]
    assert [pin_pixel(grid, p) for p in rank(cells, grid, n=4, sep=1000)["pins"]] == expected

    rng = np.random.default_rng(7)
    for _ in range(3):
        order = rng.permutation(cells["lat"].size)
        shuffled = {k: v[order] for k, v in cells.items()}
        got = rank(shuffled, grid, n=4, sep=1000)["pins"]
        assert [pin_pixel(grid, p) for p in got] == expected


# --------------------------------------------------------------------------
# Percentile
# --------------------------------------------------------------------------


def test_percentile_is_the_share_of_the_cohort_strictly_below():
    grid = synthetic_grid()
    field = np.zeros((ROWS, COLS))
    placed = {(1, 1): 0.1, (1, 18): 0.2, (18, 1): 0.2, (18, 18): 0.3}
    for rc, v in placed.items():
        field[rc] = v
    absent = [(r, c) for r in range(ROWS) for c in range(COLS) if (r, c) not in placed]
    result = rank(build_cells(grid, field, absent=absent), grid, n=4, sep=1000)

    assert result["cohort_size"] == 4
    assert [p["metric_value"] for p in result["pins"]] == [f32(0.3), f32(0.2), f32(0.2), f32(0.1)]
    # 3 of 4 below 0.3; 1 of 4 strictly below either 0.2; none below 0.1.
    assert [p["percentile"] for p in result["pins"]] == [75.0, 25.0, 25.0, 0.0]
    assert result["reason"] is None


# --------------------------------------------------------------------------
# edge_of_no_data
# --------------------------------------------------------------------------


def test_edge_flag_is_true_next_to_a_hole_and_false_in_the_interior():
    grid = synthetic_grid()
    field = np.full((ROWS, COLS), 0.0)
    field[10, 11] = 0.12  # east of the hole at (10, 10)
    field[3, 3] = 0.11    # interior, all 8 neighbours measured
    field[16, 15] = 0.10  # diagonal to a masked export at (15, 14)
    field[4, 15] = 0.09   # next to a dated cell whose NDCI is not finite
    field[3, 16] = np.nan
    cells = build_cells(grid, field, absent=[(10, 10)], masked=[(15, 14)])
    pins = {pin_pixel(grid, p): p for p in rank(cells, grid, n=4, sep=3000)["pins"]}

    assert pins[(10, 11)]["edge_of_no_data"] is True
    assert pins[(3, 3)]["edge_of_no_data"] is False
    assert pins[(16, 15)]["edge_of_no_data"] is True, "a masked 0.0 is no data, not a neighbour reading"
    assert pins[(4, 15)]["edge_of_no_data"] is True, "a NaN NDCI is drawn transparent"


def test_edge_flag_ignores_neighbours_outside_the_polygon():
    """The polygon covers columns 0..9 only. A cell on its east boundary
    has outside-polygon neighbours with no cells -- never looked at, so
    not 'unmeasured'. A grid-corner cell's off-grid neighbours likewise."""
    grid = synthetic_grid()
    poly = rect_polygon(grid.north, grid.south, grid.west, grid.west + 10 * STEP)
    field = np.full((ROWS, COLS), 0.0)
    field[10, 9] = 0.12   # on the polygon's east boundary
    field[0, 0] = 0.11    # grid corner
    absent = [(r, c) for r in range(ROWS) for c in range(10, COLS)]
    pins = {pin_pixel(grid, p): p for p in rank(build_cells(grid, field, absent=absent),
                                                grid, n=3, sep=3000, polygon=poly)["pins"]}
    assert pins[(10, 9)]["edge_of_no_data"] is False
    assert pins[(0, 0)]["edge_of_no_data"] is False


def test_an_unmeasured_neighbour_inside_the_polygon_counts_even_off_the_grid():
    """A synthetic polygon reaching past the grid: the area beyond the
    grid's north edge is inside the study area and carries no reading."""
    grid = synthetic_grid()
    poly = rect_polygon(grid.north + 5 * STEP, grid.south, grid.west, grid.east)
    field = np.full((ROWS, COLS), 0.0)
    field[0, 10] = 0.12
    pin = rank(build_cells(grid, field), grid, n=3, sep=3000, polygon=poly)["pins"][0]
    assert pin_pixel(grid, pin) == (0, 10)
    assert pin["edge_of_no_data"] is True


# --------------------------------------------------------------------------
# Cohort: what may and may not be ranked
# --------------------------------------------------------------------------


def test_the_zero_trap_a_masked_export_never_ranks_but_a_dated_zero_does():
    grid = synthetic_grid()
    field = np.full((ROWS, COLS), -0.03)
    field[2, 2] = 0.0  # a genuine dated 0.0 reading
    cells = build_cells(grid, field, masked=[(8, 8)])
    result = rank(cells, grid, n=10, sep=1000)

    chosen = [pin_pixel(grid, p) for p in result["pins"]]
    assert (8, 8) not in chosen
    assert all(p["date_ms"] > 0 for p in result["pins"])
    assert chosen[0] == (2, 2) and result["pins"][0]["metric_value"] == 0.0
    assert result["cohort_size"] == ROWS * COLS - 1


def test_a_cell_outside_the_polygon_never_ranks_however_high():
    grid = synthetic_grid()
    poly = rect_polygon(grid.north, grid.south, grid.west, grid.west + 10 * STEP)
    field = np.full((ROWS, COLS), 0.01)
    field[5, 15] = 0.5  # outside the polygon
    result = rank(build_cells(grid, field), grid, n=10, sep=1000, polygon=poly)
    assert (5, 15) not in [pin_pixel(grid, p) for p in result["pins"]]
    assert result["cohort_size"] == ROWS * 10


def test_two_cells_in_one_pixel_rank_once_as_the_cell_that_painted_it():
    """numpy's last-write-wins painted the pixel with the second cell, and
    /raster-scan/pixel answers with it; the ranking must agree."""
    grid = synthetic_grid()
    field = np.full((ROWS, COLS), 0.0)
    cells = build_cells(grid, field)
    centre_lats, centre_lngs = grid.pixel_centres()
    covered = {
        "lat": np.array([centre_lats[4] - 0.2 * STEP]),
        "lng": np.array([centre_lngs[4] - 0.2 * STEP]),
        DATE_BAND: np.array([NEW_MS], dtype=np.int64),
        **{b: np.array([0.2], dtype=np.float32) for b in INDEX_BANDS},
    }
    painted = {**covered, "lat": covered["lat"] + 0.05 * STEP}
    painted = {**painted, **{b: np.array([0.05], dtype=np.float32) for b in INDEX_BANDS}}
    merged = {k: np.concatenate([cells[k], covered[k], painted[k]]) for k in cells}

    result = rank(merged, grid, n=3, sep=3000)
    assert result["cohort_size"] == ROWS * COLS
    top = result["pins"][0]
    assert pin_pixel(grid, top) == (4, 4)
    assert top["metric_value"] == f32(0.05)
    found = pixel.inspect_cell(merged, top["cell_lat"], top["cell_lng"], grid,
                               whole_grid_polygon(grid))
    assert found["index_values"]["ndci"] == top["metric_value"]


def test_fewer_separable_cells_than_requested_gives_fewer_pins_and_says_so():
    grid = synthetic_grid()
    field = np.full((ROWS, COLS), 0.03)
    block = {(5, 5), (5, 6), (6, 5), (6, 6)}
    absent = [(r, c) for r in range(ROWS) for c in range(COLS) if (r, c) not in block]
    result = rank(build_cells(grid, field, absent=absent), grid, n=5, sep=3000)
    assert result["cohort_size"] == 4
    assert len(result["pins"]) == 1
    assert result["reason"] == "only 1 separable measured cells"


@pytest.mark.parametrize("case", ["all_masked", "no_cells", "all_nan"])
def test_an_empty_cohort_gives_no_pins_and_says_why(case):
    grid = synthetic_grid()
    field = np.full((ROWS, COLS), np.nan if case == "all_nan" else 0.0)
    everything = [(r, c) for r in range(ROWS) for c in range(COLS)]
    if case == "all_masked":
        cells = build_cells(grid, field, masked=everything)
    elif case == "no_cells":
        cells = build_cells(grid, field, absent=everything)
    else:
        cells = build_cells(grid, field)
    result = rank(cells, grid, n=5, sep=3000)
    assert result == {"cohort_size": 0, "pins": [], "reason": "no measured cells",
                      "excluded_degenerate": 0}


def test_an_unreadable_secondary_index_is_null_not_a_number():
    grid = synthetic_grid()
    field = np.full((ROWS, COLS), 0.0)
    field[9, 9] = 0.1
    cells = build_cells(grid, field, extra={
        "bda3": {(9, 9): np.nan}, "b2_b3": {(9, 9): np.inf},
    })
    pin = rank(cells, grid, n=3, sep=3000)["pins"][0]
    assert pin_pixel(grid, pin) == (9, 9)
    assert pin["index_values"] == {
        "ndci": f32(0.1), "bda2": f32(1.1), "bda3": None, "b2_b3": None,
    }


# --------------------------------------------------------------------------
# Degenerate readings: NDCI exactly +/-1 (a zero band) never pins
# --------------------------------------------------------------------------


def test_degenerate_readings_stay_in_the_cohort_but_never_pin():
    grid = synthetic_grid()
    field = np.zeros((ROWS, COLS))
    placed = {(1, 1): 1.0, (1, 18): 0.9999995, (18, 1): -1.0,
              (5, 5): 0.999998, (18, 18): 0.3, (10, 10): 0.2}
    for rc, v in placed.items():
        field[rc] = v
    absent = [(r, c) for r in range(ROWS) for c in range(COLS) if (r, c) not in placed]
    result = rank(build_cells(grid, field, absent=absent), grid, n=5, sep=1000)

    assert result["cohort_size"] == 6, "degenerate cells are measured cells the map paints"
    assert result["excluded_degenerate"] == 3
    assert [pin_pixel(grid, p) for p in result["pins"]] == [(5, 5), (18, 18), (10, 10)]
    # Percentile is over the FULL cohort: 1.0 and 0.9999995 are above the
    # top pin, -1.0 is below every pin.
    assert [p["percentile"] for p in result["pins"]] == [50.0, 2 / 6 * 100.0, 1 / 6 * 100.0]
    assert result["reason"] == "only 3 separable measured cells"


def test_a_degenerate_cell_never_suppresses_a_real_neighbour():
    grid = synthetic_grid()
    field = np.full((ROWS, COLS), -0.05)
    field[5, 5], field[5, 6] = 1.0, 0.12  # ~1 km apart, inside the 3 km radius
    pins = rank(build_cells(grid, field), grid, n=3, sep=3000)["pins"]
    assert pin_pixel(grid, pins[0]) == (5, 6)
    assert all(p["metric_value"] < 1.0 for p in pins)


def test_an_all_degenerate_cohort_says_so():
    grid = synthetic_grid()
    result = rank(build_cells(grid, np.ones((ROWS, COLS))), grid, n=5, sep=3000)
    assert result["pins"] == [] and result["cohort_size"] == ROWS * COLS
    assert result["excluded_degenerate"] == ROWS * COLS
    assert result["reason"] == (f"no measured cells eligible for pins ({ROWS * COLS} excluded: "
                                "NDCI exactly +/-1, a zero band)")


# --------------------------------------------------------------------------
# Agreement with the click lookup and the renderer
# --------------------------------------------------------------------------


def test_every_pin_is_what_a_click_on_its_cell_reports():
    """Reference: `pixel.inspect_cell` -- the /raster-scan/pixel lookup.
    A pin whose popup disagreed with a click on the same square would be
    two answers about one measurement."""
    grid = synthetic_grid()
    poly = whole_grid_polygon(grid)
    rng = np.random.default_rng(11)
    field = rng.uniform(-0.04, 0.14, size=(ROWS, COLS))
    cells = build_cells(grid, field, absent=[(3, 3), (12, 12)], masked=[(7, 1)])
    pins = rank(cells, grid, n=10, sep=1000)["pins"]
    assert len(pins) == 10
    for pin in pins:
        found = pixel.inspect_cell(cells, pin["cell_lat"], pin["cell_lng"], grid, poly)
        assert found["state"] == pixel.STATE_READING
        assert found["index_values"] == pin["index_values"]
        assert found["date_ms"] == pin["date_ms"]
        assert (found["cell_lat"], found["cell_lng"]) == (pin["cell_lat"], pin["cell_lng"])
        assert (found["pixel_centre_lat"], found["pixel_centre_lng"]) == (
            pin["pixel_centre_lat"], pin["pixel_centre_lng"])


def test_cohort_size_equals_the_measured_pixels_the_renderer_painted():
    """Reference: `render_overlay`'s own `measured_pixels` for the same
    cells, polygon and grid -- including NaN, masked and outside cells."""
    poly = ((12.9500, 100.0000), (13.0000, 100.0000), (13.0000, 100.0500), (12.9500, 100.0500))
    step = 200 / render.METRES_PER_DEGREE
    lats = np.arange(12.9400, 13.0100, step)
    lngs = np.arange(99.9950, 100.0300, step)
    lat_grid, lng_grid = np.meshgrid(lats, lngs, indexing="ij")
    count = lat_grid.size
    rng = np.random.default_rng(3)
    ndci = rng.uniform(-0.05, 0.15, count).astype(np.float32)
    ndci[::17] = np.nan
    dates = np.full(count, NEW_MS, dtype=np.int64)
    dates[::13] = 0
    cells = {
        "lat": lat_grid.ravel(), "lng": lng_grid.ravel(), DATE_BAND: dates,
        "ndci": ndci, **{b: np.full(count, 0.5, dtype=np.float32) for b in INDEX_BANDS[1:]},
    }
    rendered = render.render_overlay(cells, band="ndci", scale_m=200, polygon=poly)
    result = highlights.rank_cells(cells, grid=rendered.grid, n=5, min_separation_m=1000,
                                   polygon=poly)
    assert result["cohort_size"] == rendered.stats["measured_pixels"] > 0


# --------------------------------------------------------------------------
# No tier, no claims
# --------------------------------------------------------------------------


def test_every_pin_has_a_null_tier():
    grid = synthetic_grid()
    rng = np.random.default_rng(5)
    pins = rank(build_cells(grid, rng.uniform(0, 0.1, (ROWS, COLS))), grid, n=10, sep=1000)["pins"]
    assert pins and all(p["risk_tier"] is None for p in pins)


def test_no_source_line_assigns_a_tier_other_than_none():
    """Grep, not trust: the highlights module and its router must have no
    code path that sets `risk_tier` to anything but None."""
    backend = Path(__file__).resolve().parents[1]
    # The lookahead sits after the operator and swallows its own spaces, so
    # backtracking cannot make `"risk_tier": None` look like an offender.
    assignment = re.compile(r"""risk_tier["']?\]?\s*[:=](?!\s*None\b)""")
    assert assignment.search('pin["risk_tier"] = "watch"')
    assert assignment.search("risk_tier=level")
    assert not assignment.search('"risk_tier": None,')
    for relative in ("src/raster_scan/highlights.py", "src/routers/raster_scan.py",
                     "src/raster_scan/cell_anomaly.py", "src/schemas.py"):
        source = (backend / relative).read_text()
        offenders = [line for line in source.splitlines() if assignment.search(line)]
        assert not offenders, f"{relative} sets risk_tier: {offenders}"


@pytest.mark.parametrize("bad", [
    {"n": 0}, {"min_separation_m": -1}, {"metric": "bda2"}, {"metric": "risk"},
])
def test_invalid_arguments_are_refused(bad):
    grid = synthetic_grid()
    kwargs = {"grid": grid, "n": 5, "min_separation_m": 3000,
              "polygon": whole_grid_polygon(grid), **bad}
    with pytest.raises(ValueError):
        highlights.rank_cells(build_cells(grid, np.zeros((ROWS, COLS))), **kwargs)


def test_the_module_docstring_states_source_and_limits():
    doc = highlights.__doc__ or ""
    for phrase in ("Data source", "no GEE", "not a risk level", "not an anomaly",
                   "sediment", "shallow bottom", "glint", "cloud edges"):
        assert phrase in doc, phrase


# --------------------------------------------------------------------------
# Anomaly mode (Level B TEST cell baseline; baseline spec §6)
#
# The same cohort, NMS and edge rule as above; the order is robust z
# against each cell's OWN seasonal baseline, and only cells meeting the
# condition (assessable, z >= 2) can be pins. Fixture artefacts and the
# lattice-aligned synthetic raster come from test_raster_pixel_anomaly.
# --------------------------------------------------------------------------

from src import baseline_store  # noqa: E402
from tests import test_raster_pixel_anomaly as afx  # noqa: E402

ANOMALY_PIN_FIELDS = PIN_FIELDS | {"robust_z", "median_ndci", "mad", "n_dates", "anomaly_level"}
COUNT_KEYS = ["measured", "assessable", "no_baseline", "insufficient_dates", "zero_mad",
              "not_after_history", "too_old", "invalid", "watch", "high", "flagged_share"]
A_ROWS, A_COLS = afx.ROWS, afx.COLS


@pytest.fixture()
def anomaly_root(tmp_path, monkeypatch):
    root = tmp_path / "baselines"
    afx.isolate_baselines(root, monkeypatch)
    yield root
    baseline_store.clear_cell_cache()


def rank_anomalies(cells, *, n=5, sep=1000, date_used=afx.DATE_USED, polygon=None):
    grid = afx.lattice_grid()
    return highlights.rank_anomaly_cells(
        cells, grid=grid, context=afx.context_for(date_used), n=n, min_separation_m=sep,
        polygon=polygon if polygon is not None else afx.whole_grid_polygon(grid),
    )


def a_pixel(pin):
    return afx.lattice_grid().locate(pin["pixel_centre_lat"], pin["pixel_centre_lng"])


def test_anomaly_pins_rank_by_robust_z_against_each_cells_own_baseline(anomaly_root):
    stats = {(5, 5): (0.08, 0.02, 40),     # NDCI 0.12 here is only z = 1.35
             (20, 20): (0.02, 0.01, 40), (20, 5): (0.02, 0.01, 40), (5, 20): (0.02, 0.01, 40)}
    afx.write_cell_artefact(anomaly_root, afx.baseline_stats(overrides=stats))
    field = np.full((A_ROWS, A_COLS), 0.02)
    peaks = {(5, 5): 0.12, (20, 20): 0.07, (20, 5): 0.065, (5, 20): 0.06}
    for rc, v in peaks.items():
        field[rc] = v
    result = rank_anomalies(afx.raster_cells(afx.lattice_grid(), field))

    pins = result["pins"]
    assert [a_pixel(p) for p in pins] == [(20, 20), (20, 5), (5, 20)]
    assert (5, 5) not in [a_pixel(p) for p in pins], "highest NDCI, but not anomalous for itself"
    assert [p["rank"] for p in pins] == [1, 2, 3]
    assert [p["anomaly_level"] for p in pins] == ["high", "high", "watch"]
    for pin in pins:
        median, mad, n_dates = stats[a_pixel(pin)]
        assert pin["robust_z"] == afx.expected_z(peaks[a_pixel(pin)], median, mad)
        assert pin["metric_value"] == pin["robust_z"]
        assert (pin["median_ndci"], pin["mad"], pin["n_dates"]) == (f32(median), f32(mad), n_dates)
        assert pin["risk_tier"] is None
    assert pins[0]["robust_z"] == pytest.approx(0.05 / (1.4826 * 0.01), rel=1e-6)
    assert result["cohort_size"] == A_ROWS * A_COLS == result["counts"]["measured"]
    assert result["counts"]["watch"] == 1 and result["counts"]["high"] == 2
    assert result["reason"] == "only 3 separable cells meet the condition (900 assessable of 900 measured)"


def test_every_anomaly_pin_carries_the_ndci_fields_plus_the_anomaly_fields(anomaly_root):
    afx.write_cell_artefact(anomaly_root, afx.baseline_stats())
    field = np.full((A_ROWS, A_COLS), 0.02)
    field[7, 7] = 0.09
    pin = rank_anomalies(afx.raster_cells(afx.lattice_grid(), field))["pins"][0]
    assert set(pin) == ANOMALY_PIN_FIELDS
    assert set(pin["index_values"]) == set(INDEX_BANDS)
    assert pin["index_values"]["ndci"] == f32(0.09)
    assert pin["date_ms"] == afx.NEW_MS and pin["acquired_date"] == "2026-09-04"
    assert pin["cell_lat"] != pin["pixel_centre_lat"]


@pytest.mark.parametrize("z, pinned, level", [(2.0, True, "watch"), (3.0, True, "high")])
def test_anomaly_boundary_z_exactly_on_the_threshold_pins(anomaly_root, z, pinned, level):
    ndci, median, mad = afx.exact_z_case(z)
    afx.write_cell_artefact(anomaly_root, afx.baseline_stats(overrides={(3, 3): (median, mad, 40)}))
    field = np.full((A_ROWS, A_COLS), 0.02)
    field[3, 3] = ndci
    pins = rank_anomalies(afx.raster_cells(afx.lattice_grid(), field))["pins"]
    assert [a_pixel(p) for p in pins] == [(3, 3)]
    assert pins[0]["robust_z"] == z and pins[0]["anomaly_level"] == level


def test_anomaly_z_just_under_two_is_not_a_pin(anomaly_root):
    afx.write_cell_artefact(anomaly_root, afx.baseline_stats())
    field = np.full((A_ROWS, A_COLS), 0.02)
    field[3, 3] = 0.02 + 1.999 * 1.4826 * 0.01  # z ~ 1.999
    result = rank_anomalies(afx.raster_cells(afx.lattice_grid(), field))
    assert result["pins"] == []
    assert result["counts"]["watch"] == result["counts"]["high"] == 0
    assert result["reason"] == "no cells meet the condition (900 assessable of 900 measured)"


def test_a_negative_anomaly_never_pins_however_large(anomaly_root):
    afx.write_cell_artefact(anomaly_root, afx.baseline_stats())
    field = np.full((A_ROWS, A_COLS), 0.02)
    field[4, 4] = -0.5  # z ~ -35
    result = rank_anomalies(afx.raster_cells(afx.lattice_grid(), field))
    assert result["pins"] == []
    assert result["counts"]["assessable"] == A_ROWS * A_COLS


def test_anomaly_ties_break_by_ndci_then_row_then_column(anomaly_root):
    # Dyadic values: z of (0.125, mad 2m) equals z of (0.0625, mad m) exactly.
    m = 0.0078125
    stats = {(2, 2): (0.0, m, 40), (2, 20): (0.0, 2 * m, 40),
             (20, 2): (0.0, m, 40), (12, 12): (0.0, m, 40)}
    afx.write_cell_artefact(anomaly_root, afx.baseline_stats(overrides=stats))
    field = np.full((A_ROWS, A_COLS), 0.0)
    field[2, 2], field[2, 20], field[20, 2], field[12, 12] = 0.0625, 0.125, 0.0625, 0.0625
    cells = afx.raster_cells(afx.lattice_grid(), field)
    expected = [(2, 20), (2, 2), (12, 12), (20, 2)]
    pins = rank_anomalies(cells, n=4)["pins"]
    assert len({p["robust_z"] for p in pins}) == 1, "a genuine four-way tie in z"
    assert [a_pixel(p) for p in pins] == expected
    rng = np.random.default_rng(3)
    for _ in range(3):
        order = rng.permutation(cells["lat"].size)
        shuffled = {k: v[order] for k, v in cells.items()}
        assert [a_pixel(p) for p in rank_anomalies(shuffled, n=4)["pins"]] == expected


def test_anomaly_nms_uses_the_same_great_circle_separation(anomaly_root):
    afx.write_cell_artefact(anomaly_root, afx.baseline_stats())
    field = np.full((A_ROWS, A_COLS), 0.02)
    field[10, 10] = 0.12   # highest z
    field[10, 11] = 0.11   # 1 px east (~195 m): suppressed
    field[10, 15] = 0.10   # 5 px east (~973 m): suppressed at 1000 m
    field[10, 16] = 0.09   # 6 px east (~1168 m): kept
    pins = rank_anomalies(afx.raster_cells(afx.lattice_grid(), field), n=5, sep=1000)["pins"]
    assert [a_pixel(p) for p in pins] == [(10, 10), (10, 16)]
    gap = haversine_m_reference(pins[0]["cell_lat"], pins[0]["cell_lng"],
                                pins[1]["cell_lat"], pins[1]["cell_lng"])
    assert gap >= 1000


def test_anomaly_ranking_matches_a_brute_force_reference(anomaly_root):
    afx.write_cell_artefact(anomaly_root, afx.baseline_stats())
    grid = afx.lattice_grid()
    rng = np.random.default_rng(21)
    field = np.round(rng.uniform(0.0, 0.09, size=(A_ROWS, A_COLS)), 3)
    cells = afx.raster_cells(grid, field)
    pins = rank_anomalies(cells, n=10, sep=1500)["pins"]

    centre_lats, centre_lngs = grid.pixel_centres()
    candidates = []
    for r in range(A_ROWS):
        for c in range(A_COLS):
            z = afx.expected_z(field[r, c], 0.02, 0.01)
            if z >= 2.0:
                candidates.append((-z, -f32(field[r, c]), r, c))
    kept = []
    for _z, _v, r, c in sorted(candidates):
        lat, lng = centre_lats[r] + 0.1 * afx.D, centre_lngs[c] + 0.1 * afx.D
        if all(haversine_m_reference(lat, lng, klat, klng) >= 1500 for _, _, klat, klng in kept):
            kept.append((r, c, lat, lng))
        if len(kept) == 10:
            break
    assert [a_pixel(p) for p in pins] == [(r, c) for r, c, _, _ in kept]


def test_anomaly_percentile_is_over_the_assessable_cells(anomaly_root):
    afx.write_cell_artefact(anomaly_root, afx.baseline_stats(missing=[(0, 0)]))
    field = np.full((A_ROWS, A_COLS), 0.02)
    field[5, 5], field[15, 15] = 0.09, 0.07
    field[0, 0] = 0.5  # no baseline: measured, not assessable, never in the percentile
    result = rank_anomalies(afx.raster_cells(afx.lattice_grid(), field))
    assessable = result["counts"]["assessable"]
    assert assessable == A_ROWS * A_COLS - 1
    assert [p["percentile"] for p in result["pins"]] == [
        (assessable - 1) / assessable * 100.0, (assessable - 2) / assessable * 100.0]


def test_anomaly_counts_partition_the_cohort_with_the_specified_keys(anomaly_root):
    overrides = {(0, c): (0.02, 0.01, afx.FLOOR - 1) for c in range(3)}
    overrides.update({(1, c): (0.02, 0.0, 50) for c in range(4)})
    afx.write_cell_artefact(anomaly_root, afx.baseline_stats(overrides=overrides,
                                                             missing=[(2, 0), (2, 1)]))
    field = np.full((A_ROWS, A_COLS), 0.02)
    field[3, 0] = -1.5
    field[25, 25] = 0.09
    # On history_end (14 days before date_used, so not too old): leakage
    # guard. Sixteen days before date_used: too old (checked first).
    dates = {(4, 0): afx.ms_on(afx.HISTORY_END), (4, 1): afx.ms_on(afx.HISTORY_END, 10, 0),
             (5, 0): afx.ms_on("2026-08-29")}
    result = rank_anomalies(afx.raster_cells(afx.lattice_grid(), field, dates=dates,
                                             masked=[(6, 6)]))
    counts = result["counts"]
    assert list(counts) == COUNT_KEYS
    assert counts == {
        "measured": 899, "assessable": 899 - 3 - 4 - 2 - 1 - 2 - 1,
        "no_baseline": 2, "insufficient_dates": 3, "zero_mad": 4,
        "not_after_history": 2, "too_old": 1, "invalid": 1, "watch": 0, "high": 1,
        "flagged_share": 1 / 886,
    }
    reasons = sum(counts[k] for k in COUNT_KEYS[2:8])
    assert counts["assessable"] + reasons == counts["measured"] == result["cohort_size"]


def test_empty_anomaly_pins_say_whether_anything_was_assessable(anomaly_root):
    afx.write_cell_artefact(anomaly_root, afx.baseline_stats())
    grid = afx.lattice_grid()
    on_history = {(r, c): afx.ms_on(afx.HISTORY_END) for r in range(A_ROWS) for c in range(A_COLS)}
    stale = rank_anomalies(afx.raster_cells(grid, np.full((A_ROWS, A_COLS), 0.2), dates=on_history))
    assert stale["pins"] == []
    assert stale["counts"]["assessable"] == 0
    assert stale["reason"] == ("no measured cells are assessable against the TEST cell baseline "
                               "(0 assessable of 900 measured)")
    assert stale["counts"]["flagged_share"] is None

    calm = rank_anomalies(afx.raster_cells(grid, np.full((A_ROWS, A_COLS), 0.02)))
    assert calm["pins"] == []
    assert calm["reason"] == "no cells meet the condition (900 assessable of 900 measured)"
    assert calm["counts"]["flagged_share"] == 0.0
    assert stale["reason"] != calm["reason"]

    everything = [(r, c) for r in range(A_ROWS) for c in range(A_COLS)]
    empty = rank_anomalies(afx.raster_cells(grid, np.zeros((A_ROWS, A_COLS)), masked=everything))
    assert empty["pins"] == [] and empty["reason"] == "no measured cells"
    assert empty["cohort_size"] == 0 and empty["counts"]["measured"] == 0


def test_anomaly_cohort_is_the_painted_cells_only(anomaly_root):
    """A masked export or a cell outside the polygon never ranks, however
    anomalous its stored value would be."""
    afx.write_cell_artefact(anomaly_root, afx.baseline_stats())
    grid = afx.lattice_grid()
    polygon = ((grid.south, grid.west), (grid.north, grid.west),
               (grid.north, grid.west + 15 * afx.D), (grid.south, grid.west + 15 * afx.D))
    field = np.full((A_ROWS, A_COLS), 0.02)
    field[5, 20] = 0.3   # outside the polygon
    field[8, 8] = 0.07
    result = rank_anomalies(afx.raster_cells(grid, field, masked=[(9, 9)]), polygon=polygon)
    assert [a_pixel(p) for p in result["pins"]] == [(8, 8)]
    assert result["counts"]["measured"] == A_ROWS * 15 - 1


def test_degenerate_cells_are_never_anomaly_pins(anomaly_root):
    afx.write_cell_artefact(anomaly_root, afx.baseline_stats())
    field = np.full((A_ROWS, A_COLS), 0.02)
    field[3, 3], field[3, 20], field[8, 8] = 1.0, 0.9999995, 0.08
    result = rank_anomalies(afx.raster_cells(afx.lattice_grid(), field))
    assert [a_pixel(p) for p in result["pins"]] == [(8, 8)]
    assert result["counts"]["invalid"] == 2
    assert result["excluded_degenerate"] == 2
    assert result["counts"]["measured"] == result["cohort_size"] == A_ROWS * A_COLS


def test_anomaly_pins_keep_the_edge_of_no_data_rule(anomaly_root):
    afx.write_cell_artefact(anomaly_root, afx.baseline_stats())
    field = np.full((A_ROWS, A_COLS), 0.02)
    field[10, 11] = 0.09  # east of a hole
    field[20, 20] = 0.08  # interior
    pins = {a_pixel(p): p for p in rank_anomalies(
        afx.raster_cells(afx.lattice_grid(), field, absent=[(10, 10)]))["pins"]}
    assert pins[(10, 11)]["edge_of_no_data"] is True
    assert pins[(20, 20)]["edge_of_no_data"] is False


def test_anomaly_pins_and_ndci_pins_share_the_click_answer(anomaly_root):
    """An anomaly pin's cell is the cell a click on its square reports."""
    afx.write_cell_artefact(anomaly_root, afx.baseline_stats())
    grid = afx.lattice_grid()
    polygon = afx.whole_grid_polygon(grid)
    rng = np.random.default_rng(13)
    field = rng.uniform(0.0, 0.09, size=(A_ROWS, A_COLS))
    cells = afx.raster_cells(grid, field, absent=[(3, 3)])
    for pin in rank_anomalies(cells, n=10)["pins"]:
        found = pixel.inspect_cell(cells, pin["cell_lat"], pin["cell_lng"], grid, polygon)
        assert found["index_values"] == pin["index_values"]
        assert found["date_ms"] == pin["date_ms"]
        assert (found["pixel_centre_lat"], found["pixel_centre_lng"]) == (
            pin["pixel_centre_lat"], pin["pixel_centre_lng"])


def test_ndci_ranking_is_unchanged_when_a_cell_baseline_is_active(anomaly_root):
    """Mode ndci never looks at the baseline: same pins, same keys."""
    grid = synthetic_grid()
    field = np.full((ROWS, COLS), 0.02)
    field[5, 5] = 0.08
    before = rank(build_cells(grid, field), grid, n=3)
    afx.write_cell_artefact(anomaly_root, afx.baseline_stats())
    after = rank(build_cells(grid, field), grid, n=3)
    assert before == after
    assert set(after["pins"][0]) == PIN_FIELDS
    assert set(after) == {"cohort_size", "pins", "reason", "excluded_degenerate"}
