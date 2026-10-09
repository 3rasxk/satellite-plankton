"""
Highlight pins: the highest-NDCI measured cells of one stored raster.

Data source: the stored cells of ONE raster scan run -- the `.npz` blob
`src/raster_scan/storage.py` wrote from `data-pipeline/src/raster.py`'s
whole-polygon Sentinel-2 composite, read back exactly as
`/raster-scan/pixel` reads it: no GEE call, no network, no database
write, and no value re-derived. Every number on a pin is a stored
number, widened from float32 and otherwise untouched. Asking twice gives
the same pins, because the same blob gives the same ranking (dashboard
spec §4.6: "pins are recomputed from the stored run").

What a pin is
-------------
A RANKING by value inside one scan. Pin 1 is the measured cell with the
highest NDCI in this run, after spatial de-duplication; pin k is the k-th.
That is the whole claim. It is not a risk level, not an anomaly and not a
detection: there is no baseline behind it and no threshold in it, so a
run of uniformly clear water still has a "highest NDCI" and still gets
pins. `risk_tier` exists on every pin only so a future, separately
approved gate can fill it without changing the contract; nothing in this
module or its router can set it to anything but None (a test greps for
that).

The rules, in order
-------------------
1. **Cohort = the cells the overlay paints**, i.e. exactly the cells
   `/raster-scan/pixel` would report as state "reading":
     * date-valid by `bridge.valid_cell_mask` -- the DATE decides, never an
       index value, because GEE's NPY export writes 0.0 into every band of
       a masked pixel and 0.0 is also an ordinary NDCI (the 0.0 trap, see
       `pixel.py`). A masked cell's 0.0 never ranks; a dated 0.0 does;
     * finite NDCI (a NaN/inf is drawn transparent);
     * pixel centre inside the study polygon (the renderer's test);
     * one cell per overlay pixel: where two stored cells land in one
       pixel, the LAST one, which is the one numpy painted and the one a
       click reports.
   So `cohort_size` is the number of measured overlay pixels -- the
   renderer's `measured_pixels` -- and a pin always answers a click on its
   own square with the same numbers.
2. **Order:** metric descending, then lower overlay row (further north),
   then lower column (further west). Rows/columns come from the run's own
   recorded grid (`OverlayGrid.cell_indices`), so the order is total and
   does not depend on the order cells were stored in.
3. **De-duplication:** greedy non-maximum suppression. Walking down that
   order, a cell is skipped if its great-circle (haversine) distance to an
   already-selected pin is `< min_separation_m`; distance is measured
   between the cells' own observation coordinates (`cell_lat`/`cell_lng`).
   So five adjacent cells cannot fill the list.
4. **percentile** = share of the cohort with a STRICTLY lower metric x 100.
   Ties share a percentile; the top cell of a 4-cell cohort is 75.0. It is
   computed over the FULL cohort, degenerate cells (rule 7) included.
5. **edge_of_no_data** = true when any of the 8 neighbouring overlay
   pixels whose centre lies INSIDE the study polygon carries no reading
   (unmeasured: cloud, land mask, no pass, masked export, or non-finite
   NDCI -- the stored raster cannot separate them). Neighbours whose
   centre is outside the polygon do not count: they were never looked at,
   so their emptiness is not missing data. That includes positions beyond
   the grid's edge, tested with the same centre formula one pixel further
   out. A fact about the data around the pin, not a quality score.
6. **Fewer than n separable cells** -> fewer pins and
   `reason = "only k separable measured cells"`; an empty cohort ->
   `pins == []` and `reason = "no measured cells"`.
7. **Data-quality screens: screened cells never pin** (rules and their
   rationale in `cell_anomaly`'s docstring, "Data-quality screens").
   * Degenerate NDCI: exactly +/-1 (|ndci| >= 1 - 1e-6) means a zero band,
     not a water-colour value (run 5: 90 cells at 1.0 topped every list)
     -> counted in `excluded_degenerate`.
   * Low visible signal: any stored visible band (B4, B3, B2) below
     `cell_anomaly.MIN_VISIBLE_DN` = 50 DN -- a DEVELOPER-CHOSEN screening
     threshold, not validated against field data; near-black pixels make
     NDCI explode (run 6: the top anomaly pins had red 1-13 DN) -> counted
     in `excluded_low_signal` (cells that are not also degenerate).
   Screened cells stay in the cohort -- the map paints them, a click
   reports them -- so `cohort_size` and percentiles are unchanged; they are
   skipped as pins and so cannot suppress a neighbour. A blob without the
   visible bands cannot be screened: NDCI mode ranks as before with
   `excluded_low_signal = None` and a `quality_note`; anomaly mode refuses
   (`cell_anomaly.VisibleBandsMissing`). Every pin carries the stored
   `visible_bands_dn` (None without the bands) so a reader can see the
   signal behind its value. Applies in both modes; in anomaly mode the
   screened cells are the `invalid` / `low_signal` buckets.

Limitations -- read before quoting a pin
-----------------------------------------
* High NDCI is not a bloom. It can also come from suspended sediment
  (river mouths), shallow bottom, sun glint or cloud edges; it does not
  by itself identify a bloom or a species. Nothing here separates those.
* Percentile and rank are relative to THIS run's cohort only. They are not
  comparable across runs (a different cloud pattern is a different
  cohort) and say nothing about the water outside the measured cells.
* A cell is one nearest-neighbour-sampled native pixel, not an area
  average (`pixel.py`); a bloom smaller than the sampling interval is hit
  or missed depending on where the sample landed, and small or dispersed
  blooms may be missed entirely.
* Each pin carries its own acquisition date; neighbouring pins routinely
  come from different passes of a most-recent-wins mosaic.
* No baseline exists for spectral indices (CLAUDE.md §0/§1), so there is
  no "high" in an absolute sense here -- only "highest in this scan".

Anomaly mode (`rank_anomaly_cells`, BASELINE_MODE=test only)
------------------------------------------------------------
A second, separately labelled kind of pin: a measured cell whose NDCI is
at least 2 robust z ABOVE that same cell's own TEST seasonal baseline
(Level B), assessed by `cell_anomaly.assess` with detection's statistic.
Same cohort, NMS, edge rule and tie-break discipline as above; the order
is z (then NDCI, row, column), only assessable cells at watch or high can
be pins, and the result carries `counts` saying how many measured cells
were assessable and why the rest were not, so "no pins" can be told apart
from "nothing assessed". It is a statistical anomaly against one cell's
own clear-sky record -- uncalibrated, not a bloom detection and not a risk
level; the same sediment / shallow-bottom / glint / cloud-edge caveats
apply. `risk_tier` stays None in both modes.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from .. import _detection as bridge
from .._study_area import STUDY_AREA_POLYGON_LATLNG
from ..db_models import RasterScanRun
from . import cell_anomaly, render, storage
from .pixel import RasterCellsUnavailableError, _cell_date_fields, grid_for_run
from .render import OverlayGrid

# Metrics a pin may be ranked by. NDCI only: it is the band the overlay
# draws, so "highest" refers to the colour a viewer is looking at. A later
# anomaly mode ranks by a different, baseline-derived quantity and is
# added explicitly, not by accepting any stored band name.
RANKABLE_METRICS: tuple[str, ...] = ("ndci",)

# Mean Earth radius (IUGG), the value data-pipeline's own haversine
# (`rainfall.haversine_km`, 6371.0088 km) uses, so "3 km" means the same
# distance everywhere in this project.
EARTH_RADIUS_M = 6_371_008.8

NO_MEASURED_CELLS = "no measured cells"
FEWER_SEPARABLE_TEMPLATE = "only {k} separable measured cells"
NONE_ELIGIBLE_TEMPLATE = (
    "no measured cells eligible for pins (all {x} excluded by the data-quality screens: "
    "NDCI exactly +/-1, or a visible band below the minimum signal)"
)
NO_VISIBLE_BANDS_NOTE = (
    "this run's stored cells carry no visible bands (true_red/true_green/true_blue), so "
    "the low-signal screen could not run: pins are not screened for near-black pixels, "
    "whose NDCI is unreliable"
)

# The 8 neighbours, as (row, col) offsets.
_NEIGHBOUR_OFFSETS: tuple[tuple[int, int], ...] = tuple(
    (dr, dc) for dr in (-1, 0, 1) for dc in (-1, 0, 1) if (dr, dc) != (0, 0)
)


def haversine_m(lat1, lng1, lat2, lng2) -> np.ndarray:
    """Great-circle distance in metres, vectorised over numpy arrays."""
    phi1 = np.radians(np.asarray(lat1, dtype=np.float64))
    phi2 = np.radians(np.asarray(lat2, dtype=np.float64))
    d_phi = phi2 - phi1
    d_lambda = np.radians(np.asarray(lng2, dtype=np.float64) - np.asarray(lng1, dtype=np.float64))
    a = np.sin(d_phi / 2) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def _painted_cells(
    cells: dict, grid: OverlayGrid, polygon: tuple[tuple[float, float], ...]
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Storage indices, rows and cols of the cells that paint a pixel.

    The renderer's rule (`render.render_overlay`) and the click lookup's
    (`pixel.inspect_cell`): date-valid, finite NDCI, pixel centre inside
    the polygon, and the last stored cell of each pixel. Returned in
    storage order.
    """
    lat = np.asarray(cells["lat"], dtype=np.float64)
    lng = np.asarray(cells["lng"], dtype=np.float64)
    ndci = np.asarray(cells["ndci"], dtype=np.float64)
    dates = np.asarray(cells[bridge.RASTER_DATE_BAND])
    empty = np.zeros(0, dtype=np.int64)

    index = np.flatnonzero(bridge.valid_cell_mask(dates) & np.isfinite(ndci))
    if index.size == 0:
        return empty, empty, empty
    rows, cols = grid.cell_indices(lat[index], lng[index])
    centre_lats, centre_lngs = grid.pixel_centres()
    inside = render.points_in_polygon_mask(centre_lats[rows], centre_lngs[cols], polygon)
    index, rows, cols = index[inside], rows[inside], cols[inside]
    if index.size == 0:
        return empty, empty, empty

    # Last write wins per pixel: the first occurrence in the REVERSED
    # sequence is the last one in storage order.
    flat = rows * grid.cols + cols
    _, first_in_reversed = np.unique(flat[::-1], return_index=True)
    keep = np.sort(flat.size - 1 - first_in_reversed)
    return index[keep], rows[keep], cols[keep]


