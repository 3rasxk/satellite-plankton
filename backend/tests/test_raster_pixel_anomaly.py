"""Per-cell TEST anomaly (Level B): the cell assessment and the cell inspector.

Offline and synthetic. Every cell baseline here is a real artefact written
under pytest's ``tmp_path`` (``baseline_store.BASELINE_ROOT`` pointed there)
from a manifest built by the real ``detection/src/baseline.py`` through the
bridge (``build_manifest``, ``build_level_b``, ``cell_season_summary``), and
read back through the real never-raising loader -- the fixture is what the
builder writes, not a hand copy. Raster cells are synthetic, placed on the
same 200 m EPSG:4326 lattice the production raster reads on, a tenth of a
cell off the lattice centre so cells are matched by ``cell_key``, never by
identical coordinates. Nothing here touches GEE or ``backend/data``.

What is pinned:
  * the statistic is ``(ndci - median) / (1.4826 * mad)``, hand-checked;
  * a cell is assessable only when every rule passes, and otherwise lands
    in exactly ONE reason bucket, in the documented priority order, so
    ``assessable + reasons == measured``;
  * the leakage guard: a cell acquired on ``level_b.history_end`` is not
    assessable, one day later it is;
  * the observation-age rule (14 days, inclusive) and the floor declared by
    the Level B block;
  * ``/raster-scan/pixel``'s ``anomaly`` block: null with the mode off (every
    other key and value unchanged), equal to the highlights pin for the same
    cell, null when no Level B baseline can be used.

Helpers here are imported by ``test_raster_highlights.py`` and
``test_raster_scan_endpoint.py`` (the repository's precedent for shared test
helpers, e.g. ``tests.test_baseline_gate._artefact``).
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pytest
from sqlalchemy import delete

from src import _detection as bridge
from src import baseline_store, config, scientific_status
from src.db import SessionLocal
from src.db_models import RasterScanRun
from src.raster_scan import cell_anomaly, render, storage
from src.raster_scan.render import OverlayGrid
from src.schemas import DISCLAIMER_TEXT, DISCLAIMER_TEXT_TEST_BASELINE

logic = bridge.baseline_logic

SCALE_M = config.RASTER_SCAN_SCALE_M
D = logic.cell_size_deg(SCALE_M)
FLOOR = bridge.SIGNAL_ANOMALY_MIN_INDEPENDENT_DATES
DATE_BAND = bridge.RASTER_DATE_BAND
INDEX_BANDS = bridge.RASTER_INDEX_BANDS

HISTORY_END = "2026-08-31"
DATE_USED = "2026-09-14"
SEASON = logic.season_key(9)
NEW_MS = 1788492600000  # 2026-09-04T03:30:00Z
BUILT_ON = date(2026, 9, 2)

# Pure-test grid: 30 x 30 lattice cells (6 km) whose overlay pixels ARE
# the 200 m key lattice; north and west edges sit on lattice edges.
ROWS = COLS = 30
K_NORTH = 7300  # north edge = 7300 * D ~ 13.115 N
K_WEST = 55780  # west edge = 55780 * D ~ 100.218 E

DEFAULT_STATS = (0.02, 0.01, 40)  # median, mad, n
# Stored visible DN (red B4, green B3, blue B2) of an ordinary bright-enough
# water pixel, well above the 50 DN low-signal screen.
VISIBLE_DEFAULT = (400.0, 350.0, 300.0)
TRUE_COLOR = bridge.RASTER_TRUE_COLOR_BANDS


def f32(value: float) -> float:
    """What a stored float32 reads back as."""
    return float(np.float32(value))


def ms_on(day: str, hour: int = 3, minute: int = 30) -> int:
    """Epoch ms of ``day`` at ``hour:minute`` UTC (a plausible pass time)."""
    moment = datetime.fromisoformat(day).replace(hour=hour, minute=minute, tzinfo=timezone.utc)
    return int(moment.timestamp() * 1000)


def expected_z(ndci: float, median: float, mad: float) -> float:
    """The robust z by hand, on the float32 values the files store."""
    return (f32(ndci) - f32(median)) / (1.4826 * f32(mad))


def exact_z_case(z: float) -> tuple[float, float, float]:
    """``(ndci, median, mad)`` as float32 values whose robust z, computed in
    float64 exactly as signal_anomaly does, is EXACTLY ``z`` -- so the
    inclusive boundaries are tested on the boundary, not near it."""
    for mad in np.linspace(0.008, 0.03, 4000).astype(np.float32):
        scale = 1.4826 * float(mad)
        target = z * scale
        for shift in (1e-9, 3e-9, 1e-8, 3e-8, 1e-7):
            ndci = np.float32(target + shift)
            median = np.float32(float(ndci) - target)
            if (float(ndci) - float(median)) / scale == z:
                return float(ndci), float(median), float(mad)
    raise AssertionError(f"no float32 case gives z == {z} exactly")


# --------------------------------------------------------------------------
# A real artefact: Level A (one site) + Level B (12 seasons, same cells)
# --------------------------------------------------------------------------


def _site_rows() -> list[dict]:
    return [
        {"acquisition_date": f"{y}-{m:02d}-{d:02d}", "ndci": 0.02 + 0.001 * ((y + m + d) % 7)}
        for y in range(2014, 2026) for m in range(1, 13) for d in (5, 20)
    ]


def lattice_centre(key: tuple[int, int]) -> tuple[float, float]:
    return ((key[0] + 0.5) * D, (key[1] + 0.5) * D)


def write_cell_artefact(root, stats: dict, *, history_end: str = HISTORY_END,
                        built_on: date = BUILT_ON, floor: float = FLOOR) -> dict:
    """Write a complete TEST artefact whose Level B season files all hold
    ``stats`` = {cell_key: (median, mad, n)}; return its manifest.

    ``floor``: the ``level_b.min_independent_dates`` the block declares (a
    stricter floor than the builder's 30 is legal; the season counts are
    computed against it, as the loader checks)."""
    keys = sorted(stats)
    centres = [lattice_centre(k) for k in keys]
    arrays = {
        "lat": np.array([c[0] for c in centres], dtype=np.float64),
        "lng": np.array([c[1] for c in centres], dtype=np.float64),
        "median": np.array([stats[k][0] for k in keys], dtype=np.float32),
        "mad": np.array([stats[k][1] for k in keys], dtype=np.float32),
        "n": np.array([stats[k][2] for k in keys], dtype=np.uint16),
    }
    seasons = {}
    for month in range(1, 13):
        seasons[logic.season_key(month)] = {
            "file": logic.cells_file_name(month),
            "months": list(logic.season_months(month)),
            **logic.cell_season_summary(arrays["n"], arrays["mad"], floor=floor),
            "n_dates": 140, "first_date": "2017-04-27", "last_date": history_end,
        }
    end_exclusive = (date.fromisoformat(history_end) + timedelta(days=1)).isoformat()
    level_b = logic.build_level_b(
        scale_m=SCALE_M,
        cell_preprocessing_signature=baseline_store.live_cell_signature(),
        cell_preprocessing_params=baseline_store.live_cell_preprocessing_params(),
        built_at=f"{built_on.isoformat()}T03:00:00+00:00",
        query_start="2017-03-28",
        query_end_exclusive=end_exclusive,
        seasons=seasons,
    )
    level_b["min_independent_dates"] = floor
    rows = {"alpha": _site_rows()}
    signature = logic.preprocessing_signature(bridge.preprocessing_params())
    manifest = logic.build_manifest(
        baseline_version=logic.version_for(built_on, signature),
        built_at=f"{built_on.isoformat()}T03:00:00+00:00",
        history_start=rows["alpha"][0]["acquisition_date"],
        history_end=rows["alpha"][-1]["acquisition_date"],
        preprocessing_signature=signature,
        preprocessing_params=bridge.preprocessing_params(),
        locations={"alpha": {"n_dates": len(rows["alpha"]), "min_season_dates": 72,
                             "first": rows["alpha"][0]["acquisition_date"],
                             "last": rows["alpha"][-1]["acquisition_date"]}},
        self_check={"by_season": {}, "total": {"assessed": 10, "watch": 1, "high": 0,
                                               "no_assessment": 2, "reasons": {}}},
        builder_git_sha=None,
    )
    manifest["level_b"] = level_b
    files = {logic.cells_file_name(m): arrays for m in range(1, 13)}
    baseline_store.write_artifact(root, manifest, rows, replace=True, cells_by_file=files)
    return manifest


def isolate_baselines(root, monkeypatch, *, mode: str = "test") -> None:
    """Point the store at ``root`` with clean caches and the given mode."""
    monkeypatch.setattr(baseline_store, "BASELINE_ROOT", root)
    monkeypatch.setattr(baseline_store, "_artifact_cache", None)
    monkeypatch.setattr(baseline_store, "_last_cell_warning", None)
    baseline_store.clear_cell_cache()
    monkeypatch.setattr(config, "BASELINE_MODE", mode)


def context_for(date_used: str = DATE_USED):
    """The anomaly context the endpoints build: one status + one season."""
    resolved = cell_anomaly.resolve(scientific_status.baseline_status(), date_used)
    assert isinstance(resolved, cell_anomaly.AnomalyContext), resolved
    return resolved


# --------------------------------------------------------------------------
# Synthetic raster on the lattice
# --------------------------------------------------------------------------


def lattice_grid(rows: int = ROWS, cols: int = COLS) -> OverlayGrid:
    return OverlayGrid(
        north=K_NORTH * D, south=(K_NORTH - rows) * D,
        west=K_WEST * D, east=(K_WEST + cols) * D,
        rows=rows, cols=cols, pixel_deg_lat=D, pixel_deg_lng=D, pixel_size_source="test",
    )


def whole_grid_polygon(grid: OverlayGrid):
    return ((grid.south, grid.west), (grid.north, grid.west),
            (grid.north, grid.east), (grid.south, grid.east))


def key_of(row: int, col: int) -> tuple[int, int]:
    """The cell_key of overlay pixel (row, col) of ``lattice_grid``."""
    return (K_NORTH - row - 1, K_WEST + col)


def baseline_stats(rows: int = ROWS, cols: int = COLS, *, overrides=None, missing=()) -> dict:
    """{cell_key: (median, mad, n)} for every pixel, DEFAULT_STATS unless
    overridden; ``missing`` pixels have no baseline cell at all."""
    overrides = overrides or {}
    missing = set(missing)
    return {
        key_of(r, c): overrides.get((r, c), DEFAULT_STATS)
        for r in range(rows) for c in range(cols) if (r, c) not in missing
    }


def raster_cells(grid: OverlayGrid, field, *, dates=None, absent=(), masked=(),
                 visible=None, with_visible=True) -> dict:
    """One stored cell per pixel of ``field`` (rows x cols NDCI), 0.1 cell
    north-east of the lattice centre. ``dates``: {(r, c): epoch ms}
    overrides of NEW_MS. ``masked``: GEE's masked export (date 0, 0.0).
    ``visible``: {(r, c): (red, green, blue) DN} overrides of
    VISIBLE_DEFAULT; ``with_visible=False`` stores no visible bands."""
    centre_lats, centre_lngs = grid.pixel_centres()
    absent, masked = set(absent), set(masked)
    dates = dates or {}
    visible = visible or {}
    out = {"lat": [], "lng": [], DATE_BAND: [], **{b: [] for b in INDEX_BANDS},
           **{b: [] for b in TRUE_COLOR}}
    for r in range(grid.rows):
        for c in range(grid.cols):
            if (r, c) in absent:
                continue
            out["lat"].append(centre_lats[r] + 0.1 * D)
            out["lng"].append(centre_lngs[c] + 0.1 * D)
            if (r, c) in masked:
                out[DATE_BAND].append(0)
                for band in (*INDEX_BANDS, *TRUE_COLOR):
                    out[band].append(0.0)
                continue
            out[DATE_BAND].append(dates.get((r, c), NEW_MS))
            out["ndci"].append(field[r][c])
            out["bda2"].append(1.0 + field[r][c])
            out["bda3"].append(0.3)
            out["b2_b3"].append(0.8)
            for band, dn in zip(TRUE_COLOR, visible.get((r, c), VISIBLE_DEFAULT)):
                out[band].append(dn)
    stored = {
        "lat": np.asarray(out["lat"], dtype=np.float64),
        "lng": np.asarray(out["lng"], dtype=np.float64),
        DATE_BAND: np.asarray(out[DATE_BAND], dtype=np.int64),
        **{b: np.asarray(out[b], dtype=np.float32) for b in INDEX_BANDS},
    }
    if with_visible:
        stored.update({b: np.asarray(out[b], dtype=np.float32) for b in TRUE_COLOR})
    return stored


def assess_all(cells: dict, context) -> dict:
    """``cell_anomaly.assess`` over every stored cell, screened."""
    return cell_anomaly.assess(cells["ndci"], cells["lat"], cells["lng"], cells[DATE_BAND],
                               context, visible=cell_anomaly.visible_dn(cells))


def assess_pixels(context, grid, cells, pixels) -> list[dict]:
    """``cell_anomaly.assess`` for the stored cells at the given pixels."""
    rows, cols = grid.cell_indices(cells["lat"], cells["lng"])
    index = [int(np.flatnonzero((rows == r) & (cols == c))[-1]) for r, c in pixels]
    visible = cell_anomaly.visible_dn(cells)
    result = cell_anomaly.assess(
        cells["ndci"][index], cells["lat"][index], cells["lng"][index],
        cells[DATE_BAND][index], context, visible=tuple(band[index] for band in visible),
    )
    return [cell_anomaly.describe(result, i) for i in range(len(index))]


@pytest.fixture()
def cell_root(tmp_path, monkeypatch):
    root = tmp_path / "baselines"
    isolate_baselines(root, monkeypatch)
    yield root
    baseline_store.clear_cell_cache()


# --------------------------------------------------------------------------
# The assessment: statistic, rules, buckets
# --------------------------------------------------------------------------


def test_z_is_the_robust_z_of_the_stored_values_by_hand(cell_root):
    write_cell_artefact(cell_root, baseline_stats(overrides={(4, 4): (0.03, 0.012, 41)}))
    grid = lattice_grid()
    field = np.full((ROWS, COLS), 0.02)
    field[4, 4] = 0.08
    got = assess_pixels(context_for(), grid, raster_cells(grid, field), [(4, 4)])[0]
    # (0.08 - 0.03) / (1.4826 * 0.012) = 2.8103... by hand; exactly the
    # float64 expression on the stored float32 values.
    assert got["robust_z"] == expected_z(0.08, 0.03, 0.012)
    assert got["robust_z"] == pytest.approx(0.05 / (1.4826 * 0.012), rel=1e-6)
    assert got["level"] == "watch"
    assert got["reason"] is None
    assert (got["median_ndci"], got["mad"], got["n_dates"]) == (f32(0.03), f32(0.012), 41)


@pytest.mark.parametrize("z, level", [(2.0, "watch"), (3.0, "high")])
def test_the_boundaries_are_inclusive_on_the_exact_value(cell_root, z, level):
    ndci, median, mad = exact_z_case(z)
    write_cell_artefact(cell_root, baseline_stats(overrides={(2, 2): (median, mad, 40)}))
    grid = lattice_grid()
    field = np.full((ROWS, COLS), 0.02)
    field[2, 2] = ndci
    got = assess_pixels(context_for(), grid, raster_cells(grid, field), [(2, 2)])[0]
    assert got["robust_z"] == z
    assert got["level"] == level
    # The next float32 down leaves the boundary.
    field[2, 2] = float(np.nextafter(np.float32(ndci), np.float32(-1)))
    below = assess_pixels(context_for(), grid, raster_cells(grid, field), [(2, 2)])[0]
    assert below["robust_z"] < z
    assert below["level"] == ("normal" if z == 2.0 else "watch")


def test_floor_from_the_level_b_declaration_and_strictly_positive_mad(cell_root):
    overrides = {(0, 0): (0.02, 0.01, FLOOR - 1), (0, 1): (0.02, 0.01, FLOOR),
                 (0, 2): (0.02, 0.0, 50)}
    write_cell_artefact(cell_root, baseline_stats(overrides=overrides))
    grid = lattice_grid()
    field = np.full((ROWS, COLS), 0.06)
    got = assess_pixels(context_for(), grid, raster_cells(grid, field), [(0, 0), (0, 1), (0, 2)])
    assert got[0]["reason"] == "insufficient_dates" and got[0]["robust_z"] is None
    assert got[0]["n_dates"] == FLOOR - 1, "the baseline's own count is shown, not hidden"
    assert got[1]["reason"] is None and got[1]["level"] == "watch"  # z = 0.04 / 0.014826 = 2.70
    assert got[2]["reason"] == "zero_mad" and got[2]["level"] is None


@pytest.mark.parametrize("declared, below, at", [(35, 34, 35), (30.5, 30, 31)])
def test_the_floor_is_the_one_the_level_b_block_declares(cell_root, declared, below, at):
    """A stricter declared floor is applied as declared; a fractional one is
    rounded UP (n is a whole number of dates), never truncated."""
    overrides = {(0, 0): (0.02, 0.01, below), (0, 1): (0.02, 0.01, at)}
    write_cell_artefact(cell_root, baseline_stats(overrides=overrides), floor=declared)
    context = context_for()
    assert context.cells.min_independent_dates == at
    grid = lattice_grid()
    got = assess_pixels(context, grid, raster_cells(grid, np.full((ROWS, COLS), 0.06)),
                        [(0, 0), (0, 1)])
    assert got[0]["reason"] == "insufficient_dates"
    assert got[1]["reason"] is None


def test_leak_guard_a_cell_acquired_on_history_end_is_not_assessable(cell_root):
    write_cell_artefact(cell_root, baseline_stats())
    grid = lattice_grid()
    field = np.full((ROWS, COLS), 0.06)
    dates = {(1, 1): ms_on(HISTORY_END, 23, 59), (1, 2): ms_on("2026-09-01", 0, 0),
             (1, 3): ms_on("2026-08-20")}
    got = assess_pixels(context_for("2026-09-03"), grid, raster_cells(grid, field, dates=dates),
                        [(1, 1), (1, 2), (1, 3)])
    assert got[0]["reason"] == "not_after_history" and got[0]["robust_z"] is None
    assert got[1]["reason"] is None and got[1]["robust_z"] is not None
    assert got[2]["reason"] == "not_after_history"


def test_observation_age_is_at_most_14_days_and_never_after_the_target(cell_root):
    write_cell_artefact(cell_root, baseline_stats(), history_end="2026-08-20")
    grid = lattice_grid()
    field = np.full((ROWS, COLS), 0.06)
    dates = {(0, 0): ms_on("2026-08-31"),  # 14 days before DATE_USED
             (0, 1): ms_on("2026-08-30"),  # 15 days
             (0, 2): ms_on("2026-09-14", 23, 59),  # the target date itself
             (0, 3): ms_on("2026-09-15")}  # after the target date
    got = assess_pixels(context_for(), grid, raster_cells(grid, field, dates=dates),
                        [(0, 0), (0, 1), (0, 2), (0, 3)])
    assert got[0]["reason"] is None
    assert got[1]["reason"] == "too_old"
    assert got[2]["reason"] is None
    assert got[3]["reason"] == "invalid"


def test_a_cell_15_days_older_than_date_used_is_too_old_even_inside_history(cell_root):
    """Priority: the observation rules (invalid, too_old) come before the
    baseline rules (not_after_history, no_baseline, insufficient, zero_mad)."""
    write_cell_artefact(cell_root, baseline_stats(missing=[(0, 0)]))
    grid = lattice_grid()
    field = np.full((ROWS, COLS), 0.06)
    field[0, 1] = 1.5  # outside [-1, 1]
    dates = {(0, 0): ms_on("2026-08-30"), (0, 1): ms_on("2026-08-30")}
    got = assess_pixels(context_for(), grid, raster_cells(grid, field, dates=dates),
                        [(0, 0), (0, 1)])
    assert got[0]["reason"] == "too_old"   # also on/before history_end, also no key
    assert got[1]["reason"] == "invalid"   # also too old


def test_a_degenerate_ndci_is_invalid_and_never_assessed(cell_root):
    """NDCI exactly +/-1 means a zero band (B4 = 0 or B5 = 0): not a
    water-colour value. |ndci| >= 1 - 1e-6 (float32 noise included) is
    `invalid`, even though detection's own [-1, 1] rule accepts it, and it
    takes the `invalid` slot ahead of every later rule."""
    write_cell_artefact(cell_root, baseline_stats(), history_end="2026-08-20")
    grid = lattice_grid()
    field = np.full((ROWS, COLS), 0.02)
    field[0, 0], field[0, 1], field[0, 2], field[0, 3], field[0, 4] = (
        1.0, -1.0, 0.9999995, 0.999998, 1.0)
    dates = {(0, 4): ms_on("2026-08-25")}  # degenerate AND too old
    got = assess_pixels(context_for(), grid, raster_cells(grid, field, dates=dates),
                        [(0, 0), (0, 1), (0, 2), (0, 3), (0, 4)])
    assert f32(0.9999995) >= cell_anomaly.DEGENERATE_NDCI_ABS > f32(0.999998)
    for degenerate in (got[0], got[1], got[2], got[4]):
        assert degenerate["reason"] == "invalid"
        assert degenerate["robust_z"] is None and degenerate["level"] is None
    assert got[3]["reason"] is None and got[3]["level"] == "high", "just under the rule: a value"


@pytest.mark.parametrize("band", [0, 1, 2], ids=["red_B4", "green_B3", "blue_B2"])
def test_low_signal_boundary_is_50_dn_on_each_visible_band(cell_root, band):
    """49 DN on ONE band screens the cell; 50 DN on every band does not."""
    write_cell_artefact(cell_root, baseline_stats())
    grid = lattice_grid()
    field = np.full((ROWS, COLS), 0.08)  # z ~ 4: high if assessed
    at_49 = list(VISIBLE_DEFAULT)
    at_49[band] = 49.0
    visible = {(0, 0): tuple(at_49), (0, 1): (50.0, 50.0, 50.0)}
    got = assess_pixels(context_for(), grid, raster_cells(grid, field, visible=visible),
                        [(0, 0), (0, 1)])
    assert cell_anomaly.MIN_VISIBLE_DN == 50
    assert got[0]["reason"] == "low_signal" and got[0]["robust_z"] is None
    assert got[0]["visible_bands_dn"] == dict(zip(("red", "green", "blue"), at_49))
    assert got[1]["reason"] is None and got[1]["level"] == "high"


def test_a_near_black_cell_with_high_ndci_is_low_signal_not_an_anomaly(cell_root):
    """The live run-6 pattern: red 1 DN, NDCI 0.97 -- a ratio of noise."""
    write_cell_artefact(cell_root, baseline_stats())
    grid = lattice_grid()
    field = np.full((ROWS, COLS), 0.02)
    field[2, 2] = 0.97
    got = assess_pixels(context_for(), grid,
                        raster_cells(grid, field, visible={(2, 2): (1.0, 20.0, 27.0)}), [(2, 2)])[0]
    assert got["reason"] == "low_signal" and got["level"] is None
    # The baseline facts are still shown: nothing is hidden, only not scored.
    assert (got["median_ndci"], got["n_dates"]) == (f32(0.02), 40)


def test_degenerate_takes_priority_over_low_signal_and_nan_bands_are_screened(cell_root):
    write_cell_artefact(cell_root, baseline_stats())
    grid = lattice_grid()
    field = np.full((ROWS, COLS), 0.06)
    field[0, 0] = 1.0  # degenerate AND near-black: `invalid` first
    visible = {(0, 0): (0.0, 5.0, 5.0), (0, 1): (np.nan, 350.0, 300.0),
               (0, 2): (400.0, np.inf, 300.0)}
    got = assess_pixels(context_for(), grid, raster_cells(grid, field, visible=visible),
                        [(0, 0), (0, 1), (0, 2)])
    assert got[0]["reason"] == "invalid"
    assert got[1]["reason"] == "low_signal", "an unverifiable band is screened, never assumed"
    assert got[1]["visible_bands_dn"]["red"] is None
    assert got[2]["reason"] == "low_signal"


def test_assess_requires_the_visible_bands():
    with pytest.raises(TypeError):
        cell_anomaly.assess(np.zeros(1), np.zeros(1), np.zeros(1), np.zeros(1), None)


def test_visible_bands_are_b4_b3_b2_as_the_raster_pipeline_stores_them():
    """Read, not trusted: data-pipeline's _index_bands stores B4/B3/B2 under
    true_red/true_green/true_blue."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "data-pipeline" / "src" / "raster.py").read_text()
    for index, (stored, band) in enumerate(cell_anomaly.VISIBLE_BANDS):
        assert stored == bridge.RASTER_TRUE_COLOR_BANDS[index]
        assert f"true_{('red', 'green', 'blue')[index]} = b{band[1]}.rename(" \
               f"RASTER_TRUE_COLOR_BANDS[{index}])" in source


