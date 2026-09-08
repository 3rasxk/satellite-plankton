"""
Map-ready PNG overlay for one stored raster scan.

Data source: none of its own. This module reads the cells one raster scan
already stored (`src/raster_scan/storage.py`'s `.npz` blob, written from
`data-pipeline/src/raster.py`'s whole-polygon Sentinel-2 index composite)
and turns them into pixels. It never calls Google Earth Engine, never
opens a network connection, and never invents a cell that was not stored:
if a run's blob is gone, rendering fails loudly rather than drawing an
empty map. Everything the picture claims was measured comes from that
file.

What the picture says, and the one confusion it exists to prevent
----------------------------------------------------------------
The overlay draws exactly three states, and they are drawn differently on
purpose:

  1. **Valued water** -- a cell with a usable reading. Painted on the
     project's own NDCI ramp (`NDCI_RAMP_HEX` over `NDCI_RAMP_DOMAIN`,
     read through the bridge from `data-pipeline/src/imagery.py`, so the
     overlay and the per-site heatmap colour the same index the same
     way), fully opaque.
  2. **Unmeasured water** -- inside the study polygon, no usable reading.
     Painted as an explicit grey hatch, never left transparent. This is
     the entire reason this module exists. A transparent hole over a blue
     basemap reads to a viewer as "measured, and low" -- which is this
     project's cardinal overclaim in raster form. A viewer must be able
     to tell "we looked and saw little chlorophyll" from "we could not
     see here", and a colour is the only way a map says that.
  3. **Outside the study polygon** -- fully transparent (alpha 0).
     Nothing is drawn, because the basemap already shows what is there
     and an overlay adds no information.

Alpha alone separates the three: 0 outside, 255 for a reading, and
strictly between the two for unmeasured water. So "was this pixel
measured?" is answerable from one channel, without matching colours
against a palette.

The hatch is achromatic by construction (r == g == b) and the ramp is
chromatic everywhere (no interpolation between its five stops ever yields
r == g == b). So no unmeasured pixel can carry a colour the ramp can
produce, at any value, and the distinction survives a viewer's screen,
a screenshot and a JPEG re-encode. It also survives downscaling: a blend
of two greys is grey. `backend/tests/test_raster_scan_render.py` asserts
this against the ramp enumerated densely, not against the code's shape.

Limitations -- read before showing this to anyone
-------------------------------------------------
* **The hatch means "no usable reading", not "cloud".** A cell inside the
  polygon can be missing because it was cloudy, because the JRC water
  mask calls it land, or because no scene in the window covered it. The
  stored blob keeps only the cells that survived, so this module cannot
  tell those three apart and does not pretend to: they are one state with
  one honest label. The practical cost is that land *inside* the polygon
  (the coastline, and the polygon's corners, which sit inland) is hatched
  rather than left clear -- the picture says "nothing was measured here",
  which is true, rather than guessing at a coastline it has no data for.
  Guessing would be the worse failure: a wrong guess punches a
  transparent hole through real water, which is exactly state 2 being
  mistaken for state 1.
* **A cell is one nearest-neighbour-sampled native pixel, not an area
  average** (`data-pipeline/src/raster.py`, "Resolution"). Drawing it as
  a filled square of the sampling interval is a display convention, not a
  claim that the whole square was observed. A bloom smaller than the
  sampling interval is hit or missed depending on where the sample landed.
* **Colours are readings, not verdicts.** The ramp is a cosmetic display
  domain (CLAUDE.md §0/§1): there is no valid spectral-index baseline in
  this project, so nothing here scores, ranks or classifies a cell. Red
  is a high NDCI reading, not "a bloom".
* **One overlay routinely mixes acquisition dates.** The composite is
  most-recent-wins per pixel, so neighbouring pixels can come from scenes
  days apart. The run row's `oldest_scene_date`/`newest_scene_date` state
  the span; the picture itself cannot show it, and a single date must
  never be printed next to it as if it were the overlay's date.
* **Placement is plate carrée, stretched by Leaflet.** The PNG is a
  regular lat/lng grid handed to an `ImageOverlay` with corner bounds.
  Leaflet stretches it into Web Mercator linearly, and over this
  polygon's ~1.1 degrees of latitude that misplaces mid-image rows by a
  fraction of a percent of the image height -- irrelevant at regional
  scale, wrong for measuring a coastline against.

For whoever draws it (piece 3): the PNG is exact per-pixel state, so it
wants `image-rendering: pixelated` rather than the browser's default
smoothing, which blends hatch and value colours into intermediates at
their shared edges.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from sqlalchemy.orm import Session

from .. import _detection as bridge
from .._study_area import STUDY_AREA_POLYGON_LATLNG
from ..db_models import RasterScanRun
from . import storage

logger = logging.getLogger("backend.raster_scan.render")

# --------------------------------------------------------------------------
# The ramp. Not defined here -- read through the bridge from
# data-pipeline/src/imagery.py, which is where this project's NDCI display
# colours and display domain already live (and are already unit-tested).
# --------------------------------------------------------------------------
NDCI_RAMP_HEX: tuple[str, ...] = bridge.NDCI_RAMP_HEX
NDCI_RAMP_DOMAIN: tuple[float, float] = bridge.NDCI_RAMP_DOMAIN

# Bands this module will draw, and the display domain each is drawn over.
#
# NDCI only, deliberately. The stored blob carries four indices, but only
# NDCI has a display domain anyone in this project has agreed on
# (imagery.py's NDCI_RAMP_DOMAIN, chosen against real observed values and
# documented there). 2BDA, 3BDA and B2/B3 live on entirely different
# scales, and picking a min/max for them here would be inventing a
# visualisation domain -- which decides what looks alarming -- with
# nothing to justify it. A human sets those, and then they render;
# `render_overlay` refuses a band that has no entry rather than guessing.
BAND_DOMAINS: dict[str, tuple[float, float]] = {"ndci": NDCI_RAMP_DOMAIN}
RENDERED_BANDS: tuple[str, ...] = ("ndci",)

# --------------------------------------------------------------------------
# The three states, as pixels. RGBA, straight alpha.
# --------------------------------------------------------------------------
#
# Alpha alone says which state a pixel is in, and the values below are
# chosen so that stays true:
#
#     alpha == 0                  outside the study area, nothing drawn
#     alpha == VALUE_ALPHA (255)  a real reading, on the ramp
#     0 < alpha < 255             inside the study area, nothing usable
#
# That is a property worth paying for rather than a coincidence: it means
# "is this pixel a measurement?" can be answered from one channel, by a
# test, by whatever draws a legend, and by anyone poking at the PNG --
# without matching RGB against a palette. It is why the hatch tones stop
# short of full opacity.
#
# State 3 -- outside the study polygon. Nothing drawn at all.
OUTSIDE_RGBA: tuple[int, int, int, int] = (0, 0, 0, 0)

# State 1 -- a real reading. Fully opaque, so a value is never dimmed
# toward the basemap and never reads as partial evidence. Whether the
# whole layer is shown at reduced opacity is the map's decision, made once
# for the layer, not something baked per-pixel here.
VALUE_ALPHA = 255

# State 2 -- inside the polygon, nothing usable. Two greys in a diagonal
# hatch, both opaque enough to be unmistakably drawn rather than absent.
#
# Grey is not a decoration here, it is the guarantee: both tones are
# achromatic (r == g == b), and the ramp's five stops are chromatic and
# stay chromatic between every adjacent pair, so no unmeasured pixel can
# ever equal a value pixel. The stripes make it read as "no data" at a
# glance rather than as a flat fill that could be mistaken for one more
# ramp colour, and they stay distinguishable when the map is zoomed out
# far enough to blur them (a blend of two greys is still grey).
#
# The tones are also deliberately far from the ramp's LOW end (#0A1929,
# near-black navy), because "low reading" vs "no reading" is the specific
# confusion this module exists to prevent -- a dark grey hatch against a
# near-black low colour would have defeated the point.
#
# Neither tone is fully opaque, so that alpha keeps meaning what the block
# above says it means: 255 is reserved for a reading. They are still far
# from transparent -- an unmeasured pixel has to be seen.
NO_DATA_BASE_RGBA: tuple[int, int, int, int] = (176, 176, 176, 205)
NO_DATA_STRIPE_RGBA: tuple[int, int, int, int] = (92, 92, 92, 235)

# The weakest alpha any unmeasured pixel is allowed to carry, and the
# strongest. Stated as constants so "unmeasured is never transparent, and
# never mistakable for a reading" is a checkable rule rather than an
# accident of the two tuples above.
NO_DATA_MIN_ALPHA = min(NO_DATA_BASE_RGBA[3], NO_DATA_STRIPE_RGBA[3])
NO_DATA_MAX_ALPHA = max(NO_DATA_BASE_RGBA[3], NO_DATA_STRIPE_RGBA[3])

HATCH_PERIOD_PX = 6
HATCH_STRIPE_PX = 2

# --------------------------------------------------------------------------
# Grid geometry.
# --------------------------------------------------------------------------
#
# Earth Engine converts a metre `scale` to degrees for an EPSG:4326 read
# with this constant (one degree of latitude at the equator), applying it
# to both axes -- so a 200 m read is a 0.0017966-degree grid in lat and
# lng alike, not a 200 m square on the ground away from the equator. The
# renderer needs the same number to place a cell in the pixel it belongs
# to.
METRES_PER_DEGREE = 111_319.49

# Below this many distinct coordinates the observed spacing is not
# evidence of anything (three cells in a test fixture are not a grid), so
# the scale is used instead. See `_pixel_degrees`.
MIN_UNIQUE_FOR_INFERENCE = 8

# An overlay is a picture for a screen, not an export product. 16 million
# pixels is already ~4000 on a side -- past that, a mistaken scale (a 10 m
# read over the whole polygon: 12,400 x 12,400) would quietly try to
# allocate gigabytes, so it is refused with the numbers in the message.
MAX_OVERLAY_PIXELS = 16_000_000

OVERLAY_FILENAME_TEMPLATE = "overlay_{band}.png"
SIDECAR_FILENAME = "overlay.json"


class OverlayTooLargeError(RuntimeError):
    """The requested grid would exceed `MAX_OVERLAY_PIXELS`. Raised
    instead of attempting the allocation, because the failure mode
    otherwise is the host running out of memory rather than a message
    naming the scale that caused it."""


class UnrenderableBandError(ValueError):
    """A band was asked for that has no agreed display domain (see
    `BAND_DOMAINS`). Refused rather than rendered over an invented
    min/max, because the domain is what decides which readings look
    alarming."""


@dataclass(frozen=True)
class OverlayGrid:
    """The pixel grid an overlay was drawn on, in geographic terms.

    Edges, not centres: `north`/`south`/`west`/`east` are the outer edges
    of the outer pixels, which is exactly what a Leaflet `ImageOverlay`'s
    corner bounds mean. A half-pixel error here shifts the whole raster
    on the map, so the two are kept as one object rather than derived
    twice.
    """

    north: float
    south: float
    west: float
    east: float
    rows: int
    cols: int
    pixel_deg_lat: float
    pixel_deg_lng: float
    pixel_size_source: str  # "cells" | "scale_m" -- see _pixel_degrees

    @property
    def leaflet_bounds(self) -> list[list[float]]:
        """[[south, west], [north, east]] -- Leaflet's L.latLngBounds
        constructor order, ready to hand to L.imageOverlay."""
        return [[self.south, self.west], [self.north, self.east]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "south": self.south,
            "west": self.west,
            "north": self.north,
            "east": self.east,
            "leaflet_bounds": self.leaflet_bounds,
            "rows": self.rows,
            "cols": self.cols,
            "pixel_deg_lat": self.pixel_deg_lat,
            "pixel_deg_lng": self.pixel_deg_lng,
            "pixel_size_source": self.pixel_size_source,
        }

    def pixel_centres(self) -> tuple[np.ndarray, np.ndarray]:
        """(lat, lng) of every pixel centre, as 1-D row and column axes.
        Row 0 is the northernmost row -- image order, not map order."""
        lats = self.north - (np.arange(self.rows) + 0.5) * self.pixel_deg_lat
        lngs = self.west + (np.arange(self.cols) + 0.5) * self.pixel_deg_lng
        return lats, lngs

    def cell_indices(self, lat: np.ndarray, lng: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Pixel (row, col) each cell centre falls in, clipped to the
        grid. Clipping matters for a cell sitting exactly on the eastern
        or southern edge: floor() would put it one pixel outside."""
        rows = np.floor((self.north - np.asarray(lat)) / self.pixel_deg_lat).astype(np.int64)
        cols = np.floor((np.asarray(lng) - self.west) / self.pixel_deg_lng).astype(np.int64)
        return np.clip(rows, 0, self.rows - 1), np.clip(cols, 0, self.cols - 1)

    def locate(self, lat: float, lng: float) -> tuple[int, int] | None:
        """The pixel a single arbitrary coordinate lands in, or None if it
        lands outside this grid entirely.

        The inverse of `cell_indices`, and it lives here rather than in
        the module that inspects cells for exactly that reason: the two
        directions must use the same `north`/`west` origin and the same
        `floor()`, or a click would report the neighbour of the cell whose
        colour is under the cursor. Off-by-one there is invisible -- both
        cells are plausible readings -- so the pairing is kept structural
        rather than left to two call sites agreeing.

        The one deliberate difference is clipping. `cell_indices` clips,
        because its input is a stored cell that belongs to this raster and
        an extreme one must not fall off the edge. This takes a coordinate
        from outside -- a click anywhere on a world map -- and clipping it
        would answer a query about the open Pacific with the reading from
        the raster's eastern edge. So out is None, not the nearest pixel;
        only a coordinate exactly on the southern or eastern edge is
        pulled back into the last pixel, which is the same boundary case
        `cell_indices` clips for.
        """
        if not (self.south <= lat <= self.north and self.west <= lng <= self.east):
            return None
        row = int(np.floor((self.north - lat) / self.pixel_deg_lat))
        col = int(np.floor((lng - self.west) / self.pixel_deg_lng))
        # Exactly on the south/east edge (or a float hair past it): the
        # edge belongs to the last pixel, as it does in `cell_indices`.
        row = min(max(row, 0), self.rows - 1)
        col = min(max(col, 0), self.cols - 1)
        return row, col

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OverlayGrid":
        """Rebuild a grid from what `as_dict` stored on the run row.

        Reconstructed, never recomputed: an overlay's geometry is a fact
        about the picture that was drawn, and re-deriving it from the
        cells later can quietly land somewhere else (`_pixel_degrees`
        infers the spacing from the cells, so a differently-filtered read
        of the same blob can pick a different pixel size). Anything that
        must agree with the painted image reads the numbers the painter
        recorded.
        """
        return cls(
            north=float(data["north"]),
            south=float(data["south"]),
            west=float(data["west"]),
            east=float(data["east"]),
            rows=int(data["rows"]),
            cols=int(data["cols"]),
            pixel_deg_lat=float(data["pixel_deg_lat"]),
            pixel_deg_lng=float(data["pixel_deg_lng"]),
            pixel_size_source=str(data.get("pixel_size_source", "stored")),
        )