def _edge_of_no_data(
    row: int,
    col: int,
    painted: np.ndarray,
    grid: OverlayGrid,
    polygon: tuple[tuple[float, float], ...],
) -> bool:
    """Rule 5 of the module docstring: an in-polygon neighbour is unmeasured."""
    unpainted: list[tuple[int, int]] = []
    for dr, dc in _NEIGHBOUR_OFFSETS:
        r, c = row + dr, col + dc
        if 0 <= r < grid.rows and 0 <= c < grid.cols and painted[r, c]:
            continue
        unpainted.append((r, c))
    if not unpainted:
        return False
    rs = np.array([r for r, _ in unpainted], dtype=np.float64)
    cs = np.array([c for _, c in unpainted], dtype=np.float64)
    # `OverlayGrid.pixel_centres`' formula, evaluated one pixel past the
    # grid's edge where a neighbour lies off it.
    centre_lats = grid.north - (rs + 0.5) * grid.pixel_deg_lat
    centre_lngs = grid.west + (cs + 0.5) * grid.pixel_deg_lng
    return bool(render.points_in_polygon_mask(centre_lats, centre_lngs, polygon).any())


def _index_values(cells: dict, index: int) -> dict[str, float | None]:
    """The four stored indices of one cell; a non-finite one is None."""
    values: dict[str, float | None] = {}
    for band in bridge.RASTER_INDEX_BANDS:
        stored = cells[band][index]
        values[band] = float(stored) if np.isfinite(stored) else None
    return values


