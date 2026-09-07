"""
Raster (whole-polygon) spectral-index composite — Gulf of Thailand.

Data source: Copernicus Sentinel-2 Level-2A surface reflectance,
`COPERNICUS/S2_SR_HARMONIZED`, via Google Earth Engine, masked with the
same two auxiliary layers `sentinel2.py` uses — JRC Global Surface Water
v1.4 (`occurrence`) and NOAA ETOPO1 (`bedrock`) — through that module's
own `_water_mask_image()` / `_cloud_flag_image()`. No second copy of the
masking rule lives here.

Resolution, and what a cell actually is: the source bands are 10 m
(B2/B3/B4) and 20 m (B5/B6), but a raster read is requested at a coarser
`scale_m` (default 200 m) because a 10 m read over the whole study
polygon is neither affordable nor needed for a regional picture. An
explicit `reduceResolution` was tried at polygon extent and fails
outright ("Reprojection output too large"), so `scale=` is passed to
`getDownloadURL` instead.

That coarsening is **systematic sampling, not averaging**. Measured
against live GEE (2026-09-07, 2 km box at 12.5496N 100.0519E, the same
region read at 10 m and at 200 m): a 200 m cell came back 0.00000000
while the 400 native pixels beneath it averaged 0.01839816, and the
cell's value matched one native pixel exactly. GEE resamples with
nearest neighbour; it does not area-average. So a 200 m cell is **one
real 10 m pixel** -- a 1-in-400 sample (1-in-100 for the 20 m bands, and
1-in-100 overall at `scale_m=100`) -- carrying that pixel's own real
acquisition date.

This is the better property, not merely the cheaper one. Value and
provenance stay consistent: the number and the date in a cell come from
the same observation. An area average could not honestly carry a date at
all -- a mean of 400 pixels drawn from three different scenes has no
acquisition date, and inventing one is precisely the failure the date
band exists to prevent.

Limitation: this is the same optical measurement `sentinel2.py` makes,
read across an area instead of at a point, and it inherits every one of
that module's limitations — cloud gaps, the multi-year (not today's)
water mask, turbidity contamination near river mouths, and detection at
*pixel* resolution only: water-colour signatures, never individual
organisms, and small or dispersed blooms may be missed entirely. It is
also weaker than a point reading in one specific way, though not the way
an averaging scheme would be: because each cell is a single sampled
pixel rather than a summary of its neighbourhood, a feature smaller than
the 200 m sampling interval is not diluted -- it is either hit or missed
outright, depending on where the sample lands. Absence of signal in a
cell is therefore weaker evidence than a point reading's 30 m buffer
mean, which at least averaged the pixels it covered. Nothing here scores, ranks, or classifies
a cell: the four indices are returned as readings, exactly as elsewhere
in this project, because no valid spectral-index baseline exists
(CLAUDE.md §0/§1).

Compositing rule: the most recent acquisition wins, per pixel. The
collection is sorted ascending by `system:time_start` and `mosaic()`d, and
`mosaic()` keeps the last unmasked value it sees — so where two scenes
both have a usable pixel, the newer one answers, and where the newer one
is cloudy the older one fills in. One raster is therefore routinely a
mixture of several acquisition dates, which is exactly why every cell
carries its own date.

The date band, and why it is the fragile part
---------------------------------------------
Each cell carries `date_ms`, the acquisition timestamp (epoch
milliseconds, UTC) of the scene that actually supplied that cell. Two
independent ways exist to destroy that number, and both are guarded here
rather than left to reviewer vigilance:

  1. *Averaging.* The mean of two acquisition timestamps is a timestamp
     no satellite flew. It looks like a date, formats like a date, and is
     fabricated. Three independent things prevent it, and it matters to
     be exact about which of them acts where:
       - GEE's read path never averages: it samples with nearest
         neighbour (measured -- see "Resolution" above), so a cell's date
         is whatever that one pixel carried.
       - The band is built as an `ee.Image.constant` per acquisition --
         one value across a whole scene -- and the only cross-scene
         combination it undergoes is `mosaic()`, which selects.
       - `RASTER_BAND_REDUCERS` pins the date band to a selecting
         reducer (`mode`, ties broken toward the newer scene). **This
         governs `summarize_raster_cells` -- the pure-numpy reduction
         over already-downloaded cells -- and nothing else. It is not
         communicated to Earth Engine and cannot influence the read.**
     Belt and braces regardless: on the way back in,
     `download_composite_arrays` refuses any date that is not one of the
     composite's own source timestamps (`FabricatedDateError`).
  2. *Narrowing.* Epoch milliseconds today are ~1.79e12, which needs 13
     significant digits. float32 carries about 7: its spacing at that
     magnitude is 131,072 ms, so a float32 round trip silently moves a
     timestamp by up to ~65 seconds (measured: 2026-09-04T03:30:00Z comes
     back 44,352 ms late). That is not a rounding nicety -- the value
     stops equalling any real `system:time_start`, so it can no longer be
     matched to the acquisition it came from, and guard 1 above, which is
     exact equality, would reject every cell without saying why. The band
     is therefore cast `.toDouble()` (float64, exact for every integer
     below 2^53) in transit and converted to int64 at rest, and a date
     band arriving narrower is refused (`DateBandPrecisionError`).

Offline-testable pieces (`data-pipeline/tests/test_raster_composite.py`):
`RASTER_BAND_REDUCERS`, `NUMPY_BAND_REDUCERS` and
`summarize_raster_cells` are plain data and plain numpy — no `ee` object
is involved, so the reduction policy can be asserted directly. The
composite/download path is exercised against a synthetic `ee` double that
computes real numpy arrays, so the masking order, the mosaic's
most-recent-wins rule and both date guards run as production code.

What that suite structurally CANNOT tell you: how real Earth Engine
resamples. The double is what applies `RASTER_BAND_REDUCERS` when it
coarsens; real GEE never sees that dict. A green suite is therefore not
evidence that the GEE read behaves as described here -- the claim that
it samples rather than averages rests on the live measurement recorded
under "Resolution", and re-checking it needs a live call, not a test
run. This exact gap already hid one wrong claim in this file.
"""

