"""
Per-cell seasonal NDCI history statistics over the study polygon -- the
input for the Level B (per-cell) TEST baseline.

Data source: Copernicus Sentinel-2 Level-2A surface reflectance,
`COPERNICUS/S2_SR_HARMONIZED`, via Google Earth Engine, masked by exactly
the production raster's rule: `raster._index_bands` (the same function the
served raster composite maps over its scenes), which in turn applies
`sentinel2._water_mask_image` (JRC Global Surface Water with the ETOPO1
fallback) and `sentinel2._cloud_flag_image` (Scene Classification Layer
classes `sentinel2.DEFAULT_CLOUD_CLASSES`). Nothing in the masking or the
index arithmetic is re-implemented here.

What one stored cell is: for one calendar-month season window (the three
months `detection/src/baseline.py`'s `season_months(M)` gives for a target
month M) and one pixel of the raster grid, the median, the MAD and the
count of that pixel's DAILY NDCI values over `[start, end)`. A daily value
is the per-day mosaic of every Sentinel-2 tile acquired on that UTC date
(overlapping tiles of one pass are the same acquisition, so one value per
date, not one per tile). The grid is the one the production raster is read
on: the polygon requested at `scale_m` (default
`raster.DEFAULT_RASTER_SCALE_M`, 200 m), so each cell is one nearest-
neighbour native pixel per day -- the same sampling as a production cell,
which is what makes the two comparable at all.

Cell identity: the coordinates are Earth Engine's own `pixelLonLat` values
for the grid it read. Both this grid and the production raster's are
EPSG:4326 reads of a composite at the same `scale_m`, and their centres fall
on the same lattice; `detection/src/baseline.py`'s `cell_key` turns a
coordinate into that lattice's integer index, so a production cell and its
baseline cell are matched by key, never by array position.

Statistics (computed server-side by Earth Engine, not here):
  - median = `ee.Reducer.median()` over the daily values (exact for up to
    1,000 inputs per pixel -- GEE's `maxRaw` default -- which a 3-month
    window of a 5-day revisit never approaches);
  - MAD = the same median reducer over |daily - median|;
  - n = `ee.Reducer.count()`, the number of dates with a valid pixel.

Limitations -- read before using any of this as evidence:
  - TEST statistics, not a calibrated baseline. Nothing here has been
    checked against recorded bloom events; a past bloom inside the window
    widens the MAD and hides later anomalies.
  - Single sampled pixels. A 200 m cell is one 10/20 m pixel per day, not
    an area mean; a feature smaller than the sampling interval is hit or
    missed outright. Detection is at pixel resolution: water-colour
    signatures only, never individual organisms, and small or dispersed
    blooms can be missed.
  - Clear-sky days only, decided per pixel. Days the pixel was cloudy do
    not count, so the record over-represents calm, clear weather; during
    the southwest monsoon a cell's history can be thin (its `n` says how
    thin). Absence of a value is not evidence of an absent bloom.
  - Turbid river-mouth and shallow water raise NDCI with no bloom; the
    JRC/ETOPO1 water mask is least trustworthy exactly there.
  - Dimensionless index readings, not chlorophyll concentrations.

Everything that touches `ee` lives in `_fetch_cell_stats`. The rest --
`cell_baseline_params`, `polygon_id`, `cells_from_grid` and the checks in
`build_cell_baseline` -- is pure and offline-testable.
"""

from __future__ import annotations

import hashlib
import io
import json
from datetime import date
from typing import Callable

import ee
import numpy as np

from . import raster, sentinel2
from .auth import initialize_ee
from .history import NDCI_DEFINITION, S2_COLLECTION
from .study_area import STUDY_AREA_POLYGON_LATLNG

CELL_SAMPLING_DEFINITION = "raster-nearest-native-pixel-per-day-mosaic"
PER_DAY_REDUCTION_DEFINITION = "mosaic of same-UTC-date tiles"
STATISTIC_DEFINITION = "median / MAD(median of |x-median|) over daily values"
SCENE_FILTER_DEFINITION = "none: per-pixel cloud+water mask only, as the raster composite"
GRID_DEFINITION = "EPSG:4326 read at scale_m over the polygon; pixelLonLat cell centres"