def rank_cells(
    cells: dict,
    *,
    grid: OverlayGrid,
    n: int,
    min_separation_m: float,
    metric: str = "ndci",
    polygon: tuple[tuple[float, float], ...] = STUDY_AREA_POLYGON_LATLNG,
) -> dict[str, Any]:
    """Rank one run's painted cells by `metric`. Pure: arrays in, dict out.

    Args:
        cells: `storage.read_cells`' return value.
        grid: the grid the run's overlay was drawn on (`pixel.grid_for_run`),
            so rows, columns and pixel centres are the picture's own.
        n: maximum number of pins (the router enforces 3..10).
        min_separation_m: NMS radius in metres; a candidate closer than
            this to an already-selected pin is skipped.
        metric: one of RANKABLE_METRICS.
        polygon: study-area boundary, as the renderer used it.

    Returns:
        {"cohort_size": int, "pins": [pin, ...], "reason": str | None,
        "excluded_degenerate": int, "excluded_low_signal": int | None,
        "quality_note": str | None}. Each pin: rank, cell_lat, cell_lng,
        pixel_centre_lat, pixel_centre_lng, index_values, percentile,
        date_ms, acquired_date, acquired_at, edge_of_no_data, metric_value,
        visible_bands_dn, risk_tier (always None). Screened cells (rule 7)
        are counted in `cohort_size` and in every percentile but never
        pinned; `excluded_low_signal` is None (and `quality_note` says why)
        when the blob stores no visible bands.

    Raises:
        ValueError: unknown metric, n < 1, or a negative separation.
    """
    if metric not in RANKABLE_METRICS:
        raise ValueError(f"cannot rank by {metric!r}; rankable metrics: {RANKABLE_METRICS}")
    _validate_arguments(n, min_separation_m)

    index, rows, cols = _painted_cells(cells, grid, polygon)
    values = np.asarray(cells[metric], dtype=np.float64)[index]
    finite = np.isfinite(values)
    index, rows, cols, values = index[finite], rows[finite], cols[finite], values[finite]

    visible = cell_anomaly.visible_dn(cells)
    quality_note = None if visible is not None else NO_VISIBLE_BANDS_NOTE
    cohort_size = int(index.size)
    if cohort_size == 0:
        return {"cohort_size": 0, "pins": [], "reason": NO_MEASURED_CELLS,
                "excluded_degenerate": 0,
                "excluded_low_signal": 0 if visible is not None else None,
                "quality_note": quality_note}

    # lexsort: the LAST key is primary. Metric descending, then row, then col.
    order = np.lexsort((cols, rows, -values))
    index, rows, cols, values = index[order], rows[order], cols[order], values[order]
    lat = np.asarray(cells["lat"], dtype=np.float64)[index]
    lng = np.asarray(cells["lng"], dtype=np.float64)[index]

    # Rule 7: a degenerate NDCI (a zero band) or a low visible signal stays
    # in the cohort -- the map paints it -- but can never be a pin, and never
    # suppresses one. The two counts are disjoint: degenerate first.
    degenerate = cell_anomaly.is_degenerate_ndci(np.asarray(cells["ndci"], dtype=np.float64)[index])
    if visible is not None:
        low_signal = cell_anomaly.is_low_signal(*(band[index] for band in visible)) & ~degenerate
        excluded_low_signal: int | None = int(np.count_nonzero(low_signal))
    else:  # the screen cannot run: rank as before and say so (quality_note)
        low_signal = np.zeros(cohort_size, dtype=bool)
        excluded_low_signal = None
    eligible = np.flatnonzero(~degenerate & ~low_signal)
    excluded = int(np.count_nonzero(degenerate))
    chosen = [int(eligible[p]) for p in _greedy_nms(lat[eligible], lng[eligible],
                                                    n, min_separation_m)]

    ascending = np.sort(values)
    painted = np.zeros((grid.rows, grid.cols), dtype=bool)
    painted[rows, cols] = True
    centre_lats, centre_lngs = grid.pixel_centres()
    dates = np.asarray(cells[bridge.RASTER_DATE_BAND])

    pins: list[dict[str, Any]] = []
    for rank, position in enumerate(chosen, start=1):
        stored = int(index[position])
        row, col = int(rows[position]), int(cols[position])
        value = float(values[position])
        strictly_lower = int(np.searchsorted(ascending, value, side="left"))
        pins.append({
            "rank": rank,
            "cell_lat": float(lat[position]),
            "cell_lng": float(lng[position]),
            "pixel_centre_lat": float(centre_lats[row]),
            "pixel_centre_lng": float(centre_lngs[col]),
            "index_values": _index_values(cells, stored),
            "percentile": strictly_lower / cohort_size * 100.0,
            "metric_value": value,
            "edge_of_no_data": _edge_of_no_data(row, col, painted, grid, polygon),
            "risk_tier": None,
            "visible_bands_dn": _visible_bands_dn(visible, stored),
            **_cell_date_fields(int(dates[stored])),
        })

    if len(pins) >= n:
        reason = None
    elif eligible.size == 0:
        reason = NONE_ELIGIBLE_TEMPLATE.format(x=cohort_size)
    else:
        reason = FEWER_SEPARABLE_TEMPLATE.format(k=len(pins))
    return {"cohort_size": cohort_size, "pins": pins, "reason": reason,
            "excluded_degenerate": excluded, "excluded_low_signal": excluded_low_signal,
            "quality_note": quality_note}