def test_flagged_share_is_watch_plus_high_over_assessable(cell_root):
    write_cell_artefact(cell_root, baseline_stats())
    grid = lattice_grid()
    field = np.full((ROWS, COLS), 0.02)
    field[1, 1], field[2, 2], field[3, 3] = 0.06, 0.07, 0.09  # watch, high, high
    cells = raster_cells(grid, field, dates={(4, 4): ms_on(HISTORY_END)})
    result = assess_all(cells, context_for())
    counts = cell_anomaly.counts(result)
    assert (counts["watch"], counts["high"], counts["assessable"]) == (1, 2, ROWS * COLS - 1)
    assert counts["flagged_share"] == 3 / (ROWS * COLS - 1)
    on_history = raster_cells(grid, field, dates={(r, c): ms_on(HISTORY_END)
                                                  for r in range(ROWS) for c in range(COLS)})
    none = cell_anomaly.counts(assess_all(on_history, context_for()))
    assert none["assessable"] == 0 and none["flagged_share"] is None


def test_a_cell_without_a_baseline_key_is_no_baseline_never_a_default(cell_root):
    write_cell_artefact(cell_root, baseline_stats(missing=[(3, 3)]))
    grid = lattice_grid()
    got = assess_pixels(context_for(), grid, raster_cells(grid, np.full((ROWS, COLS), 0.06)),
                        [(3, 3)])[0]
    assert got == {"robust_z": None, "median_ndci": None, "mad": None, "n_dates": None,
                   "level": None, "reason": "no_baseline",
                   "visible_bands_dn": dict(zip(("red", "green", "blue"), VISIBLE_DEFAULT))}