@dataclass(frozen=True)
class RenderedOverlay:
    """One rendered band: the pixels, where they go, and what they cover."""

    band: str
    rgba: np.ndarray  # (rows, cols, 4) uint8
    grid: OverlayGrid
    domain: tuple[float, float]
    stats: dict[str, Any]


# --------------------------------------------------------------------------
# Pure pixel math -- no files, no database, no `ee`.
# --------------------------------------------------------------------------


def ramp_rgb(
    values: np.ndarray,
    domain: tuple[float, float] = NDCI_RAMP_DOMAIN,
    stops_hex: tuple[str, ...] = NDCI_RAMP_HEX,
) -> np.ndarray:
    """Vectorised form of `imagery.ndci_value_to_color`, for N values at
    once.

    Same piecewise-linear interpolation across the same evenly spaced
    stops, same clamping outside `domain`, same half-to-even rounding --
    it is the identical mapping applied to an array instead of a scalar,
    written out here only because colouring ~50,000 cells through a
    Python-level function per cell is not worth the round trip. The two
    are asserted equal value-for-value in the test suite, so this can
    never quietly become a second, differently-tuned palette.

    Args:
        values: finite index readings. Non-finite input is the caller's
            problem to exclude -- `render_overlay` treats a non-finite
            reading as unmeasured, because there is no colour that
            honestly represents "the arithmetic did not produce a number".
        domain, stops_hex: as in `imagery.ndci_value_to_color`.

    Returns:
        (N, 3) uint8 array of RGB.

    Raises:
        ValueError: degenerate domain, or fewer than two stops.
    """
    vmin, vmax = domain
    if vmax <= vmin:
        raise ValueError(f"domain max ({vmax}) must be > domain min ({vmin})")
    if len(stops_hex) < 2:
        raise ValueError("Need at least 2 ramp stops to interpolate between")

    stops = np.array([bridge.hex_to_rgb(h) for h in stops_hex], dtype=np.float64)
    n = len(stops)

    values = np.asarray(values, dtype=np.float64)
    t = np.clip((values - vmin) / (vmax - vmin), 0.0, 1.0)
    scaled = t * (n - 1)
    # Clipped to n-2 so t == 1 interpolates to exactly the last stop with
    # frac == 1, matching the scalar version's `if i >= n - 1` branch
    # rather than indexing off the end.
    lower = np.clip(np.floor(scaled).astype(np.int64), 0, n - 2)
    frac = (scaled - lower)[:, None]
    c0 = stops[lower]
    c1 = stops[lower + 1]
    return np.round(c0 + (c1 - c0) * frac).astype(np.uint8)