# Fields of the structured grid `_fetch_cell_stats` returns (and any test
# double must return): the three statistics plus GEE's own coordinates.
GRID_FIELDS: tuple[str, ...] = (
    "median",
    "mad",
    "n",
    raster.LONGITUDE_BAND,
    raster.LATITUDE_BAND,
)

# uint16 is the stored dtype of `n`; a 3-month window over ~9 years at a
# 5-day revisit is a few hundred dates, far below this.
_MAX_COUNT = int(np.iinfo(np.uint16).max)

# (structured grid, sorted distinct acquisition dates "YYYY-MM-DD" in the window)
FetchCells = Callable[
    [tuple, tuple[int, int, int], str, str, int], tuple[np.ndarray, list[str]]
]


def polygon_id(polygon_latlng) -> str:
    """First 16 hex chars of SHA-256 over the polygon's (lat, lng) vertices.

    Vertex order matters (it is a different ring); tuple vs list does not.
    """
    vertices = [[float(lat), float(lng)] for lat, lng in polygon_latlng]
    canonical = json.dumps(vertices, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()[:16]


def cell_baseline_params(
    scale_m: int = raster.DEFAULT_RASTER_SCALE_M,
    polygon_latlng=STUDY_AREA_POLYGON_LATLNG,
) -> dict:
    """Canonical description of how the per-cell statistics are produced.

    Built from the *live* constants in `sentinel2` on every call (module
    attribute lookups, not names bound at import), so changing the cloud
    classes, the water-occurrence threshold, the band set, the read scale or
    the polygon changes the returned dict and therefore the cell baseline's
    preprocessing signature. Deliberately different from
    `history.preprocessing_params()` (point-buffer means at 10 m): a cell
    baseline must never be mistaken for, or mixed with, a site baseline.

    Returns plain JSON types and a fresh dict each time.
    """
    return {
        "collection": S2_COLLECTION,
        "bands": list(sentinel2.BANDS),
        "cloud_classes": list(sentinel2.DEFAULT_CLOUD_CLASSES),
        "min_water_occurrence_pct": sentinel2.DEFAULT_MIN_WATER_OCCURRENCE_PCT,
        "water_mask_assets": [sentinel2.JRC_GSW_ASSET, sentinel2.ETOPO1_ASSET],
        "scale_m": int(scale_m),
        "grid": GRID_DEFINITION,
        "sampling": CELL_SAMPLING_DEFINITION,
        "index": NDCI_DEFINITION,
        "per_day_reduction": PER_DAY_REDUCTION_DEFINITION,
        "statistic": STATISTIC_DEFINITION,
        "scene_filter": SCENE_FILTER_DEFINITION,
        "polygon_id": polygon_id(polygon_latlng),
    }


def _check_months(months) -> tuple[int, int, int]:
    values = tuple(months)
    if (
        len(values) != 3
        or not all(isinstance(m, int) and not isinstance(m, bool) for m in values)
        or not all(1 <= m <= 12 for m in values)
        or len(set(values)) != 3
    ):
        raise ValueError(f"months must be three distinct calendar months 1..12, got {months!r}")
    return values


def _check_window(start: str, end: str) -> tuple[date, date]:
    try:
        first = date.fromisoformat(start)
        stop = date.fromisoformat(end)
    except (TypeError, ValueError):
        raise ValueError(f"start/end must be ISO dates, got {start!r}, {end!r}") from None
    if first >= stop:
        raise ValueError(f"start {start} must be before end {end} (end is exclusive)")
    return first, stop


def cells_from_grid(grid: np.ndarray) -> dict[str, np.ndarray]:
    """Flatten a structured statistics grid to the valid cells, storage dtypes.

    Pure. A cell is kept when it has at least one dated observation
    (`n >= 1`) and a finite median and a finite, non-negative MAD. Earth
    Engine's NPY export writes 0 into masked pixels in every band, so the
    COUNT decides validity, never the median: 0.0 is an ordinary NDCI
    reading. Order is the grid's row-major order.

    Returns `{"lat", "lng": float64, "median", "mad": float32, "n": uint16}`.

    Raises:
        ValueError: a field is missing, a count is not a whole number, or a
            count does not fit uint16.
    """
    names = grid.dtype.names or ()
    missing = [name for name in GRID_FIELDS if name not in names]
    if missing:
        raise ValueError(f"cell statistics grid lacks field(s) {missing}; has {list(names)}")

    flat = np.asarray(grid).reshape(-1)
    median = np.asarray(flat["median"], dtype=np.float64)
    mad = np.asarray(flat["mad"], dtype=np.float64)
    n = np.asarray(flat["n"], dtype=np.float64)
    lat = np.asarray(flat[raster.LATITUDE_BAND], dtype=np.float64)
    lng = np.asarray(flat[raster.LONGITUDE_BAND], dtype=np.float64)

    with np.errstate(invalid="ignore"):
        valid = (
            np.isfinite(n) & (n >= 1)
            & np.isfinite(median)
            & np.isfinite(mad) & (mad >= 0)
            & np.isfinite(lat) & np.isfinite(lng)
        )
    counts = n[valid]
    if counts.size and not np.all(counts == np.round(counts)):
        raise ValueError("cell counts must be whole numbers of dates")
    if counts.size and counts.max() > _MAX_COUNT:
        raise ValueError(f"cell count {int(counts.max())} does not fit uint16")

    return {
        "lat": lat[valid],
        "lng": lng[valid],
        "median": median[valid].astype(np.float32),
        "mad": mad[valid].astype(np.float32),
        "n": counts.astype(np.uint16),
    }


def _fetch_cell_stats(
    polygon_latlng: tuple,
    months: tuple[int, int, int],
    start: str,
    end: str,
    scale_m: int,
    timeout_s: float = raster.DEFAULT_DOWNLOAD_TIMEOUT_S,
) -> tuple[np.ndarray, list[str]]:
    """Per-pixel median / MAD / count of daily NDCI for one season window.

    The only function in this module that talks to Earth Engine (verified
    live in the Task 11 spike: one season window, ~140 dates, 618 x 620
    grid at 200 m, 27 s). Steps, all server-side:

      1. Sentinel-2 SR scenes intersecting the polygon in `[start, end)`
         (`filterDate`, end exclusive) whose calendar month is one of
         `months` (`ee.Filter.calendarRange` per month, OR-ed, so the
         December-January wrap needs no special case).
      2. The distinct UTC acquisition dates of those scenes.
      3. Per date: every scene of that UTC day, time-sorted, mapped through
         `raster._index_bands` with the production water mask and cloud
         classes, `mosaic()`-ed, NDCI band only -- one image per date.
      4. median, MAD (median of |daily - median|) and count over the daily
         images; `ee.Image.pixelLonLat()` for the coordinates (float64).
      5. One NPY download of the polygon at `scale_m`, the same request
         shape as `raster.download_composite_arrays`.

    Returns `(structured grid, sorted distinct dates)`. An empty window
    returns an empty grid and no dates, without a download.

    Raises:
        GEEAuthError: GEE not authenticated (propagated, never swallowed).
    """
    initialize_ee()

    ring = [[lng, lat] for lat, lng in polygon_latlng]
    region = ee.Geometry.Polygon([ring])
    month_filter = ee.Filter.Or(
        *[ee.Filter.calendarRange(month, month, "month") for month in months]
    )
    collection = (
        ee.ImageCollection(S2_COLLECTION)
        .filterBounds(region)
        .filterDate(start, end)
        .filter(month_filter)
    )

    # Read at call time so the computation is exactly what
    # cell_baseline_params() reports.
    water_mask = sentinel2._water_mask_image(
        sentinel2.DEFAULT_MIN_WATER_OCCURRENCE_PCT
    ).selfMask()
    cloud_classes = tuple(sentinel2.DEFAULT_CLOUD_CLASSES)

    days = (
        ee.List(collection.aggregate_array("system:time_start"))
        .map(lambda t: ee.Date(t).format("YYYY-MM-dd"))
        .distinct()
    )
    dates = sorted(str(d) for d in days.getInfo())
    if not dates:
        return np.zeros(0, dtype=[(name, "<f8") for name in GRID_FIELDS]), []

    def per_day(day):
        day_start = ee.Date(ee.String(day))
        day_images = (
            collection.filterDate(day_start, day_start.advance(1, "day"))
            .sort("system:time_start")
            .map(lambda image: raster._index_bands(ee.Image(image), water_mask, cloud_classes))
        )
        return day_images.mosaic().select("ndci").set("system:time_start", day_start.millis())

    daily = ee.ImageCollection(days.map(per_day))
    median = daily.reduce(ee.Reducer.median())
    mad = daily.map(lambda image: ee.Image(image).subtract(median).abs()).reduce(
        ee.Reducer.median()
    )
    count = daily.reduce(ee.Reducer.count())
    stats = (
        median.rename("median")
        .addBands(mad.rename("mad"))
        .toFloat()
        .addBands(count.rename("n").toInt32())
        .addBands(ee.Image.pixelLonLat())
    )
    url = stats.getDownloadURL({"region": region, "scale": scale_m, "format": "NPY"})
    grid = np.load(io.BytesIO(raster._fetch_npy_bytes(url, timeout_s)), allow_pickle=False)
    return grid, dates


def build_cell_baseline(
    polygon_latlng,
    months,
    start: str,
    end: str,
    scale_m: int = raster.DEFAULT_RASTER_SCALE_M,
    *,
    _fetch: FetchCells | None = None,
) -> dict:
    """Per-cell NDCI season statistics over `[start, end)` (end exclusive).

    Args:
        polygon_latlng: (lat, lng) vertices, implicitly closed (normally
            `study_area.STUDY_AREA_POLYGON_LATLNG`, the raster's polygon).
        months: the three calendar months of the season window, e.g.
            `baseline.season_months(10) == (9, 10, 11)`.
        start, end: ISO dates; `end` is exclusive, like `filterDate`.
        scale_m: read scale; must equal the production raster's
            (`RASTER_SCAN_SCALE_M`) for the cells to be comparable.
        _fetch: test seam with `_fetch_cell_stats`'s signature.

    Returns:
        {"lat", "lng": float64[N], "median", "mad": float32[N],
         "n": uint16[N], "scale_m": int, "months": [m1, m2, m3],
         "start": str, "end": str, "n_dates": int,
         "first_date": str | None, "last_date": str | None}
        One entry per cell with n >= 1 and finite statistics (see
        `cells_from_grid`). `n_dates` counts the distinct acquisition
        dates in the window over the whole polygon; a cell's own `n` is
        how many of them gave it a clear water pixel.

    Raises:
        ValueError: bad months or window; the fetch reported a date outside
            `[start, end)` or outside the months (that would put the future,
            or another season, into the baseline); a cell counts more dates
            than the window has; malformed grid (see `cells_from_grid`).
        GEEAuthError: default fetch only.
    """
    season = _check_months(months)
    first, stop = _check_window(start, end)
    polygon = tuple((float(lat), float(lng)) for lat, lng in polygon_latlng)

    fetch = _fetch if _fetch is not None else _fetch_cell_stats
    grid, dates = fetch(polygon, season, start, end, int(scale_m))

    parsed = sorted({date.fromisoformat(str(d)) for d in dates})
    outside = [d for d in parsed if not first <= d < stop]
    if outside:
        raise ValueError(
            f"the fetch reported acquisition date(s) outside the window [{start}, {end}): "
            f"{[d.isoformat() for d in outside[:3]]}"
        )
    off_season = [d for d in parsed if d.month not in season]
    if off_season:
        raise ValueError(
            f"the fetch reported acquisition date(s) outside the season months {list(season)}: "
            f"{[d.isoformat() for d in off_season[:3]]}"
        )

    cells = cells_from_grid(grid)
    if cells["n"].size and int(cells["n"].max()) > len(parsed):
        raise ValueError(
            f"a cell counts {int(cells['n'].max())} dates but the window has only "
            f"{len(parsed)} distinct acquisition dates"
        )

    return {
        **cells,
        "scale_m": int(scale_m),
        "months": list(season),
        "start": start,
        "end": end,
        "n_dates": len(parsed),
        "first_date": parsed[0].isoformat() if parsed else None,
        "last_date": parsed[-1].isoformat() if parsed else None,
    }