def test_reason_buckets_partition_the_measured_cells(cell_root):
    rng = np.random.default_rng(4)
    overrides = {}
    for r in range(ROWS):
        for c in range(COLS):
            roll = rng.random()
            if roll < 0.03:
                overrides[(r, c)] = (0.02, 0.01, FLOOR - 5)
            elif roll < 0.05:
                overrides[(r, c)] = (0.02, 0.0, 45)
    missing = [(r, c) for r in range(ROWS) for c in range(COLS) if rng.random() < 0.05]
    write_cell_artefact(cell_root, baseline_stats(overrides=overrides, missing=missing))
    grid = lattice_grid()
    field = rng.uniform(-0.05, 0.12, size=(ROWS, COLS))
    field[rng.random((ROWS, COLS)) < 0.02] = 1.7
    choices = [NEW_MS, ms_on(HISTORY_END), ms_on("2026-08-25"), ms_on("2026-09-20")]
    dates = {(r, c): choices[int(rng.integers(0, 4))] for r in range(ROWS) for c in range(COLS)}
    dark = (12.0, 350.0, 300.0)
    visible = {(r, c): dark for r in range(ROWS) for c in range(COLS) if rng.random() < 0.04}
    cells = raster_cells(grid, field, dates=dates, visible=visible)
    result = assess_all(cells, context_for())
    counts = cell_anomaly.counts(result)
    reasons = [counts[name] for name in cell_anomaly.REASON_ORDER]
    assert counts["measured"] == ROWS * COLS
    assert counts["assessable"] + sum(reasons) == counts["measured"]
    assert all(count > 0 for count in reasons), counts
    assert counts["assessable"] > 0
    # Each cell is in exactly one bucket and the bucket is its first failing rule.
    codes = result["reason"]
    assert set(np.unique(codes)) <= set(range(len(cell_anomaly.REASON_ORDER) + 1))
    assert counts["watch"] == int(np.count_nonzero((codes == 0) & (result["level"] == 2)))
    assert counts["high"] == int(np.count_nonzero((codes == 0) & (result["level"] == 3)))
    assert counts["watch"] + counts["high"] <= counts["assessable"]