def points_in_polygon_mask(
    lat: np.ndarray, lng: np.ndarray, polygon: tuple[tuple[float, float], ...]
) -> np.ndarray:
    """Ray-casting point-in-polygon over whole arrays at once.

    The same algorithm as `data-pipeline/src/study_area.py`'s
    `point_in_polygon`, evaluated on a grid instead of one point --
    384,000 pixel centres is too many Python-level calls to be worth it.
    The suite checks the two agree on a lattice covering the real study
    polygon, so this is a vectorisation of that rule and not a second
    opinion about where the study area is.

    Args:
        lat, lng: broadcastable coordinate arrays.
        polygon: (lat, lng) vertices, implicitly closed.

    Returns:
        Boolean array (broadcast shape) -- True inside. Boundary
        behaviour is whatever ray casting does, exactly as the scalar
        version documents: reliable for points clearly in or clearly out.
    """
    x = np.asarray(lng, dtype=np.float64)
    y = np.asarray(lat, dtype=np.float64)
    inside = np.zeros(np.broadcast(x, y).shape, dtype=bool)

    x1, y1 = polygon[-1][1], polygon[-1][0]
    for vertex_lat, vertex_lng in polygon:
        x2, y2 = vertex_lng, vertex_lat
        if y2 != y1:
            # `(y1 > y) != (y2 > y)` is False for every point when the
            # edge is horizontal, and the scalar version's `and` never
            # evaluates the division in that case. numpy would, and would
            # divide by zero -- so the branch reproduces the short circuit.
            straddles = (y1 > y) != (y2 > y)
            crosses = straddles & (x < (x2 - x1) * (y - y1) / (y2 - y1) + x1)
            inside ^= crosses
        x1, y1 = x2, y2
    return inside