from __future__ import annotations

import io
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

import ee
import numpy as np

from .auth import initialize_ee
from .sentinel2 import (
    BANDS,
    DEFAULT_CLOUD_CLASSES,
    DEFAULT_MIN_WATER_OCCURRENCE_PCT,
    NoCloudFreeImageryError,
    NoWaterPixelsError,
    _cloud_flag_image,
    _water_mask_image,
    default_max_scene_age_days,
)

# The four indices, as `ee.Image` band math over the masked Sentinel-2
# bands. Same formulas as detection/src/indices.py evaluates on scalar
# band means -- that module stays the written definition of each index;
# these are the per-pixel form of the identical arithmetic:
#     ndci  = (B5 - B4) / (B5 + B4)   -> ee.Image.normalizedDifference
#     bda2  = B5 / B4
#     bda3  = (1/B4 - 1/B5) * B6
#     b2_b3 = B2 / B3
# Named without a leading digit ("bda2", not "2bda") because GEE band
# names must be valid identifiers; the mapping to detection/'s "2bda" /
# "3bda" keys is one rename at whichever layer joins them, not a
# different quantity.
RASTER_INDEX_BANDS: tuple[str, str, str, str] = ("ndci", "bda2", "bda3", "b2_b3")

# Per-cell acquisition time of the scene that supplied that cell -- epoch
# milliseconds UTC, exactly as Sentinel-2's `system:time_start` reports
# it. Never derived, never rounded to a day, never backfilled from the
# requested date.
RASTER_DATE_BAND = "date_ms"

RASTER_BAND_ORDER: tuple[str, ...] = (*RASTER_INDEX_BANDS, RASTER_DATE_BAND)