def test_the_vectorised_z_is_what_assess_cells_classified(cell_root):
    """The reported z is the float64 value detection's assess_cells
    classified (its float32 output is that value cast), and the level is
    what classify_robust_z says of it."""
    write_cell_artefact(cell_root, baseline_stats())
    grid = lattice_grid()
    rng = np.random.default_rng(9)
    cells = raster_cells(grid, rng.uniform(-0.05, 0.12, size=(ROWS, COLS)))
    result = assess_all(cells, context_for())
    ok = result["reason"] == 0
    assert ok.all()
    z32, level, _ = logic.assess_cells(cells["ndci"], result["median_ndci"], result["mad"],
                                       result["n_dates"])
    np.testing.assert_array_equal(result["robust_z"].astype(np.float32), z32)
    np.testing.assert_array_equal(result["level"], level)
    for z, code in zip(result["robust_z"], result["level"]):
        assert logic.LEVEL_CODES[int(code)] == bridge.baseline_logic.classify_robust_z(float(z), {
            "minimum_independent_dates": FLOOR, "max_observation_age_days": 14,
            "mad_scale": 1.4826, "watch_at_z": 2.0, "high_at_z": 3.0})


# --------------------------------------------------------------------------
# resolve(): when an anomaly can be computed at all
# --------------------------------------------------------------------------