def hatch_mask(rows: int, cols: int) -> np.ndarray:
    """Diagonal stripe pattern, True on the stripe.

    Position-based rather than data-based: the stripes must not encode
    anything, or a viewer could read structure into them. Their only job
    is to make a no-data region unmistakable as a region.
    """
    yy, xx = np.mgrid[0:rows, 0:cols]
    return ((xx + yy) % HATCH_PERIOD_PX) < HATCH_STRIPE_PX


def _pixel_degrees(values: np.ndarray, scale_m: int) -> tuple[float, str]:
    """Pixel size in degrees for one axis, and where it came from.

    Two sources, and the cheap one is only trusted when it is evidence:

      * the cells' own spacing (the smallest gap between distinct stored
        coordinates), which is what the grid actually is, whatever
        projection Earth Engine chose;
      * `scale_m / METRES_PER_DEGREE`, the spacing an EPSG:4326 read at
        that scale is expected to have.

    The observed spacing is used only when there are enough distinct
    coordinates for it to mean something AND it agrees with the expected
    spacing to within a factor of two. Otherwise the scale wins. The
    reason is a specific failure: a raster reduced to a handful of
    scattered cells would otherwise report a "spacing" of kilometres, and
    each cell -- one sampled 10 m pixel -- would be painted as a
    kilometres-wide block of confident colour.
    """
    expected = scale_m / METRES_PER_DEGREE
    # Rounded first so float noise in the ninth decimal (~0.1 mm) does not
    # register as a distinct coordinate and produce a spacing of zero.
    unique = np.unique(np.round(np.asarray(values, dtype=np.float64), 9))
    if unique.size < MIN_UNIQUE_FOR_INFERENCE:
        return expected, "scale_m"
    diffs = np.diff(unique)
    diffs = diffs[diffs > 1e-9]
    if diffs.size == 0:
        return expected, "scale_m"
    observed = float(np.min(diffs))
    if not (0.5 * expected <= observed <= 2.0 * expected):
        return expected, "scale_m"
    return observed, "cells"