def _visible_bands_dn(visible, stored: int) -> dict[str, float | None] | None:
    """One cell's stored visible DN for a pin; None when the blob has none."""
    if visible is None:
        return None
    return cell_anomaly.visible_bands_dict(*(band[stored] for band in visible))


def _greedy_nms(lat: np.ndarray, lng: np.ndarray, n: int, min_separation_m: float) -> list[int]:
    """Positions picked by greedy NMS over candidates already in rank order.

    After each selection every candidate within the radius of it is struck
    out, so the next still-alive candidate in order is the highest-ranked
    cell at least `min_separation_m` from every pin so far.
    """
    count = int(lat.size)
    alive = np.ones(count, dtype=bool)
    chosen: list[int] = []
    start = 0
    while len(chosen) < n and start < count:
        offset = int(np.argmax(alive[start:]))
        position = start + offset
        if not alive[position]:
            break
        chosen.append(position)
        alive[position] = False
        alive &= ~(haversine_m(lat[position], lng[position], lat, lng) < min_separation_m)
        start = position + 1
    return chosen


# --------------------------------------------------------------------------
# Anomaly mode: pins that meet the condition against the Level B baseline
# --------------------------------------------------------------------------

# Reasons when an anomaly ranking has fewer than n pins. "No pins" must
# say whether nothing could be assessed or nothing met the condition.
NONE_ASSESSABLE_TEMPLATE = (
    "no measured cells are assessable against the TEST cell baseline "
    "(0 assessable of {m} measured)"
)
NONE_MET_TEMPLATE = "no cells meet the condition ({a} assessable of {m} measured)"
FEWER_MET_TEMPLATE = (
    "only {k} separable cells meet the condition ({a} assessable of {m} measured)"
)