def test_resolve_mode_off_touches_no_file(tmp_path, monkeypatch):
    isolate_baselines(tmp_path / "baselines", monkeypatch, mode="off")

    def must_not_be_called(*_a, **_k):
        raise AssertionError("mode off must not look at the artefact")

    monkeypatch.setattr(baseline_store, "latest_artifact_path", must_not_be_called)
    resolved = cell_anomaly.resolve(scientific_status.baseline_status(), DATE_USED)
    assert resolved == cell_anomaly.Unavailable(reason="mode_off", cause=None, season_key=None)


def test_resolve_names_why_there_is_no_cell_baseline(cell_root, monkeypatch):
    status = scientific_status.baseline_status()
    assert cell_anomaly.resolve(status, DATE_USED) == cell_anomaly.Unavailable(
        reason="no_cell_baseline", cause="no_artifact", season_key=SEASON)

    path_manifest = write_cell_artefact(cell_root, baseline_stats())
    version_dir = cell_root / path_manifest["baseline_version"]
    (version_dir / "cells_m05.npz").unlink()
    baseline_store.clear_cell_cache()
    resolved = cell_anomaly.resolve(scientific_status.baseline_status(), DATE_USED)
    assert resolved.reason == "no_cell_baseline"
    assert resolved.cause == "missing_cells_file:cells_m05.npz"

    monkeypatch.setattr(config, "RASTER_SCAN_SCALE_M", 100)
    resolved = cell_anomaly.resolve(scientific_status.baseline_status(), DATE_USED)
    assert resolved.reason == "invalid:cell_signature_mismatch"