def build_grid(
    lat: np.ndarray,
    lng: np.ndarray,
    scale_m: int,
    polygon: tuple[tuple[float, float], ...] = STUDY_AREA_POLYGON_LATLNG,
) -> OverlayGrid:
    """The pixel grid an overlay of these cells is drawn on.

    The extent is the study polygon's bounding box UNIONED with the cells'
    own bounding box -- never the cells alone. That is the important part:
    an overlay sized to the cells would shrink on a cloudy day, and the
    water that went missing would leave the image entirely instead of
    being drawn as unmeasured. The area a scan covers must not depend on
    how much of it the scan could see. (The union also keeps a cell that
    landed marginally outside the polygon inside the picture, rather than
    cropping a real reading away.)

    Raises:
        OverlayTooLargeError: the grid would exceed MAX_OVERLAY_PIXELS.
        ValueError: no cells, or a non-positive scale.
    """
    lat = np.asarray(lat, dtype=np.float64)
    lng = np.asarray(lng, dtype=np.float64)
    if lat.size == 0 or lng.size == 0:
        raise ValueError(
            "cannot build an overlay grid from zero cells -- a run that measured "
            "nothing is recorded as status='no_data' and has no blob to render."
        )
    if scale_m <= 0:
        raise ValueError(f"scale_m must be positive, got {scale_m}")

    pixel_lat, source_lat = _pixel_degrees(lat, scale_m)
    pixel_lng, source_lng = _pixel_degrees(lng, scale_m)
    # One label for the pair: mixed provenance would be confusing to read
    # back, and the two axes come off the same read.
    source = "cells" if source_lat == source_lng == "cells" else "scale_m"

    poly_lats = [vertex[0] for vertex in polygon]
    poly_lngs = [vertex[1] for vertex in polygon]
    south = min(min(poly_lats), float(lat.min()))
    north = max(max(poly_lats), float(lat.max()))
    west = min(min(poly_lngs), float(lng.min()))
    east = max(max(poly_lngs), float(lng.max()))

    # Half a pixel of margin puts an extreme cell's centre inside its own
    # pixel instead of on the boundary; the grid is then snapped outward
    # from the north-west corner so the stated bounds are the real edges
    # of the real pixels, not a rectangle the pixels approximately fill.
    north_edge = north + pixel_lat / 2
    west_edge = west - pixel_lng / 2
    rows = max(1, int(np.ceil((north_edge - (south - pixel_lat / 2)) / pixel_lat)))
    cols = max(1, int(np.ceil(((east + pixel_lng / 2) - west_edge) / pixel_lng)))

    if rows * cols > MAX_OVERLAY_PIXELS:
        raise OverlayTooLargeError(
            f"an overlay of {rows} x {cols} = {rows * cols} pixels exceeds the "
            f"{MAX_OVERLAY_PIXELS}-pixel ceiling (scale_m={scale_m}, pixel="
            f"{pixel_lat:.6g} deg). An overlay is a picture for a screen; a read "
            "this fine belongs in the stored cells, not in one PNG."
        )

    return OverlayGrid(
        north=north_edge,
        south=north_edge - rows * pixel_lat,
        west=west_edge,
        east=west_edge + cols * pixel_lng,
        rows=rows,
        cols=cols,
        pixel_deg_lat=pixel_lat,
        pixel_deg_lng=pixel_lng,
        pixel_size_source=source,
    )


