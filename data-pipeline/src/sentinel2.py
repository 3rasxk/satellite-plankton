"""
Sentinel-2 band extraction — Gulf of Thailand fine-detail layer.

Data source: Copernicus Sentinel-2 Level-2A surface reflectance,
`COPERNICUS/S2_SR_HARMONIZED`, accessed via Google Earth Engine.
Resolution: 10 m (B2/B3/B4), 20 m (B5/B6), resampled together at a 10 m
scale over a small buffer around the requested point. Revisit ~5 days
(2 satellites) at this latitude, so a cloud-free image is not guaranteed
on the exact requested date.
Limitation: optical sensor — cannot see through cloud, so `actual_date`
may differ from the requested date (nearest usable image within the
search window is used instead, and the caller is told which date that
was). Turbid coastal water near river mouths can still contaminate the
land/water mask; the JRC Global Surface Water "occurrence" layer used
here is a multi-year statistical mask, not today's water extent, so a
newly-exposed mudflat or an unusually low tide is not guaranteed to be
excluded. Detection is at pixel resolution — individual organisms are
never resolved, only water-colour signatures.

Cloud masking and land/water masking are implemented as pure, GEE-free
functions (`compute_cloud_fraction`, `water_pixel_mask`,
`masked_band_mean`, `build_water_cloud_mask`) operating on plain numpy
arrays, so they are unit-testable against synthetic pixel data without a
live Earth Engine session. Only `get_sentinel2_bands` itself talks to GEE.

The candidate search/sort/cloud-check loop lives in one place,
`_resolve_sentinel2_scene`, which `get_sentinel2_bands` wraps. This is
also the function `data-pipeline/src/imagery.py` calls to render the
true-color and NDCI-heatmap panel thumbnails from — reusing this exact
loop (rather than a second, independently written one) is what
guarantees an image and the numeric band reading given for the same
lat/lng/date/window/buffer/cloud-threshold always describe the same
resolved Sentinel-2 scene, never two different candidates. See
`_resolve_sentinel2_scene`'s docstring for the determinism argument.

Known GEE gotcha this module defends against: `reduceRegion` with
`ee.Reducer.toList()` reduces each band of a multi-band image
independently, dropping masked pixels per band rather than keeping
positionally-aligned lists. The JRC `occurrence` band is masked
(no data) over pixels that were never observed as water, so a
land/beach point can return a full-length `SCL` list alongside a short
or empty `occurrence` list. Naively combining a cloud mask and a water
mask built from differently-sized arrays either raises a numpy
broadcast `ValueError` or, worse, silently misaligns pixels. This module
checks array lengths explicitly and raises the typed `NoWaterPixelsError`
instead of guessing.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import ee
import numpy as np

from .auth import initialize_ee

# Sentinel-2 L2A Scene Classification Layer (SCL) values.
# https://sentiwiki.copernicus.eu/web/s2-processing (Scene Classification)
SCL_NO_DATA = 0
SCL_SATURATED_DEFECTIVE = 1
SCL_CLOUD_SHADOW = 3
SCL_UNCLASSIFIED = 7
SCL_CLOUD_MEDIUM_PROB = 8
SCL_CLOUD_HIGH_PROB = 9
SCL_THIN_CIRRUS = 10

# Pixels excluded from a usable reading: no-data, saturated, cloud shadow,
# unclassified, cloud (any confidence), thin cirrus.
DEFAULT_CLOUD_CLASSES = (
    SCL_NO_DATA,
    SCL_SATURATED_DEFECTIVE,
    SCL_CLOUD_SHADOW,
    SCL_UNCLASSIFIED,
    SCL_CLOUD_MEDIUM_PROB,
    SCL_CLOUD_HIGH_PROB,
    SCL_THIN_CIRRUS,
)

BANDS = ("B2", "B3", "B4", "B5", "B6")
DEFAULT_BUFFER_M = 30  # ~3x3 10 m pixels around the point
DEFAULT_SCALE_M = 10
DEFAULT_SEARCH_WINDOW_DAYS = 10
DEFAULT_MAX_CLOUD_FRACTION = 0.5
DEFAULT_MIN_WATER_OCCURRENCE_PCT = 50.0


class NoCloudFreeImageryError(RuntimeError):
    """No Sentinel-2 image within the search window met the cloud-fraction
    threshold at this location. Distinct from GEEAuthError — auth worked,
    the data simply is not usable (e.g. deep monsoon cloud cover)."""


class NoWaterPixelsError(RuntimeError):
    """Every pixel in the sample buffer was classified as land by the
    JRC Global Surface Water occurrence mask — the point is likely on
    shore or the buffer is too small for a coastal location."""


# --------------------------------------------------------------------------
# Pure functions — no `ee` calls, unit-testable with synthetic arrays.
# --------------------------------------------------------------------------


def compute_cloud_fraction(
    scl_values: Any, cloud_classes: tuple = DEFAULT_CLOUD_CLASSES
) -> float:
    """Fraction of pixels in `scl_values` classified as cloud/invalid.

    Pure numpy function — takes a flat array of SCL classification codes
    (as would come from `image.select('SCL').reduceRegion(...).getInfo()`)
    and returns a float in [0, 1]. An empty array is treated as fully
    unusable (fraction 1.0) rather than raising, since "no pixels
    returned" is itself evidence the reading can't be trusted.
    """
    arr = np.asarray(scl_values)
    if arr.size == 0:
        return 1.0
    is_cloud = np.isin(arr, cloud_classes)
    return float(np.count_nonzero(is_cloud) / arr.size)


def water_pixel_mask(
    occurrence_values: Any, min_occurrence_pct: float = DEFAULT_MIN_WATER_OCCURRENCE_PCT
) -> np.ndarray:
    """Boolean water mask from JRC Global Surface Water occurrence values.

    Pure numpy function. `occurrence_values` is percent-of-time-water
    (0-100, as returned by the JRC GSW `occurrence` band); pixels with no
    recorded occurrence (masked/NaN, i.e. never observed as water) are
    treated as land.
    """
    arr = np.asarray(occurrence_values, dtype=float)
    arr = np.nan_to_num(arr, nan=0.0)
    return arr >= min_occurrence_pct


def masked_band_mean(band_values: Any, mask: Any) -> float:
    """Mean of `band_values` restricted to pixels where `mask` is True.

    Pure numpy function shared by cloud masking and land/water masking —
    callers combine both masks before calling this. Raises
    NoWaterPixelsError if the mask excludes every pixel.
    """
    values = np.asarray(band_values, dtype=float)
    keep = np.asarray(mask, dtype=bool)
    if values.shape != keep.shape:
        raise ValueError(
            f"band_values shape {values.shape} != mask shape {keep.shape}"
        )
    kept = values[keep]
    if kept.size == 0:
        raise NoWaterPixelsError(
            "No pixels passed the combined cloud/water mask in this buffer."
        )
    return float(np.nanmean(kept))


def build_water_cloud_mask(
    scl_values: Any,
    occurrence_values: Any,
    cloud_classes: tuple = DEFAULT_CLOUD_CLASSES,
    min_occurrence_pct: float = DEFAULT_MIN_WATER_OCCURRENCE_PCT,
) -> np.ndarray:
    """Combined cloud-clear AND water boolean mask, pure numpy.

    `scl_values` and `occurrence_values` are independent per-band results
    of a GEE `reduceRegion(reducer=ee.Reducer.toList())` call against a
    multi-band image. GEE's `toList` reducer drops masked pixels
    *per band independently*, so the two lists are not guaranteed to be
    the same length or positionally aligned -- most commonly because the
    JRC Global Surface Water `occurrence` band has no data at a land/
    shore pixel (it's a statistical mask defined only over
    historically-water pixels), so a land point can return a full-length
    `SCL` list alongside a short or empty `occurrence` list.

    A length mismatch (including an empty `occurrence_values`) is treated
    the same as "no water pixels found" -- we never guess or pad values
    to force the arrays to align; we raise the same typed error used when
    every pixel is explicitly land, so callers already handling
    `NoWaterPixelsError` (retry next candidate date, or surface the error)
    don't need a second code path.

    Raises:
        NoWaterPixelsError: `occurrence_values` is empty, or its length
            does not match `scl_values`'s length.
    """
    scl_arr = np.asarray(scl_values)
    occurrence_arr = np.asarray(occurrence_values, dtype=float)
    if scl_arr.size == 0 or occurrence_arr.size != scl_arr.size:
        raise NoWaterPixelsError(
            f"Occurrence band returned {occurrence_arr.size} pixel(s) but "
            f"SCL returned {scl_arr.size} -- the sample buffer is likely "
            f"on land/shore, where JRC Global Surface Water has no "
            f"coverage, so reduceRegion's per-band toList reducer dropped "
            f"some or all of the occurrence pixels."
        )
    cloud_mask = ~np.isin(scl_arr, cloud_classes)
    water_mask = water_pixel_mask(occurrence_arr, min_occurrence_pct)
    return cloud_mask & water_mask


# --------------------------------------------------------------------------
# GEE-backed extraction.
# --------------------------------------------------------------------------


def _resolve_sentinel2_scene(
    lat: float,
    lng: float,
    date: str,
    search_window_days: int = DEFAULT_SEARCH_WINDOW_DAYS,
    buffer_m: int = DEFAULT_BUFFER_M,
    max_cloud_fraction: float = DEFAULT_MAX_CLOUD_FRACTION,
) -> dict:
    """Shared candidate-resolution logic: search, sort-by-proximity-to-
    `date`, and cloud/water-check Sentinel-2 candidates until one usable
    scene is found.

    This is the single place that loop lives. `get_sentinel2_bands`
    (numeric path) and `data-pipeline/src/imagery.py` (image-rendering
    path, added for the true-color/NDCI-heatmap panel thumbnails) both
    call this function rather than each running their own copy of the
    search/sort/cloud-check loop — a second, independently written loop
    could drift (different default threshold, different sort, a future
    bugfix applied to only one copy) and end up picking a different
    image than the one the numeric bands came from, which is exactly the
    inconsistency this project cannot tolerate: a caller must never be
    shown a picture from a different date than the numbers next to it.
    Given identical arguments, the underlying GEE query here is
    deterministic (same collection filter + sort + candidate loop), so
    both callers resolving with the same lat/lng/date/window/buffer/
    cloud-threshold land on the same scene by construction, not by luck.

    Returns:
        {
            "image": ee.Image,        # the resolved scene, full band set
            "image_id": str,          # "system:index" of the resolved image
            "region": ee.Geometry,    # the sample buffer used for masking
            "band_means": {B2, B3, B4, B5, B6},  # water/cloud-masked means
            "cloud_fraction": float,
            "actual_date": str,       # "YYYY-MM-DD" of the resolved image
        }

    Raises:
        GEEAuthError: GEE not authenticated.
        NoCloudFreeImageryError: no image in the window met the cloud
            threshold.
        NoWaterPixelsError: the buffer is entirely land per the JRC GSW
            mask (or no usable image was found; see below).
    """
    initialize_ee()

    point = ee.Geometry.Point([lng, lat])
    region = point.buffer(buffer_m)

    requested = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    window_start = (requested - timedelta(days=search_window_days)).strftime("%Y-%m-%d")
    window_end = (requested + timedelta(days=search_window_days + 1)).strftime("%Y-%m-%d")

    collection = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(region)
        .filterDate(window_start, window_end)
        .sort("system:time_start")
    )

    image_ids = collection.aggregate_array("system:index").getInfo()
    if not image_ids:
        raise NoCloudFreeImageryError(
            f"No Sentinel-2 scenes found for ({lat}, {lng}) between "
            f"{window_start} and {window_end}."
        )

    # JRC Global Surface Water: multi-year "how often was this pixel
    # water" mask, independent of any single day's turbidity/cloud.
    water_occurrence_img = ee.Image("JRC/GSW1_4/GlobalSurfaceWater").select("occurrence")

    dated_ids = collection.aggregate_array("system:time_start").getInfo()
    candidates = sorted(
        zip(image_ids, dated_ids),
        key=lambda item: abs(item[1] - requested.timestamp() * 1000),
    )

    best_error: Exception | None = None
    for image_id, time_start_ms in candidates:
        image = ee.Image(f"COPERNICUS/S2_SR_HARMONIZED/{image_id}")
        sample_img = image.select(list(BANDS) + ["SCL"]).addBands(water_occurrence_img)

        sample = sample_img.reduceRegion(
            reducer=ee.Reducer.toList(),
            geometry=region,
            scale=DEFAULT_SCALE_M,
            maxPixels=1e7,
        ).getInfo()

        scl_values = sample.get("SCL", [])
        cloud_fraction = compute_cloud_fraction(scl_values)
        if cloud_fraction > max_cloud_fraction:
            best_error = NoCloudFreeImageryError(
                f"Candidate {image_id} rejected: cloud_fraction={cloud_fraction:.2f} "
                f"> max_cloud_fraction={max_cloud_fraction}."
            )
            continue

        occurrence_values = sample.get("occurrence", [])
        try:
            combined_mask = build_water_cloud_mask(scl_values, occurrence_values)
        except NoWaterPixelsError as exc:
            best_error = exc
            continue

        try:
            band_means = {
                band: masked_band_mean(sample.get(band, []), combined_mask)
                for band in BANDS
            }
        except NoWaterPixelsError as exc:
            best_error = exc
            continue
        except ValueError as exc:
            # A spectral band's toList result came back a different length
            # than the SCL/occurrence-derived mask -- the same per-band
            # independent-masking gotcha `build_water_cloud_mask` guards
            # against, just surfacing on B2-B6 instead of `occurrence`.
            # Treat as an unusable sample for this candidate rather than
            # letting a raw numpy broadcast error escape.
            best_error = NoWaterPixelsError(
                f"Candidate {image_id}: inconsistent per-band pixel counts "
                f"in the sample buffer ({exc}) -- treating as no usable "
                f"water pixels for this date."
            )
            continue

        actual_date = datetime.fromtimestamp(time_start_ms / 1000, tz=timezone.utc).strftime(
            "%Y-%m-%d"
        )
        return {
            "image": image,
            "image_id": image_id,
            "region": region,
            "band_means": band_means,
            "cloud_fraction": cloud_fraction,
            "actual_date": actual_date,
        }

    # Every candidate in the window was rejected.
    raise best_error or NoCloudFreeImageryError(
        f"No usable Sentinel-2 image for ({lat}, {lng}) within "
        f"{search_window_days} days of {date}."
    )


def get_sentinel2_bands(
    lat: float,
    lng: float,
    date: str,
    search_window_days: int = DEFAULT_SEARCH_WINDOW_DAYS,
    buffer_m: int = DEFAULT_BUFFER_M,
    max_cloud_fraction: float = DEFAULT_MAX_CLOUD_FRACTION,
) -> dict:
    """Sentinel-2 surface-reflectance bands at a point, cloud- and
    land-masked, nearest usable date to the one requested.

    Args:
        lat, lng: WGS84 coordinates (upper Gulf of Thailand study area).
        date: requested date, "YYYY-MM-DD". The nearest cloud-free enough
            image within `search_window_days` on either side is used if
            the exact date is unusable.
        search_window_days: how far before/after `date` to search.
        buffer_m: radius (metres) of the sample buffer around the point.
            A small buffer (not a single pixel) avoids one noisy pixel
            dominating the reading.
        max_cloud_fraction: reject candidate images whose SCL cloud
            fraction in the buffer exceeds this.

    Returns:
        {B2, B3, B4, B5, B6, cloud_fraction, actual_date}
        Band values are water-pixel-only means of surface reflectance
        (as stored by S2_SR_HARMONIZED, i.e. scaled reflectance, not yet
        divided by 10000 — callers computing indices should apply that
        scale factor consistently across all bands, which cancels out in
        ratio-based indices like NDCI/2BDA/3BDA).

    Raises:
        GEEAuthError: GEE not authenticated.
        NoCloudFreeImageryError: no image in the window met the cloud
            threshold.
        NoWaterPixelsError: the buffer is entirely land per the JRC GSW
            mask (or no usable image was found; see below).
    """
    resolved = _resolve_sentinel2_scene(
        lat, lng, date, search_window_days, buffer_m, max_cloud_fraction
    )
    return {
        **resolved["band_means"],
        "cloud_fraction": resolved["cloud_fraction"],
        "actual_date": resolved["actual_date"],
    }