# GEE's own per-pixel coordinate bands, added at download time only (they
# are not part of the composite). Taking the coordinates from the server's
# projection rather than reconstructing the grid client-side from a
# bounding box and a scale means a cell's stated position is the position
# GEE actually computed it at, with no chance of a half-cell offset.
LONGITUDE_BAND = "longitude"
LATITUDE_BAND = "latitude"

# --------------------------------------------------------------------------
# Band -> reducer policy. The single most important constant in this file.
# --------------------------------------------------------------------------
#
# Read this as: "when values from more than one native pixel have to
# become one number, this is how each band is allowed to be combined."
#
# The index bands are continuous physical ratios; a mean over the cell is
# the honest average over the cells a summary covers. (This governs the
# retained summary only -- see the module docstring: GEE's own read is a
# nearest-neighbour sample and consults nothing here.)
#
# The date band is NOT continuous. It is a label naming a real satellite
# pass. Averaging two labels invents a third that names nothing -- the
# same class of error this project has repeatedly removed elsewhere (a
# spectral-index anomaly scored against a chlorophyll-concentration
# baseline; a cluster given one date when its members came from scenes
# ten days apart). `mode` picks the acquisition that actually supplied
# most of the cell; on a tie it takes the newer one (see `_reduce_mode`).
# `max` -- "the newest scene contributing to this cell" -- is the only
# other defensible choice. `mean` is never acceptable here, and
# `download_composite_arrays` will raise rather than store a date that is
# not one of the composite's own source timestamps.
RASTER_BAND_REDUCERS: dict[str, str] = {
    "ndci": "mean",
    "bda2": "mean",
    "bda3": "mean",
    "b2_b3": "mean",
    RASTER_DATE_BAND: "mode",
}

# Reducers that must never be applied to `RASTER_DATE_BAND`. Stated as
# data so the rule is checkable, not just described in prose.
FABRICATING_REDUCERS: frozenset[str] = frozenset({"mean", "median", "sum"})

# Default read scale. Measured live over the study polygon: 200 m gave
# 49,607 valid water cells and a ~9.2 MB NPY transfer in ~10 s; 100 m gave
# 196,424 cells and 36.8 MB. 200 m is the default because it is the
# coarsest scale that still resolves a bloom patch of a few hundred
# metres, and because quadrupling the transfer for a regional overview
# buys detail the truth boundary above says should not be over-read
# anyway. Overridable per call, and by the backend via RASTER_SCAN_SCALE_M.
DEFAULT_RASTER_SCALE_M = 200

# A full-polygon NPY at 200 m is ~9 MB and at 100 m ~37 MB; this is a bulk
# transfer, not the thumbnail fetch imagery.py does, so the timeout is
# correspondingly longer.
DEFAULT_DOWNLOAD_TIMEOUT_S = 300

# Epoch ms of a real Sentinel-2 acquisition is ~1.79e12 and can never be
# 0: 1970-01-01 predates the mission by 45 years. GEE's NPY export writes
# 0 into masked pixels, so `date_ms > 0` is the validity test for a cell,
# and it is the date band that decides it -- an index band's 0 is a
# legitimate reading, not a mask.
_MASKED_FILL = 0.0


class FabricatedDateError(RuntimeError):
    """A returned cell date is not one of the composite's own source
    acquisitions -- i.e. something averaged or interpolated the date band
    on the way back. Raised instead of returning the value, because a
    fabricated acquisition date is worse than no raster at all."""


class DateBandPrecisionError(RuntimeError):
    """The date band arrived in a dtype too narrow to carry epoch
    milliseconds exactly (float32 holds ~7 significant digits; epoch ms
    needs 13, and float32's spacing at 1.79e12 is 131,072 ms). Raised
    rather than accepted, because the loss is silent: the value still
    looks like a plausible timestamp, it just no longer equals the
    acquisition it came from."""