def render_overlay(
    cells: dict,
    band: str = "ndci",
    scale_m: int = bridge.DEFAULT_RASTER_SCALE_M,
    polygon: tuple[tuple[float, float], ...] = STUDY_AREA_POLYGON_LATLNG,
    domain: tuple[float, float] | None = None,
) -> RenderedOverlay:
    """Draw one band of one stored raster as RGBA pixels.

    Painting order is the guarantee, not an implementation detail:
    everything starts transparent (state 3), the polygon's interior is
    then filled with the no-data hatch (state 2), and only then are the
    stored cells painted over it (state 1). A real reading therefore
    always wins over the hatch, and any pixel that is not a reading is
    left saying so. Nothing can silently invert that.

    A cell whose value is not finite (an index is a ratio, and a division
    by a zero-reflectance pixel can produce inf or NaN even where the
    cell's date is perfectly good) is counted, reported in `stats`, and
    left as unmeasured. There is no honest colour for "the arithmetic did
    not produce a number", and putting it at either end of the ramp would
    be inventing a reading.

    Args:
        cells: `storage.read_cells`' return value -- needs at least
            `lat`, `lng` and `band`.
        band: which index to draw (see BAND_DOMAINS).
        scale_m: the run's read scale, for pixel sizing.
        polygon: study-area boundary; the hatch is drawn inside it.
        domain: display domain override; defaults to BAND_DOMAINS[band].

    Raises:
        UnrenderableBandError: `band` has no agreed display domain.
        KeyError: the blob does not carry that band.
        OverlayTooLargeError, ValueError: see `build_grid`.
    """
    if domain is None:
        if band not in BAND_DOMAINS:
            raise UnrenderableBandError(
                f"no display domain is defined for {band!r} (have: "
                f"{sorted(BAND_DOMAINS)}). Rendering it would mean inventing the "
                "min/max that decides which readings look alarming -- a human sets "
                "that, in data-pipeline/src/imagery.py, the same way NDCI's was set."
            )
        domain = BAND_DOMAINS[band]

    lat = np.asarray(cells["lat"], dtype=np.float64)
    lng = np.asarray(cells["lng"], dtype=np.float64)
    values = np.asarray(cells[band], dtype=np.float64)

    grid = build_grid(lat, lng, scale_m, polygon)
    centre_lats, centre_lngs = grid.pixel_centres()
    inside = points_in_polygon_mask(centre_lats[:, None], centre_lngs[None, :], polygon)

    rgba = np.zeros((grid.rows, grid.cols, 4), dtype=np.uint8)
    rgba[...] = OUTSIDE_RGBA
    stripes = hatch_mask(grid.rows, grid.cols)
    rgba[inside & stripes] = NO_DATA_STRIPE_RGBA
    rgba[inside & ~stripes] = NO_DATA_BASE_RGBA

    finite = np.isfinite(values)
    rows_idx, cols_idx = grid.cell_indices(lat[finite], lng[finite])
    if rows_idx.size:
        rgba[rows_idx, cols_idx, :3] = ramp_rgb(values[finite], domain, NDCI_RAMP_HEX)
        rgba[rows_idx, cols_idx, 3] = VALUE_ALPHA

    valued = np.zeros((grid.rows, grid.cols), dtype=bool)
    valued[rows_idx, cols_idx] = True
    inside_total = int(inside.sum())
    measured_inside = int((inside & valued).sum())
    stats = {
        "cell_count": int(lat.size),
        # Cells whose reading was not a finite number: counted here rather
        # than dropped quietly, because a raster that lost most of its
        # cells this way is a raster to investigate, not to display.
        "unreadable_cells": int((~finite).sum()),
        "valued_pixels": int(valued.sum()),
        "no_data_pixels": int((inside & ~valued).sum()),
        "transparent_pixels": int((~inside & ~valued).sum()),
        "inside_polygon_pixels": inside_total,
        # The numerator of measured_fraction, carried explicitly so a
        # reader of this metadata (or of the API that serves it) never has
        # to reconstruct a count by multiplying a rounded fraction back
        # out against a total.
        "measured_pixels": measured_inside,
        # Fraction of the study polygon this raster actually has a reading
        # for. The honest headline number for an overlay: everything else
        # inside the boundary is hatch. Denominator is the POLYGON, land
        # included -- the polygon is a boundary, not a water mask, so the
        # land inside it can never be measured and is counted against
        # this figure. It is not a fraction of water.
        "measured_fraction": (measured_inside / inside_total) if inside_total else 0.0,
        # Readings that fell outside the polygon and were still drawn -- a
        # measurement is never erased for being marginally out of bounds.
        "valued_pixels_outside_polygon": int((~inside & valued).sum()),
    }
    return RenderedOverlay(band=band, rgba=rgba, grid=grid, domain=tuple(domain), stats=stats)