def test_resolve_refuses_an_invalid_level_a_baseline(cell_root, monkeypatch):
    write_cell_artefact(cell_root, baseline_stats())
    monkeypatch.setattr(bridge, "preprocessing_params", lambda: {"changed": True})
    resolved = cell_anomaly.resolve(scientific_status.baseline_status(), DATE_USED)
    assert resolved.reason == "invalid:signature_mismatch"


def test_resolve_refuses_an_unusable_run_date(cell_root):
    write_cell_artefact(cell_root, baseline_stats())
    for bad in (None, "", "2026-13-01", "not a date"):
        resolved = cell_anomaly.resolve(scientific_status.baseline_status(), bad)
        assert resolved.reason == "run_date_unusable"


def test_resolve_refuses_a_cell_baseline_of_another_version(cell_root, monkeypatch):
    """Two reads in one request can straddle a rebuild; a status of one
    version is never paired with cells of another."""
    write_cell_artefact(cell_root, baseline_stats())
    status = dict(scientific_status.baseline_status(), version="TEST-20990101-deadbeef")
    resolved = cell_anomaly.resolve(status, DATE_USED)
    assert resolved.reason == "no_cell_baseline"
    assert resolved.cause == "version_mismatch"


def test_season_is_the_month_of_date_used(cell_root):
    write_cell_artefact(cell_root, baseline_stats())
    assert context_for("2026-09-14").season_key == "m09+-1"
    assert context_for("2026-01-03").season_key == "m01+-1"
    assert context_for("2026-01-03").cells.season_key == "m01+-1"


# --------------------------------------------------------------------------
# GET /raster-scan/pixel: the anomaly block
# --------------------------------------------------------------------------

# Every key /raster-scan/pixel returned before the anomaly block existed.
_PIXEL_KEYS_BEFORE = {
    "disclaimer", "state", "meaning", "run_id", "date_used", "scale_m", "query_lat",
    "query_lng", "cell_lat", "cell_lng", "pixel_centre_lat", "pixel_centre_lng",
    "pixel_row", "pixel_col", "index_values", "unreadable_bands", "date_ms",
    "acquired_date", "acquired_at",
}
# + visible_bands_dn (fix round 2, 2026-10-10: added deliberately).
_ANOMALY_KEYS = {"robust_z", "median_ndci", "mad", "n_dates", "level", "reason",
                 "baseline_version", "season_key", "visible_bands_dn"}

# An endpoint fixture: a block of lattice cells inside the real study
# polygon (13.10 N, 100.30 E), dated 2026-09-04, the run asking about
# 2026-09-06 (season m09+-1). Pixel (r, c) of the block is key
# (EP_ROW0 - r, EP_COL0 + c).
EP_ROW0, EP_COL0 = 7291, 55826
EP_ROWS = EP_COLS = 12
EP_DATE_USED = "2026-09-06"


def endpoint_cells(peaks: dict, *, base: float = 0.02, dates=None) -> dict:
    """Lattice-aligned stored cells (0.1 cell off centre) with NDCI ``base``
    except ``peaks`` = {(r, c): ndci}."""
    dates = dates or {}
    out = {"lat": [], "lng": [], DATE_BAND: [], **{b: [] for b in INDEX_BANDS}}
    for r in range(EP_ROWS):
        for c in range(EP_COLS):
            lat, lng = lattice_centre((EP_ROW0 - r, EP_COL0 + c))
            value = peaks.get((r, c), base)
            out["lat"].append(lat + 0.1 * D)
            out["lng"].append(lng + 0.1 * D)
            out[DATE_BAND].append(dates.get((r, c), NEW_MS))
            out["ndci"].append(value)
            out["bda2"].append(1.0 + value)
            out["bda3"].append(0.3)
            out["b2_b3"].append(0.8)
    return {
        "lat": np.asarray(out["lat"]), "lng": np.asarray(out["lng"]),
        DATE_BAND: np.asarray(out[DATE_BAND], dtype=np.int64),
        **{b: np.asarray(out[b], dtype=np.float32) for b in INDEX_BANDS},
        **{b: np.full(len(out["lat"]), 500.0, dtype=np.float32)
           for b in bridge.RASTER_TRUE_COLOR_BANDS},
    }


