"""
One cell of one stored raster, looked up by coordinate.

Data source: none of its own. This module reads the cells a raster scan
already stored (`src/raster_scan/storage.py`'s `.npz` blob, written from
`data-pipeline/src/raster.py`'s whole-polygon Sentinel-2 composite) and
answers "what does this raster hold at this coordinate?". It never calls
Earth Engine, never opens a network connection and never re-derives a
reading: the numbers it returns are the numbers on disk, widened from
their stored dtype and otherwise untouched. A click is a query about a
measurement that was already taken, not a new measurement -- if it were
live, two people clicking the same pixel a minute apart could get
different answers from the same picture.

What a click can and cannot be told
-----------------------------------
The overlay draws three states (`src/raster_scan/render.py`), and this
module answers in the same three, because a reader who can see a
difference on the map must be able to get that difference back in words:

  "reading"             a stored cell covers this pixel -- its four index
                        values and its own acquisition date.
  "not_measured"        inside the study polygon, no stored cell here.
  "outside_study_area"  outside the polygon; nothing was ever looked at.

`not_measured` is deliberately ONE state and not three. A cell can be
missing because cloud covered it, because the JRC water mask calls it
land, or because no scene in the window passed over it -- and the stored
blob keeps only the cells that survived, so it holds no evidence that
separates those. Reporting "land" for a pixel that was merely cloudy
would be inventing a distinction the data cannot support, so the three
collapse into one honest label, exactly as they do in the picture.
`outside_study_area` IS distinguishable -- it is decided by the polygon,
not by the data -- and stays separate.

The 0.0 trap, which is the whole reason this module has a validity rule
--------------------------------------------------------------------
GEE's NPY export writes 0 into every band of a masked pixel. NDCI 0.0 is
also a perfectly ordinary reading -- water with equal reflectance in B4
and B5. So "is this cell real?" can never be asked of an index value: the
test would silently convert "we could not see here" into "we looked and
measured zero", which is this project's cardinal overclaim, and would
also throw away the genuine 0.0 readings. It is the DATE band that
decides whether the stored zero is a masked export, and the test is
`date_ms > 0` -- a real Sentinel-2 acquisition
is ~1.79e12 ms and can never be 0. That rule is not restated here: it is
imported as `bridge.valid_cell_mask` from the module that filters the
raster on the way in (`data-pipeline/src/raster.py`), so a cell dropped
at read time and a click reported as unmeasured are decided by one line
of code, not two that happen to agree today.

That date rule is applied here to whatever is on disk. The visible NDCI
must also be finite, matching `render_overlay`: a date-valid NaN or
infinity is transparent and therefore remains `not_measured` on click.
Secondary index arithmetic may still be unreadable for an otherwise valid
NDCI cell; those values are returned as null and named in
`unreadable_bands`.

Limitations -- read before quoting a number from this
-----------------------------------------------------
* **A cell is one nearest-neighbour-sampled native pixel, not an area
  average** (`data-pipeline/src/raster.py`, "Resolution"). It is drawn as
  a filled square of the sampling interval, so a click anywhere in that
  square returns the same single 10 m observation. The value describes
  the pixel the satellite sampled, not the whole square, and `cell_lat`/
  `cell_lng` -- the sample's own coordinate -- are returned next to the
  square's centre precisely so the two are never confused.
* **The date is the cell's own, and neighbouring cells routinely differ.**
  The composite is most-recent-wins per pixel, so a run's
  `oldest_scene_date`/`newest_scene_date` span several days and no single
  date describes the picture. Every reading here carries the acquisition
  that actually supplied it.
* **Readings, never verdicts.** Four index values and a date. No anomaly
  statistic, no risk level, no classification -- no valid spectral-index
  baseline exists in this project (CLAUDE.md §0/§1). Nothing here scores
  or ranks a cell, and a high NDCI is a high reading, not "a bloom".
* **Detection is at pixel resolution**, water-colour signatures only,
  never individual organisms; a bloom smaller than the sampling interval
  is hit or missed depending on where the sample landed.

Cost: one blob read per call, uncached. A 200 m raster is ~9 MB
compressed, so a click costs a decompress plus one vectorised pass over
~50,000 cells. Deliberately not cached -- a cache keyed on anything but
the file's own identity is a staleness bug waiting for the day two runs
are served in one session, and the read is fast enough that buying that
risk would be a bad trade.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import numpy as np

from .. import _detection as bridge
from .._study_area import STUDY_AREA_POLYGON_LATLNG
from ..db_models import RasterScanRun
from . import render, storage
from .render import OverlayGrid

logger = logging.getLogger("backend.raster_scan.pixel")

# The three answers, matching the three states the overlay paints. Named
# rather than spelled inline so the router's schema and the tests refer to
# the same strings the renderer's legend describes.
STATE_READING = "reading"
STATE_NOT_MEASURED = "not_measured"
STATE_OUTSIDE = "outside_study_area"

# What each state means, in the words the legend already uses. Travels
# with the answer for the same reason the legend travels with the picture
# (`render.write_overlay_assets`): a caption written separately from the
# thing it captions is free to drift away from it.
STATE_MEANING: dict[str, str] = {
    STATE_READING: (
        "index readings at this cell, from the acquisition named by this cell's own "
        "date -- a measurement, not a score: no valid spectral-index baseline exists, "
        "so nothing here classifies the water"
    ),
    STATE_NOT_MEASURED: (
        "inside the study area, no usable reading here -- cloud, land-masked, or no "
        "scene covered it. NOT a low reading, and not a value of zero: this raster "
        "holds no observation at this coordinate."
    ),
    STATE_OUTSIDE: (
        "outside the study area -- nothing was looked at here, so there is nothing "
        "to report"
    ),
}


class RasterCellsUnavailableError(RuntimeError):
    """The run whose overlay is on screen has no cells to read.

    Retention removes the blob and the PNGs together, so this normally
    cannot happen; when it does (a blob removed by something other than
    retention) the honest answer is that the picture can still be shown
    but no number behind it can be quoted. Raised rather than returning
    `not_measured`, which would say the satellite saw nothing when in
    fact this server can no longer see what the satellite saw."""


def _cell_date_fields(date_ms: int) -> dict[str, Any]:
    """The cell's own acquisition timestamp, as the int and as dates.

    The integer is carried through untouched and is the authoritative
    field: it is what `raster.py` matched against the composite's real
    `system:time_start` values, and the only form that can still be
    matched back to a scene. The strings are conveniences derived from
    it, never the other way round.
    """
    moment = datetime.fromtimestamp(date_ms / 1000, tz=timezone.utc)
    return {
        "date_ms": int(date_ms),
        "acquired_date": moment.date().isoformat(),
        "acquired_at": moment.isoformat().replace("+00:00", "Z"),
    }


def inspect_cell(
    cells: dict,
    lat: float,
    lng: float,
    grid: OverlayGrid,
    polygon: tuple[tuple[float, float], ...] = STUDY_AREA_POLYGON_LATLNG,
) -> dict[str, Any]:
    """What this raster holds at one coordinate. Pure: arrays in, dict out.

    The lookup is the exact inverse of the paint. `grid.locate()` uses the
    same origin and the same `floor()` as the `grid.cell_indices()` that
    placed every cell in the image, so the pixel this resolves to is the
    pixel whose colour is under the cursor. Where two stored cells landed
    in one pixel, the LAST of them answers -- which is what numpy's
    `rgba[rows, cols] = ...` did when the overlay was drawn, so the number
    reported is the one that painted the square rather than the one it
    covered over.

    Order of decision matches the renderer: the pixel centre must first be
    inside the study polygon, then a date-valid stored cell may report a
    reading. Transparent gaps inside remain queryable as not measured.

    Args:
        cells: `storage.read_cells`' return value.
        lat, lng: the coordinate asked about.
        grid: the grid the overlay was drawn on -- reconstructed from what
            the run recorded, not rebuilt (see `grid_for_run`).
        polygon: study-area boundary, tested at the pixel's centre because
            that is where the renderer tested it.

    Returns:
        A dict carrying `state` plus, for a reading, the cell's four index
        values, its own coordinate and its own acquisition date. Values
        are the stored ones widened to Python floats -- exact, since every
        float32 is a float64 -- with no rounding applied anywhere.
    """
    result: dict[str, Any] = {
        "state": STATE_OUTSIDE,
        "meaning": STATE_MEANING[STATE_OUTSIDE],
        "query_lat": float(lat),
        "query_lng": float(lng),
        "pixel_row": None,
        "pixel_col": None,
        "pixel_centre_lat": None,
        "pixel_centre_lng": None,
        "cell_lat": None,
        "cell_lng": None,
        "index_values": None,
        "unreadable_bands": [],
        "date_ms": None,
        "acquired_date": None,
        "acquired_at": None,
    }

    located = grid.locate(float(lat), float(lng))
    if located is None:
        # Off the image entirely. The grid always contains the study
        # polygon's bounding box (`render.build_grid` unions it in), so
        # there is no coordinate that is off the image and inside the
        # polygon; the clicked point is tested directly anyway rather than
        # relying on that being true of whatever grid was handed in.
        inside = bool(render.points_in_polygon_mask(np.float64(lat), np.float64(lng), polygon))
        if inside:  # pragma: no cover -- see above; kept so it cannot lie if it happens
            result["state"] = STATE_NOT_MEASURED
            result["meaning"] = STATE_MEANING[STATE_NOT_MEASURED]
        return result

    row, col = located
    centre_lats, centre_lngs = grid.pixel_centres()
    centre_lat = float(centre_lats[row])
    centre_lng = float(centre_lngs[col])
    result.update(
        pixel_row=int(row),
        pixel_col=int(col),
        pixel_centre_lat=centre_lat,
        pixel_centre_lng=centre_lng,
    )

    inside = bool(
        render.points_in_polygon_mask(np.float64(centre_lat), np.float64(centre_lng), polygon)
    )
    if not inside:
        return result

    date_band = bridge.RASTER_DATE_BAND
    cell_lat = np.asarray(cells["lat"], dtype=np.float64)
    cell_lng = np.asarray(cells["lng"], dtype=np.float64)
    dates = np.asarray(cells[date_band])

    # The export validity rule is imported rather than restated: the date
    # band distinguishes a genuine 0.0 from GEE's masked-band fill value
    # (see the module docstring's 0.0 trap). The active NDCI must also be a
    # finite reading, exactly as render_overlay requires before painting.
    # Applied here and not only at download time because this module is
    # handed whatever is on disk, and a blob that ever carried a masked
    # cell must not have its 0.0 read out as a measurement.
    measured = bridge.valid_cell_mask(dates) & np.isfinite(
        np.asarray(cells["ndci"], dtype=np.float64)
    )

    rows_idx, cols_idx = grid.cell_indices(cell_lat, cell_lng)
    hits = np.flatnonzero((rows_idx == row) & (cols_idx == col) & measured)

    if hits.size == 0:
        result["state"] = STATE_NOT_MEASURED
        result["meaning"] = STATE_MEANING[STATE_NOT_MEASURED]
        return result

    # Last one wins -- numpy's own rule for `rgba[rows, cols] = values`,
    # so the cell reported is the cell that painted the pixel.
    index = int(hits[-1])

    values: dict[str, float | None] = {}
    unreadable: list[str] = []
    for band in bridge.RASTER_INDEX_BANDS:
        stored = cells[band][index]
        if np.isfinite(stored):
            # float() on a float32 is exact -- every float32 is a float64.
            # No rounding: a displayed 0.05 that is really 0.050000001 is
            # the display's business, not this module's.
            values[band] = float(stored)
        else:
            values[band] = None
            unreadable.append(band)

    result.update(
        state=STATE_READING,
        meaning=STATE_MEANING[STATE_READING],
        cell_lat=float(cell_lat[index]),
        cell_lng=float(cell_lng[index]),
        index_values=values,
        unreadable_bands=unreadable,
        **_cell_date_fields(int(dates[index])),
    )
    return result


def grid_for_run(run: RasterScanRun, cells: dict) -> OverlayGrid:
    """The grid this run's overlay was actually drawn on.

    Read back from `run.overlay["bounds"]`, which `render.write_overlay_assets`
    wrote from the grid it painted with. Rebuilding it from the cells
    instead would be a second derivation of a number the picture has
    already committed to, and `render._pixel_degrees` infers pixel size
    from the cells themselves -- so a rebuild is not guaranteed to land on
    the same grid, and half a pixel of disagreement is an off-by-one cell
    that no one can see is wrong.

    Falls back to rebuilding only when the row carries no bounds (a run
    stored before an overlay was rendered, or one rendered with no bands
    at all), because an answer computed from the same cells the picture
    was drawn from is still worth more than no answer.
    """
    bounds = ((run.overlay or {}).get("bounds")) if isinstance(run.overlay, dict) else None
    if isinstance(bounds, dict) and "rows" in bounds:
        return OverlayGrid.from_dict(bounds)
    logger.info(
        "raster_scan: run %s has no recorded overlay bounds -- rebuilding the grid "
        "from its cells to answer a pixel query",
        run.id,
    )
    return render.build_grid(cells["lat"], cells["lng"], run.scale_m)


def inspect_run(
    run: RasterScanRun,
    lat: float,
    lng: float,
    polygon: tuple[tuple[float, float], ...] = STUDY_AREA_POLYGON_LATLNG,
) -> dict[str, Any]:
    """`inspect_cell` for the run a caller already selected.

    Raises:
        RasterCellsUnavailableError: the run's blob is gone or its path is
            null. The overlay may still be on screen; the numbers behind
            it are not recoverable, and saying so is the only honest
            answer.
    """
    if not run.blob_path:
        raise RasterCellsUnavailableError(
            f"raster scan {run.id} has no stored cells (blob_deleted_at="
            f"{run.blob_deleted_at}). Its overlay can still be shown, but no reading "
            "behind it can be quoted -- the cells it was drawn from are gone."
        )
    try:
        cells = storage.read_cells(run.blob_path)
    except FileNotFoundError as exc:
        raise RasterCellsUnavailableError(str(exc)) from exc
    return inspect_cell(cells, lat, lng, grid_for_run(run, cells), polygon)