_WATCH_CODE = bridge.baseline_logic.LEVEL_CODE["watch"]


def _validate_arguments(n: int, min_separation_m: float) -> None:
    if int(n) != n or n < 1:
        raise ValueError(f"n must be a positive integer, got {n!r}")
    if not np.isfinite(min_separation_m) or min_separation_m < 0:
        raise ValueError(f"min_separation_m must be >= 0, got {min_separation_m!r}")


def rank_anomaly_cells(
    cells: dict,
    *,
    grid: OverlayGrid,
    context: cell_anomaly.AnomalyContext,
    n: int,
    min_separation_m: float,
    polygon: tuple[tuple[float, float], ...] = STUDY_AREA_POLYGON_LATLNG,
) -> dict[str, Any]:
    """Pins where a measured cell meets the TEST anomaly condition. Pure.

    Cohort: exactly `rank_cells`' (the cells the overlay paints), each
    assessed by `cell_anomaly.assess` against its own season baseline.
    Candidates: assessable cells with level watch or high, i.e. robust
    z >= 2 -- positive anomalies only (higher NDCI than this cell's own
    seasonal record); a negative or normal z is never a pin. Order: z
    descending, then NDCI descending, then lower row, then lower column.
    De-duplication and `edge_of_no_data` are `rank_cells`' rules (the
    painted mask is every measured cell, not only the candidates).
    `percentile` is the share of the ASSESSABLE cells with a strictly lower
    z, x 100; `metric_value` is the pin's robust z.

    Returns:
        {"cohort_size", "pins", "reason", "counts", "excluded_degenerate",
        "excluded_low_signal", "quality_note" (None)} (degenerate cells are in
        `counts["invalid"]`, low-signal ones in `counts["low_signal"]`).
        Each pin: the ndci-mode
        fields plus robust_z, median_ndci, mad, n_dates, anomaly_level
        ("watch" | "high"); risk_tier always None. `counts` is
        `cell_anomaly.counts` (it partitions the cohort).

    Raises:
        ValueError: n < 1 or a negative separation.
        cell_anomaly.VisibleBandsMissing: the blob stores no visible bands,
            so the low-signal screen cannot run -- nothing is scored.
    """
    _validate_arguments(n, min_separation_m)
    visible = cell_anomaly.visible_dn(cells)
    if visible is None:
        raise cell_anomaly.VisibleBandsMissing(
            "the run's stored cells carry no visible bands; the low-signal screen cannot run")
    index, rows, cols = _painted_cells(cells, grid, polygon)
    dates = np.asarray(cells[bridge.RASTER_DATE_BAND])
    ndci = np.asarray(cells["ndci"], dtype=np.float64)[index]
    lat_all = np.asarray(cells["lat"], dtype=np.float64)
    lng_all = np.asarray(cells["lng"], dtype=np.float64)

    assessed = cell_anomaly.assess(
        ndci, lat_all[index], lng_all[index], dates[index].astype(np.int64), context,
        visible=tuple(band[index] for band in visible),
    )
    counts = cell_anomaly.counts(assessed)
    measured, assessable = counts["measured"], counts["assessable"]
    # Degenerate cells are `invalid` (never assessed, never pins); counted
    # here as well so both modes report the same exclusion.
    degenerate = cell_anomaly.is_degenerate_ndci(ndci)
    excluded = int(np.count_nonzero(degenerate))
    # Same definition as NDCI mode (low signal and not degenerate); the
    # `counts.low_signal` bucket can be smaller (an `invalid` cell for
    # another reason is counted there first).
    excluded_low = int(np.count_nonzero(
        cell_anomaly.is_low_signal(assessed["red"], assessed["green"], assessed["blue"])
        & ~degenerate))
    extra = {"excluded_degenerate": excluded, "excluded_low_signal": excluded_low,
             "quality_note": None}
    if measured == 0:
        return {"cohort_size": 0, "pins": [], "reason": NO_MEASURED_CELLS, "counts": counts,
                **extra}

    z = assessed["robust_z"]
    is_assessable = assessed["reason"] == 0
    candidate = np.flatnonzero(is_assessable & (assessed["level"] >= _WATCH_CODE))
    # lexsort: the LAST key is primary. z, NDCI descending; row, col ascending.
    order = candidate[np.lexsort((cols[candidate], rows[candidate],
                                  -ndci[candidate], -z[candidate]))]
    chosen = [int(order[p]) for p in _greedy_nms(lat_all[index[order]], lng_all[index[order]],
                                                 n, min_separation_m)]

    ascending = np.sort(z[is_assessable])
    painted = np.zeros((grid.rows, grid.cols), dtype=bool)
    painted[rows, cols] = True
    centre_lats, centre_lngs = grid.pixel_centres()

    pins: list[dict[str, Any]] = []
    for rank, position in enumerate(chosen, start=1):
        stored = int(index[position])
        row, col = int(rows[position]), int(cols[position])
        value = float(z[position])
        strictly_lower = int(np.searchsorted(ascending, value, side="left"))
        described = cell_anomaly.describe(assessed, position)
        pins.append({
            "rank": rank,
            "cell_lat": float(lat_all[stored]),
            "cell_lng": float(lng_all[stored]),
            "pixel_centre_lat": float(centre_lats[row]),
            "pixel_centre_lng": float(centre_lngs[col]),
            "index_values": _index_values(cells, stored),
            "percentile": strictly_lower / assessable * 100.0,
            "metric_value": value,
            "edge_of_no_data": _edge_of_no_data(row, col, painted, grid, polygon),
            "risk_tier": None,
            "robust_z": described["robust_z"],
            "median_ndci": described["median_ndci"],
            "mad": described["mad"],
            "n_dates": described["n_dates"],
            "anomaly_level": described["level"],
            "visible_bands_dn": described["visible_bands_dn"],
            **_cell_date_fields(int(dates[stored])),
        })

    if len(pins) >= n:
        reason = None
    elif assessable == 0:
        reason = NONE_ASSESSABLE_TEMPLATE.format(m=measured)
    elif not pins:
        reason = NONE_MET_TEMPLATE.format(a=assessable, m=measured)
    else:
        reason = FEWER_MET_TEMPLATE.format(k=len(pins), a=assessable, m=measured)
    return {"cohort_size": measured, "pins": pins, "reason": reason, "counts": counts,
            **extra}