# --------------------------------------------------------------------------
# Files and the run row.
# --------------------------------------------------------------------------


def write_png(rgba: np.ndarray, path: Path) -> int:
    """Write an (rows, cols, 4) uint8 array as an RGBA PNG. Returns bytes.

    PNG, not JPEG: an overlay needs an alpha channel to leave land alone,
    and it must be lossless -- a JPEG's ringing around the hatch edges
    would blend no-data grey with a value colour and produce pixels that
    are neither.
    """
    if rgba.dtype != np.uint8 or rgba.ndim != 3 or rgba.shape[2] != 4:
        raise ValueError(
            f"expected an (rows, cols, 4) uint8 RGBA array, got {rgba.shape} "
            f"of {rgba.dtype}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba, mode="RGBA").save(path, format="PNG", optimize=True)
    return path.stat().st_size


def write_overlay_assets(
    run_id: int,
    cells: dict,
    scale_m: int,
    root: Path | None = None,
    bands: tuple[str, ...] = RENDERED_BANDS,
    polygon: tuple[tuple[float, float], ...] = STUDY_AREA_POLYGON_LATLNG,
) -> dict[str, Any]:
    """Render `bands` from already-read cells and write them beside the blob.

    Assets live in the run's own directory (`storage.run_blob_dir`),
    alongside the cells they were drawn from -- the sidecar that piece 1's
    storage docstring left room for. A `overlay.json` is written next to
    the PNGs carrying the bounds and the legend, so the images stay
    placeable and readable even if the database is rebuilt: a PNG with no
    bounds is not a map layer, it is a picture of nothing in particular.

    Returns the metadata to store on the run row (see `render_and_store`).
    """
    directory = storage.run_blob_dir(run_id, root)
    grid: OverlayGrid | None = None
    assets: dict[str, Any] = {}
    for band in bands:
        rendered = render_overlay(cells, band=band, scale_m=scale_m, polygon=polygon)
        grid = rendered.grid
        path = directory / OVERLAY_FILENAME_TEMPLATE.format(band=band)
        size = write_png(rendered.rgba, path)
        assets[band] = {
            "path": str(path),
            "bytes": size,
            "domain": list(rendered.domain),
            "ramp_hex": list(NDCI_RAMP_HEX),
            **rendered.stats,
        }

    metadata: dict[str, Any] = {
        "status": "ok",
        "rendered_at": datetime.now(timezone.utc).isoformat(),
        "scale_m": int(scale_m),
        "bounds": grid.as_dict() if grid else None,
        "assets": assets,
        # What each of the three states means, carried with the picture so
        # a legend cannot be written from a guess about the colours.
        "legend": {
            "value": {
                "ramp_hex": list(NDCI_RAMP_HEX),
                "domain": list(BAND_DOMAINS.get(bands[0], NDCI_RAMP_DOMAIN)) if bands else None,
                # Discrete swatches sampled from the same ramp_rgb() that
                # painted the image, so a legend can be drawn from these
                # bytes instead of re-interpolating the stops itself. Two
                # interpolations that agree today can drift apart later,
                # and a legend that disagrees with the picture is a quiet
                # lie about what a colour means.
                "swatches": legend_swatches(
                    BAND_DOMAINS.get(bands[0], NDCI_RAMP_DOMAIN)
                ) if bands else [],
                "meaning": (
                    "index reading at this cell -- a display ramp, not a risk "
                    "score: no valid spectral-index baseline exists, so nothing "
                    "here classifies a cell"
                ),
            },
            "no_data": {
                "base_rgba": list(NO_DATA_BASE_RGBA),
                "stripe_rgba": list(NO_DATA_STRIPE_RGBA),
                "meaning": (
                    "inside the study area, no usable reading -- cloud, "
                    "land-masked, or no scene covered it. Not a low reading."
                ),
            },
            "transparent": {
                "rgba": list(OUTSIDE_RGBA),
                "meaning": "outside the study area -- nothing was looked at, nothing drawn",
            },
        },
        # Flat list of every file written for this run, so retention can
        # remove them all without knowing the shape of anything above.
        "files": [asset["path"] for asset in assets.values()],
    }

    # The sidecar is written last but describes itself, so the file on
    # disk and the copy on the run row are the same document -- one of
    # them being a subset of the other is the kind of small asymmetry
    # that later reads as a bug.
    sidecar = directory / SIDECAR_FILENAME
    metadata["sidecar_path"] = str(sidecar)
    metadata["files"].append(str(sidecar))
    sidecar.write_text(json.dumps(metadata, indent=2))
    logger.info(
        "raster_scan: run %s rendered %s (%s) -- %.1f%% of the polygon measured, "
        "the rest drawn as no-data",
        run_id,
        ", ".join(assets),
        grid.as_dict()["leaflet_bounds"] if grid else "no bounds",
        100 * next(iter(assets.values()))["measured_fraction"] if assets else 0.0,
    )
    return metadata


LEGEND_SWATCH_COUNT = 24


def legend_swatches(domain: tuple[float, float], count: int = LEGEND_SWATCH_COUNT) -> list[dict]:
    """Discrete legend colours, taken from the renderer's own ramp.

    Returns `count` evenly spaced samples across `domain` as
    {"value": float, "hex": "#rrggbb"}, computed by the same
    `ramp_rgb()` that paints the overlay. A legend built from these is
    the picture's colours by construction; one built by re-interpolating
    the stops is a second implementation that can drift.
    """
    import numpy as _np

    values = _np.linspace(domain[0], domain[1], count)
    colours = _np.asarray(ramp_rgb(values))
    return [
        {"value": float(v), "hex": "#{:02x}{:02x}{:02x}".format(int(c[0]), int(c[1]), int(c[2]))}
        for v, c in zip(values, colours)
    ]


def render_and_store(
    db: Session,
    run: RasterScanRun,
    root: Path | None = None,
    bands: tuple[str, ...] = RENDERED_BANDS,
) -> dict[str, Any]:
    """Render one completed run's stored raster and record it on the row.

    Reads the cells from `run.blob_path` -- the path the row itself
    records, the same authority retention uses -- so an expired run raises
    `FileNotFoundError` from `storage.read_cells` rather than producing an
    empty overlay that looks like a real one. There is no path here that
    reaches Earth Engine: an overlay is a picture of what was already
    measured and stored, never a new measurement.

    Returns the stored metadata dict. Also assigned to `run.overlay` and
    committed, so a later piece can serve the PNG and its bounds from the
    row alone.

    Raises:
        ValueError: the run has no blob to render.
        FileNotFoundError: the blob it names is gone.
    """
    if not run.blob_path:
        raise ValueError(
            f"raster scan {run.id} has no blob to render (status={run.status!r}, "
            f"blob_deleted_at={run.blob_deleted_at}). A run that stored no cells "
            "has no overlay -- that is the honest state, not one to draw around."
        )
    cells = storage.read_cells(run.blob_path)
    metadata = write_overlay_assets(run.id, cells, run.scale_m, root=root, bands=bands)
    run.overlay = metadata
    db.commit()
    return metadata