def endpoint_stats(overrides=None, missing=()) -> dict:
    overrides = overrides or {}
    missing = set(missing)
    return {
        (EP_ROW0 - r, EP_COL0 + c): overrides.get((r, c), DEFAULT_STATS)
        for r in range(EP_ROWS) for c in range(EP_COLS) if (r, c) not in missing
    }


def clear_runs() -> None:
    with SessionLocal() as db:
        db.execute(delete(RasterScanRun))
        db.commit()


def store_run(tmp_path, cells, *, date_used: str = EP_DATE_USED, hint: str = "anom") -> int:
    """A rendered run whose cells are on disk, as a real scan leaves it."""
    png = tmp_path / f"{hint}-placeholder.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n")
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        run = RasterScanRun(
            started_at=now, completed_at=now, status="ok", date_used=date_used,
            scale_m=SCALE_M, retention_days=30, cell_count=int(cells["lat"].size),
            scene_count=1, oldest_scene_date="2026-09-04", newest_scene_date="2026-09-04",
            overlay={"status": "ok", "assets": {"ndci": {"path": str(png)}}},
        )
        db.add(run)
        db.commit()
        run.blob_path = storage.write_cells(run.id, cells, root=tmp_path)["path"]
        db.commit()
        render.render_and_store(db, run, root=tmp_path)
        db.refresh(run)
        return run.id


def test_pixel_mode_off_keeps_every_key_and_value_and_adds_a_null_anomaly(client, tmp_path,
                                                                        monkeypatch):
    isolate_baselines(tmp_path / "baselines", monkeypatch, mode="off")
    clear_runs()
    run_id = store_run(tmp_path, endpoint_cells({(3, 3): 0.09}))
    lat, lng = lattice_centre((EP_ROW0 - 3, EP_COL0 + 3))
    body = client.get("/raster-scan/pixel", params={"lat": lat, "lng": lng}).json()
    assert set(body) == _PIXEL_KEYS_BEFORE | {"anomaly"}
    assert body["anomaly"] is None
    assert body["disclaimer"] == DISCLAIMER_TEXT
    assert body["run_id"] == run_id and body["state"] == "reading"
    assert body["index_values"]["ndci"] == f32(0.09)
    assert body["date_ms"] == NEW_MS and body["date_used"] == EP_DATE_USED


def test_pixel_anomaly_block_for_a_reading_cell(client, tmp_path, cell_root):
    write_cell_artefact(cell_root, endpoint_stats(overrides={(3, 3): (0.025, 0.011, 44)}))
    clear_runs()
    store_run(tmp_path, endpoint_cells({(3, 3): 0.09}))
    lat, lng = lattice_centre((EP_ROW0 - 3, EP_COL0 + 3))
    body = client.get("/raster-scan/pixel", params={"lat": lat, "lng": lng}).json()
    assert set(body) == _PIXEL_KEYS_BEFORE | {"anomaly"}
    anomaly = body["anomaly"]
    assert set(anomaly) == _ANOMALY_KEYS
    assert anomaly["robust_z"] == expected_z(0.09, 0.025, 0.011)
    assert anomaly["level"] == "high" and anomaly["reason"] is None
    assert (anomaly["median_ndci"], anomaly["mad"], anomaly["n_dates"]) == (
        f32(0.025), f32(0.011), 44)
    assert anomaly["season_key"] == "m09+-1"
    assert anomaly["baseline_version"] == logic.version_for(
        BUILT_ON, logic.preprocessing_signature(bridge.preprocessing_params()))
    assert body["disclaimer"] == DISCLAIMER_TEXT_TEST_BASELINE


def test_pixel_anomaly_block_states_why_a_cell_is_not_assessed(client, tmp_path, cell_root):
    write_cell_artefact(cell_root, endpoint_stats(missing=[(2, 2)]))
    clear_runs()
    store_run(tmp_path, endpoint_cells({}, dates={(4, 4): ms_on(HISTORY_END)}))
    for (r, c), reason in {(2, 2): "no_baseline", (4, 4): "not_after_history"}.items():
        lat, lng = lattice_centre((EP_ROW0 - r, EP_COL0 + c))
        anomaly = client.get("/raster-scan/pixel", params={"lat": lat, "lng": lng}).json()["anomaly"]
        assert anomaly["reason"] == reason
        assert anomaly["robust_z"] is None and anomaly["level"] is None


def test_pixel_anomaly_is_null_for_an_unmeasured_or_outside_coordinate(client, tmp_path,
                                                                     cell_root):
    write_cell_artefact(cell_root, endpoint_stats())
    clear_runs()
    store_run(tmp_path, endpoint_cells({}))
    outside = client.get("/raster-scan/pixel", params={"lat": 10.0, "lng": 99.0}).json()
    assert outside["state"] == "outside_study_area" and outside["anomaly"] is None
    lat, lng = lattice_centre((EP_ROW0 + 6, EP_COL0 + 3))  # inside, no cell stored there
    unmeasured = client.get("/raster-scan/pixel", params={"lat": lat, "lng": lng}).json()
    assert unmeasured["state"] == "not_measured" and unmeasured["anomaly"] is None