def read_run_cells(run: RasterScanRun) -> dict:
    """The run's stored cells, failing exactly as `pixel.inspect_run` does."""
    if not run.blob_path:
        raise RasterCellsUnavailableError(
            f"raster scan {run.id} has no stored cells (blob_deleted_at="
            f"{run.blob_deleted_at}). Its overlay can still be shown, but no reading "
            "behind it can be quoted -- the cells it was drawn from are gone."
        )
    try:
        return storage.read_cells(run.blob_path)
    except FileNotFoundError as exc:
        raise RasterCellsUnavailableError(str(exc)) from exc


def rank_run(
    run: RasterScanRun,
    *,
    n: int,
    min_separation_m: float,
    metric: str = "ndci",
    polygon: tuple[tuple[float, float], ...] = STUDY_AREA_POLYGON_LATLNG,
) -> dict[str, Any]:
    """`rank_cells` for a run the caller already selected.

    Reads the run's blob and the grid its overlay was drawn on, the same
    way `pixel.inspect_run` does, and fails with the same message: the
    endpoint's 404 must read identically to `/raster-scan/pixel`'s (an
    endpoint test compares the two).

    Raises:
        RasterCellsUnavailableError: the run's blob is gone or its path is
            null -- the overlay may still be on screen, but no number
            behind it can be ranked.
    """
    cells = read_run_cells(run)
    return rank_cells(
        cells,
        grid=grid_for_run(run, cells),
        n=n,
        min_separation_m=min_separation_m,
        metric=metric,
        polygon=polygon,
    )


def rank_anomaly_run(
    run: RasterScanRun,
    *,
    context: cell_anomaly.AnomalyContext,
    n: int,
    min_separation_m: float,
    polygon: tuple[tuple[float, float], ...] = STUDY_AREA_POLYGON_LATLNG,
) -> dict[str, Any]:
    """`rank_anomaly_cells` for a run the caller selected; `rank_run`'s blob
    read and errors (`RasterCellsUnavailableError`)."""
    cells = read_run_cells(run)
    return rank_anomaly_cells(
        cells,
        grid=grid_for_run(run, cells),
        context=context,
        n=n,
        min_separation_m=min_separation_m,
        polygon=polygon,
    )