# --------------------------------------------------------------------------
# Pure aggregation -- no `ee`, no network. Used for the retained summary a
# raster is reduced to once its full blob is deleted, and reused by the
# test suite's `ee` double so the policy above is exercised, not just
# asserted.
# --------------------------------------------------------------------------


def _reduce_mean(values: np.ndarray) -> float:
    """Mean of a continuous band over the retained cells. Meaningful for
    the indices; never applied to the date band."""
    return float(np.mean(values))


def _reduce_mode(values: np.ndarray) -> Any:
    """Most frequent value; ties broken toward the LARGER value.

    For `date_ms` that means: the acquisition that supplied most of the
    cell wins, and an exact tie goes to the newer pass. The returned
    value is always one of the inputs -- that is the whole point, and it
    is what separates this from `mean`.
    """
    uniques, counts = np.unique(values, return_counts=True)
    best = counts.max()
    return uniques[counts == best].max()


def _reduce_max(values: np.ndarray) -> Any:
    """Largest input value. For `date_ms`: the newest acquisition
    contributing to the cell. Also always one of the inputs."""
    return values.max()


NUMPY_BAND_REDUCERS = {
    "mean": _reduce_mean,
    "mode": _reduce_mode,
    "max": _reduce_max,
}


def summarize_raster_cells(arrays: dict[str, np.ndarray]) -> dict:
    """Reduce a whole raster to one row, applying `RASTER_BAND_REDUCERS`.

    This is what a raster is kept as after its full blob is deleted by
    the backend's retention policy (`backend/src/raster_scan/storage.py`),
    so it must not quietly change meaning: the reducer each band was
    aggregated with is returned alongside the values, so a reader of an
    old summary can see for themselves that the date was selected and not
    averaged.

    Args:
        arrays: `{band: 1-D np.ndarray}` as returned by
            `download_composite_arrays` (one entry per valid cell).

    Returns:
        {
          "cell_count": int,
          "bands": {band: float | int},   # per RASTER_BAND_REDUCERS
          "reducers": {band: str},        # provenance, stored with it
        }
        `{"cell_count": 0, "bands": {}, "reducers": {...}}` for an empty
        raster -- an empty input is summarised as empty, never as zero
        readings.
    """
    cell_count = int(len(arrays[RASTER_DATE_BAND])) if RASTER_DATE_BAND in arrays else 0
    reducers = {band: RASTER_BAND_REDUCERS[band] for band in RASTER_BAND_ORDER}
    if cell_count == 0:
        return {"cell_count": 0, "bands": {}, "reducers": reducers}

    bands: dict[str, Any] = {}
    for band in RASTER_BAND_ORDER:
        values = np.asarray(arrays[band])
        reduced = NUMPY_BAND_REDUCERS[RASTER_BAND_REDUCERS[band]](values)
        # int for the date (it is a timestamp, and JSON has no int64),
        # float for the indices.
        bands[band] = int(reduced) if band == RASTER_DATE_BAND else float(reduced)
    return {"cell_count": cell_count, "bands": bands, "reducers": reducers}


# --------------------------------------------------------------------------
# GEE-backed composite.
# --------------------------------------------------------------------------