def test_pixel_anomaly_is_null_and_disclaimer_standard_without_a_cell_baseline(
        client, tmp_path, cell_root):
    clear_runs()
    store_run(tmp_path, endpoint_cells({(3, 3): 0.09}))
    lat, lng = lattice_centre((EP_ROW0 - 3, EP_COL0 + 3))
    response = client.get("/raster-scan/pixel", params={"lat": lat, "lng": lng})
    assert response.status_code == 200
    assert response.json()["anomaly"] is None
    assert response.json()["disclaimer"] == DISCLAIMER_TEXT
    assert response.json()["index_values"]["ndci"] == f32(0.09)


def test_pixel_reports_a_degenerate_reading_as_stored_but_never_assesses_it(
        client, tmp_path, cell_root):
    write_cell_artefact(cell_root, endpoint_stats())
    clear_runs()
    store_run(tmp_path, endpoint_cells({(5, 5): 1.0}))
    lat, lng = lattice_centre((EP_ROW0 - 5, EP_COL0 + 5))
    body = client.get("/raster-scan/pixel", params={"lat": lat, "lng": lng}).json()
    assert body["state"] == "reading" and body["index_values"]["ndci"] == 1.0
    assert body["anomaly"]["reason"] == "invalid"
    assert body["anomaly"]["robust_z"] is None and body["anomaly"]["level"] is None


def test_pixel_reports_low_signal_for_a_near_black_cell(client, tmp_path, cell_root):
    write_cell_artefact(cell_root, endpoint_stats())
    clear_runs()
    cells = endpoint_cells({(6, 6): 0.97})
    position = 6 * EP_COLS + 6
    for band, dn in zip(TRUE_COLOR, (1.0, 20.0, 27.0)):
        cells[band][position] = dn
    store_run(tmp_path, cells)
    lat, lng = lattice_centre((EP_ROW0 - 6, EP_COL0 + 6))
    anomaly = client.get("/raster-scan/pixel", params={"lat": lat, "lng": lng}).json()["anomaly"]
    assert anomaly["reason"] == "low_signal" and anomaly["robust_z"] is None
    assert anomaly["visible_bands_dn"] == {"red": 1.0, "green": 20.0, "blue": 27.0}


def test_pixel_anomaly_is_null_when_the_blob_has_no_visible_bands(client, tmp_path, cell_root):
    """An unscreened cell is never scored; every reading field is unchanged."""
    write_cell_artefact(cell_root, endpoint_stats())
    clear_runs()
    cells = {k: v for k, v in endpoint_cells({(3, 3): 0.09}).items() if k not in TRUE_COLOR}
    store_run(tmp_path, cells)
    lat, lng = lattice_centre((EP_ROW0 - 3, EP_COL0 + 3))
    body = client.get("/raster-scan/pixel", params={"lat": lat, "lng": lng}).json()
    assert body["state"] == "reading" and body["index_values"]["ndci"] == f32(0.09)
    assert body["anomaly"] is None


def test_pixel_never_500s_on_a_broken_cell_baseline(client, tmp_path, cell_root):
    manifest = write_cell_artefact(cell_root, endpoint_stats())
    (cell_root / manifest["baseline_version"] / "cells_m09.npz").write_bytes(b"garbage")
    clear_runs()
    store_run(tmp_path, endpoint_cells({}))
    lat, lng = lattice_centre((EP_ROW0 - 3, EP_COL0 + 3))
    response = client.get("/raster-scan/pixel", params={"lat": lat, "lng": lng})
    assert response.status_code == 200
    assert response.json()["anomaly"] is None


def test_pixel_anomaly_equals_the_highlights_pin_for_the_same_cell(client, tmp_path, cell_root):
    peaks = {(1, 1): 0.11, (1, 10): 0.07, (9, 2): 0.065, (10, 10): 0.09}
    write_cell_artefact(cell_root, endpoint_stats(overrides={(10, 10): (0.03, 0.009, 52)}))
    clear_runs()
    run_id = store_run(tmp_path, endpoint_cells(peaks))
    highlights = client.get("/raster-scan/highlights",
                            params={"mode": "anomaly", "min_separation_m": 1000}).json()
    assert highlights["mode"] == "anomaly"
    assert len(highlights["pins"]) == 4
    for pin in highlights["pins"]:
        body = client.get("/raster-scan/pixel", params={
            "lat": pin["cell_lat"], "lng": pin["cell_lng"], "run_id": run_id}).json()
        anomaly = body["anomaly"]
        assert anomaly["robust_z"] == pin["robust_z"] == pin["metric_value"]
        assert anomaly["median_ndci"] == pin["median_ndci"]
        assert anomaly["mad"] == pin["mad"]
        assert anomaly["n_dates"] == pin["n_dates"]
        assert anomaly["level"] == pin["anomaly_level"]
        assert anomaly["reason"] is None
        assert anomaly["visible_bands_dn"] == pin["visible_bands_dn"] == {
            "red": 500.0, "green": 500.0, "blue": 500.0}
        assert anomaly["baseline_version"] == highlights["baseline"]["version"]
        assert anomaly["season_key"] == highlights["baseline"]["level_b"]["season_key"]
        assert body["index_values"] == pin["index_values"]


def test_pixel_handler_stays_sync():
    import inspect

    from src.routers import raster_scan as raster_scan_router

    assert not inspect.iscoroutinefunction(raster_scan_router.get_raster_pixel)


def test_cell_anomaly_module_states_source_and_limits():
    doc = cell_anomaly.__doc__ or ""
    for phrase in ("Data source", "no GEE", "TEST", "not a risk level", "own",
                   "sediment", "history_end", "14 days"):
        assert phrase in doc, phrase


def test_counts_json_is_plain_numbers(cell_root):
    write_cell_artefact(cell_root, baseline_stats())
    grid = lattice_grid()
    cells = raster_cells(grid, np.full((ROWS, COLS), 0.05))
    result = assess_all(cells, context_for())
    counts = cell_anomaly.counts(result)
    assert all(type(v) is int for k, v in counts.items() if k != "flagged_share")
    assert type(counts["flagged_share"]) is float
    assert json.loads(json.dumps(counts))["measured"] == ROWS * COLS
