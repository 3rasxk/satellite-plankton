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
`masked_band_mean`) operating on plain numpy arrays, so they are
unit-testable against synthetic pixel data without a live Earth Engine
session. Only `get_sentinel2_bands` itself talks to GEE.
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


# --------------------------------------------------------------------------
# GEE-backed extraction.
# --------------------------------------------------------------------------


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
        cloud_mask = ~np.isin(np.asarray(scl_values), DEFAULT_CLOUD_CLASSES)
        water_mask = water_pixel_mask(occurrence_values, DEFAULT_MIN_WATER_OCCURRENCE_PCT)
        combined_mask = cloud_mask & water_mask[: cloud_mask.size]

        try:
            band_means = {
                band: masked_band_mean(sample.get(band, []), combined_mask)
                for band in BANDS
            }
        except NoWaterPixelsError as exc:
            best_error = exc
            continue

        actual_date = datetime.fromtimestamp(time_start_ms / 1000, tz=timezone.utc).strftime(
            "%Y-%m-%d"
        )
        return {
            **band_means,
            "cloud_fraction": cloud_fraction,
            "actual_date": actual_date,
        }

    # Every candidate in the window was rejected.
    raise best_error or NoCloudFreeImageryError(
        f"No usable Sentinel-2 image for ({lat}, {lng}) within "
        f"{search_window_days} days of {date}."
    )