def _index_bands(image: ee.Image, water_mask: ee.Image, cloud_classes: tuple) -> ee.Image:
    """One acquisition's four index bands plus its `date_ms` band.

    Masking happens BEFORE the arithmetic -- `updateMask` on the raw
    B2-B6 selection, not on the computed indices. It matters: a ratio
    computed first and masked second still evaluates over cloud and land
    on the way through, and a division by a near-zero land or cloud pixel
    can produce a huge finite value that survives as a neighbour's
    contribution once the read is coarsened. Masking first means those
    pixels never enter any arithmetic at all.

    `date_ms` is `ee.Image.constant(system:time_start)` carrying this
    scene's acquisition time across the whole scene, masked to exactly
    the pixels the indices survived at (`ndci.mask()`), so a cell's date
    and its readings can never come from different scenes.
    """
    bands = (
        image.select(list(BANDS))
        .updateMask(water_mask)
        .updateMask(_cloud_flag_image(image, cloud_classes).Not())
        # Cast after masking, before arithmetic: S2_SR_HARMONIZED bands
        # are integers, and an integer reciprocal (1/B4 for 3BDA) would
        # truncate to zero.
        .toFloat()
    )
    b2 = bands.select("B2")
    b3 = bands.select("B3")
    b4 = bands.select("B4")
    b5 = bands.select("B5")
    b6 = bands.select("B6")
    one = ee.Image.constant(1.0)

    ndci = bands.normalizedDifference(["B5", "B4"]).rename("ndci")
    bda2 = b5.divide(b4).rename("bda2")
    bda3 = one.divide(b4).subtract(one.divide(b5)).multiply(b6).rename("bda3")
    b2_b3 = b2.divide(b3).rename("b2_b3")

    date_ms = (
        ee.Image.constant(ee.Number(image.get("system:time_start")))
        .toDouble()
        .rename(RASTER_DATE_BAND)
        .updateMask(ndci.mask())
    )
    return ndci.addBands(bda2).addBands(bda3).addBands(b2_b3).addBands(date_ms)


def build_index_composite(
    polygon_latlng: tuple[tuple[float, float], ...],
    date: str,
    max_scene_age_days: int | None = None,
    cloud_classes: tuple = DEFAULT_CLOUD_CLASSES,
    min_water_occurrence_pct: float = DEFAULT_MIN_WATER_OCCURRENCE_PCT,
) -> dict[str, Any]:
    """Most-recent-wins index composite over a polygon, as of `date`.

    Every Sentinel-2 acquisition intersecting the polygon in the window
    [`date` - `max_scene_age_days`, `date`] contributes its cloud- and
    land-masked index bands; `mosaic()` over the time-sorted collection
    keeps the newest unmasked value per pixel. No scene is rejected
    wholesale on cloud fraction, unlike the point path
    (`sentinel2._resolve_sentinel2_scene`): at polygon extent a "cloudy"
    scene is normally clear somewhere, and per-pixel masking already
    excludes the parts that are not.

    Args:
        polygon_latlng: (lat, lng) vertices in order, implicitly closed
            (e.g. `study_area.STUDY_AREA_POLYGON_LATLNG`).
        date: "YYYY-MM-DD", read as "as of this day" -- exactly as
            `get_sentinel2_bands` reads it. Acquisitions after this day
            are never candidates, at any distance.
        max_scene_age_days: how far back the window reaches. Defaults to
            `default_max_scene_age_days()`, the one system-wide ceiling
            (`SENTINEL2_MAX_SCENE_AGE_DAYS`) -- this module deliberately
            does not introduce a second, raster-specific staleness
            policy that could disagree with the point path's.
        cloud_classes, min_water_occurrence_pct: passed straight to
            `sentinel2._cloud_flag_image` / `_water_mask_image`.

    Returns:
        {
          "image": ee.Image,              # RASTER_BAND_ORDER, masked
          "region": ee.Geometry,          # the polygon, for the read
          "scene_ids": tuple[str, ...],
          "scene_timestamps_ms": tuple[int, ...],   # ascending
          "target_date": str,
          "window_start": str, "window_end": str,   # end exclusive
          "max_scene_age_days": int,
          "band_order": tuple[str, ...],
        }
        `scene_timestamps_ms` is the closed set of dates any cell is
        allowed to carry -- `download_composite_arrays` checks against it.

    Raises:
        GEEAuthError: GEE not authenticated (propagated, never caught).
        NoCloudFreeImageryError: no Sentinel-2 scene at all intersects
            the polygon inside the window. Reported, never filled in.
    """
    initialize_ee()

    if max_scene_age_days is None:
        max_scene_age_days = default_max_scene_age_days()

    ring = [[lng, lat] for lat, lng in polygon_latlng]
    region = ee.Geometry.Polygon([ring])

    requested = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    window_start = (requested - timedelta(days=max_scene_age_days)).strftime("%Y-%m-%d")
    # filterDate's end is exclusive; +1 day keeps the requested day's own
    # acquisitions and admits nothing later (same rule as sentinel2.py).
    window_end = (requested + timedelta(days=1)).strftime("%Y-%m-%d")

    collection = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(region)
        .filterDate(window_start, window_end)
        # Ascending, because mosaic() keeps the LAST unmasked value it
        # sees -- so "sorted oldest first" is what makes it newest-wins.
        .sort("system:time_start")
    )

    # One round trip for the scene inventory. It is not optional
    # bookkeeping: it is the allow-list the returned dates are checked
    # against below, so a fabricated date has something to fail against.
    meta = ee.Dictionary({
        "ids": collection.aggregate_array("system:index"),
        "times": collection.aggregate_array("system:time_start"),
    }).getInfo()
    scene_ids = tuple(meta["ids"])
    scene_timestamps = tuple(int(t) for t in meta["times"])
    if not scene_timestamps:
        raise NoCloudFreeImageryError(
            f"No Sentinel-2 scenes intersect the polygon between {window_start} "
            f"and {window_end} (as of {date}, ceiling {max_scene_age_days} days)."
        )

    water_mask = _water_mask_image(min_water_occurrence_pct).selfMask()
    composite = collection.map(
        lambda image: _index_bands(ee.Image(image), water_mask, cloud_classes)
    ).mosaic()

    return {
        "image": composite,
        "region": region,
        "scene_ids": scene_ids,
        "scene_timestamps_ms": scene_timestamps,
        "target_date": date,
        "window_start": window_start,
        "window_end": window_end,
        "max_scene_age_days": max_scene_age_days,
        "band_order": RASTER_BAND_ORDER,
    }


def _fetch_npy_bytes(url: str, timeout_s: float = DEFAULT_DOWNLOAD_TIMEOUT_S) -> bytes:
    """Fetch a GEE download URL's bytes server-side.

    Same boundary rule as `imagery.py`'s `_fetch_thumb_bytes`: only
    `data-pipeline` fetches from GEE-hosted URLs, so no signed,
    time-limited URL is ever handed to a downstream project. Network
    failures (`urllib.error.URLError`/`HTTPError`) propagate unwrapped --
    a failed transfer is a distinct condition from "GEE has no usable
    data here", which has its own typed errors.
    """
    with urllib.request.urlopen(url, timeout=timeout_s) as response:  # noqa: S310 -- GEE-issued download URL, not user input
        return response.read()


def download_composite_arrays(
    composite: dict[str, Any],
    scale_m: int = DEFAULT_RASTER_SCALE_M,
    timeout_s: float = DEFAULT_DOWNLOAD_TIMEOUT_S,
) -> dict[str, Any]:
    """Read a composite at `scale_m` as flat numpy arrays of valid cells.

    Coarsening from the native 10/20 m to `scale_m` is done by GEE's
    implicit pyramiding -- the scale is simply requested. An explicit
    `reduceResolution` fails at polygon extent ("Reprojection output too
    large") and is deliberately not attempted.

    The transfer is a rectangular grid over the polygon's bounding box,
    masked cells included (that is why a 200 m read moves ~9 MB for
    ~50,000 usable cells); this function returns only the valid ones,
    flattened, each with its own coordinates and its own acquisition date.

    Args:
        composite: the dict `build_index_composite` returned. Passed
            whole rather than as a bare image because the date guard
            needs `scene_timestamps_ms`.
        scale_m: read scale in metres (default `DEFAULT_RASTER_SCALE_M`).
        timeout_s: transfer timeout.

    Returns:
        {
          "lat": np.ndarray[float64], "lng": np.ndarray[float64],
          "ndci": np.ndarray[float32], "bda2": ..., "bda3": ..., "b2_b3": ...,
          "date_ms": np.ndarray[int64],      # exact epoch ms, never rounded
          "scale_m": int,
          "cell_count": int,                 # valid cells returned
          "grid_shape": tuple[int, int],     # full transferred grid
          "scene_timestamps_ms": tuple[int, ...],
        }

    Raises:
        GEEAuthError: propagated.
        NoWaterPixelsError: every cell in the polygon was masked (cloud,
            land, or no scene coverage). An honest empty answer, not an
            error condition to paper over.
        DateBandPrecisionError: the date band came back narrower than
            float64, so epoch ms cannot be represented exactly.
        FabricatedDateError: a cell carries a date that is not one of the
            composite's source acquisitions -- something averaged or
            interpolated it.
    """
    image = composite["image"].addBands(ee.Image.pixelLonLat())
    url = image.getDownloadURL({
        "region": composite["region"],
        "scale": scale_m,
        "format": "NPY",
    })
    grid = np.load(io.BytesIO(_fetch_npy_bytes(url, timeout_s)))

    # Guard 1 (narrowing). float32 carries ~7 significant digits; epoch
    # ms needs 13. Checked before any value is read out, because after a
    # narrowing cast the damage is indistinguishable from a real date.
    date_dtype = grid.dtype[RASTER_DATE_BAND]
    if date_dtype != np.float64 and date_dtype != np.int64:
        raise DateBandPrecisionError(
            f"{RASTER_DATE_BAND} arrived as {date_dtype}, which cannot represent "
            "epoch milliseconds (~1.79e12) exactly -- float32's spacing there is "
            "131,072 ms, so every acquisition time shifts by up to ~65 s and stops "
            "matching its own scene. Expected float64 or int64; the band is built "
            "with .toDouble() for exactly this reason."
        )

    raw_dates = np.asarray(grid[RASTER_DATE_BAND], dtype=np.float64)
    valid = np.isfinite(raw_dates) & (raw_dates > _MASKED_FILL)
    cell_count = int(valid.sum())
    if cell_count == 0:
        raise NoWaterPixelsError(
            "No cell in the polygon survived the combined cloud+water mask at "
            f"{scale_m} m for {composite['target_date']} "
            f"({len(composite['scene_timestamps_ms'])} scenes in the window)."
        )

    dates = np.rint(raw_dates[valid]).astype(np.int64)

    # Guard 2 (fabrication). Every date must be a scene that actually
    # flew. A mean of two acquisitions lands between them and is caught
    # here; so is an interpolated or resampled date.
    allowed = set(composite["scene_timestamps_ms"])
    unexpected = sorted(set(dates.tolist()) - allowed)
    if unexpected:
        shown = ", ".join(
            datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()
            for ms in unexpected[:3]
        )
        raise FabricatedDateError(
            f"{len(unexpected)} cell date(s) match no source acquisition "
            f"(e.g. {shown}). The composite's scenes are "
            f"{composite['scene_timestamps_ms']}. A date between two "
            "acquisitions means the band was averaged -- see "
            "RASTER_BAND_REDUCERS; it must never be reduced with "
            f"{sorted(FABRICATING_REDUCERS)}."
        )

    arrays: dict[str, Any] = {
        "lat": np.asarray(grid[LATITUDE_BAND], dtype=np.float64)[valid],
        "lng": np.asarray(grid[LONGITUDE_BAND], dtype=np.float64)[valid],
        RASTER_DATE_BAND: dates,
    }
    for band in RASTER_INDEX_BANDS:
        arrays[band] = np.asarray(grid[band], dtype=np.float32)[valid]

    arrays["scale_m"] = int(scale_m)
    arrays["cell_count"] = cell_count
    arrays["grid_shape"] = tuple(int(n) for n in grid.shape)
    arrays["scene_timestamps_ms"] = composite["scene_timestamps_ms"]
    return arrays
