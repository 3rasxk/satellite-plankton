"""
Sentinel-2 band extraction — Gulf of Thailand fine-detail layer.

Data source: Copernicus Sentinel-2 Level-2A surface reflectance,
`COPERNICUS/S2_SR_HARMONIZED`, accessed via Google Earth Engine. Water
masking uses two auxiliary layers: JRC Global Surface Water v1.4
(`JRC/GSW1_4/GlobalSurfaceWater`, `occurrence`) and NOAA ETOPO1
(`NOAA/NGDC/ETOPO1`, `bedrock`).
Resolution: 10 m (B2/B3/B4), 20 m (B5/B6), resampled together at a 10 m
scale over a small buffer around the requested point. Revisit ~5 days
(2 satellites) at this latitude, so a cloud-free image is not guaranteed
on the exact requested date. JRC GSW is 30 m (Landsat-derived); ETOPO1 is
1 arc-minute, roughly 1.85 km at this latitude — far coarser than the
Sentinel-2 pixels it is deciding about.
Limitation: optical sensor — cannot see through cloud, so `actual_date`
routinely differs from the requested date: the newest usable image
acquired on or before that date is used, however old that turns out to
be, and the caller is always told which date it was. An image acquired
*after* the requested date is never used, at any distance — the
requested date means "as of this day". Turbid
coastal water near river mouths can still contaminate the
land/water mask; the JRC Global Surface Water "occurrence" layer used
here is a multi-year statistical mask, not today's water extent, so a
newly-exposed mudflat or an unusually low tide is not guaranteed to be
excluded. The ETOPO1 fallback below is ~1.85 km per cell, so a single
ETOPO1 cell straddles the shoreline — which is exactly why it is only
consulted where JRC has no opinion at all, never to override JRC near
shore. Where JRC happens to be silent *at* the shoreline the fallback is
a ~1.85 km bathymetry cell deciding 10 m pixels, and the resulting
reading can be shoreline-contaminated; see `ETOPO1_ASSET`'s comment for
the measured Ang Sila case. Detection is at pixel resolution —
individual organisms are never resolved, only water-colour signatures.

Water test (per pixel, in `_water_mask_image` / `water_pixel_mask`):
  - JRC `occurrence` HAS data at this pixel -> water iff
    `occurrence >= DEFAULT_MIN_WATER_OCCURRENCE_PCT` (50). JRC stays
    authoritative wherever it has an opinion, because near shore is
    exactly where turbidity and mudflats make a purpose-built water
    product worth trusting over bathymetry.
  - JRC has NO data at this pixel -> water iff ETOPO1 `bedrock < 0`
    (below sea level). Missing bathymetry counts as land.

Why the fallback exists: JRC GSW is a *surface water* product built from
Landsat for inland and coastal water. It has no data over open ocean.
Reading "JRC has no opinion here" as "this is land" meant the further
offshore a point sat, the more certainly it was discarded — backwards for
a marine bloom monitor. Measured against `data/validation/water_mask_truth.json`
(499 upper-Gulf grid points, 400 water / 99 land, truth = NDWI > 0 from a
Cloud Score+ clearest-pixel composite), JRC has zero coverage at 170 of
the 499 buffers and partial coverage at 24 more.

Per-pixel, not per-buffer: JRC's no-data is a per-pixel property (that
pixel was never observed as water in the Landsat archive), so the
fallback is evaluated at the same granularity as the gap. Switching the
whole buffer to ETOPO1 only when JRC covers *nothing* would let a single
JRC-covered pixel at a buffer's edge decide the fate of the 29 pixels JRC
never saw — the same "no opinion = land" error, just at buffer
granularity. On the 499-point fixture the two rules happen to score
identically (no partial-coverage buffer there has a JRC-dry, ETOPO-wet
combination that separates them), so the choice is made on the rule, not
on the fixture.

The candidate search/sort/cloud-check loop lives in one place,
`_resolve_sentinel2_scene`, which `get_sentinel2_bands` wraps. This is
also the function `data-pipeline/src/imagery.py` calls to render the
true-color and NDCI-heatmap panel thumbnails from — reusing this exact
loop (rather than a second, independently written one) is what
guarantees an image and the numeric band reading given for the same
lat/lng/date/max-scene-age/buffer/cloud-threshold always describe the
same resolved Sentinel-2 scene. Numeric and image callers run the one
backward-only selection rule, so that guarantee holds system-wide with
no per-caller exception. See `_resolve_sentinel2_scene`'s docstring for
the determinism argument.

Historical GEE gotcha, now designed out rather than guarded against:
`reduceRegion` with `ee.Reducer.toList()` reduces each band of a
multi-band image independently, dropping masked pixels per band rather
than keeping positionally-aligned lists. This module used to pull `SCL`,
`occurrence` and B2-B6 as parallel Python lists and zip them, which
forced a length-mismatch guard that turned "JRC has no data here" into
"this buffer has no water pixels" — the root cause of the offshore
discards above. The zip is gone. The combined cloud+water mask is now
built as an `ee.Image` and applied with `updateMask` before a single
`reduceRegion(ee.Reducer.mean().combine(ee.Reducer.count()))`, so the
pixels never leave the server as parallel lists and there is no alignment
problem to guard. Anyone adding another per-pixel layer here should keep
it server-side for the same reason.

GEE-free, offline-testable pieces (`data-pipeline/tests/test_sentinel2_masking.py`,
`data-pipeline/tests/test_water_mask_fixture.py`):
  - `cloud_fraction_from_stats` and `band_means_from_stats` are executed
    in production: they parse the plain dict `reduceRegion(...).getInfo()`
    returns, which is a typed boundary containing no `ee` objects.
  - `compute_cloud_fraction` and `water_pixel_mask` are plain-numpy
    *reference implementations* of the two rules the server-side
    expressions encode. They are not called by the pipeline — an
    `ee.Image` expression cannot be evaluated offline, and the masking
    rule is the single thing most worth testing, so it is stated twice:
    once as the executing `ee` expression, once as a numpy function the
    test suite can drive against the 499-point fixture with no GEE
    session. That duplication is a real drift risk; it is accepted
    deliberately and each side's docstring names the other.
"""

from __future__ import annotations

import os
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
# Ceiling on the backward scene search -- NOT the selection rule. The
# rule is "newest usable scene acquired on or before the requested day";
# this only decides when to stop looking and report no imagery rather
# than reach for something older still. Sentinel-2's ~5-day revisit puts
# roughly a dozen acquisition opportunities inside the default 60 days,
# which through the southwest monsoon is often what it takes to reach one
# cloud-free pass: measured 2026-09-06 at upper-Gulf grid point 1_2,
# every acquisition from 2026-09-02 back to 2026-08-20 was 100% cloud
# over the sample buffer and the walk only stopped at 2026-08-18. Past
# this ceiling a reading is too stale to say anything about current water
# colour, so no-data is the honest answer. Override with
# SENTINEL2_MAX_SCENE_AGE_DAYS (see .env.example).
DEFAULT_MAX_SCENE_AGE_DAYS = 60
MAX_SCENE_AGE_ENV_VAR = "SENTINEL2_MAX_SCENE_AGE_DAYS"
DEFAULT_MAX_CLOUD_FRACTION = 0.5
DEFAULT_MIN_WATER_OCCURRENCE_PCT = 50.0

# Primary water layer: JRC Global Surface Water v1.4, `occurrence` =
# percent of valid Landsat observations 1984-2021 in which the pixel was
# water. 30 m. Masked (no data) wherever the pixel was never observed as
# water -- including all open ocean, which is what the ETOPO1 fallback
# below exists to cover.
JRC_GSW_ASSET = "JRC/GSW1_4/GlobalSurfaceWater"
JRC_GSW_OCCURRENCE_BAND = "occurrence"

# Fallback where JRC has no data: NOAA ETOPO1 bedrock elevation, 1
# arc-minute (~1.85 km here). Only consulted per-pixel where JRC is
# silent -- far too coarse to be trusted against JRC, but unambiguous
# well offshore, which is where most of JRC's gap sits.
#
# Not all of it, though: JRC is also silent at some narrow near-shore
# strips, and there ETOPO1 is at its worst. Live-checked 2026-09-05 at
# Ang Sila (13.338, 100.925): JRC returns
# zero pixels in the 30 m buffer, and ETOPO1 averages +3.1 m across it
# while still placing ~35% of it below sea level, because one ~1.85 km
# cell straddles the shoreline. That buffer now yields a reading where it
# previously raised NoWaterPixelsError, and the reading is bright
# (B2-B6 ~1040-1660 vs ~200-560 for open Gulf water) -- consistent with a
# turbid pier strip, and possibly with some shoreline in the average.
# Treat near-shore readings that exist only because of this fallback with
# the same suspicion as any other river-mouth/mudflat reading.
ETOPO1_ASSET = "NOAA/NGDC/ETOPO1"
ETOPO1_BEDROCK_BAND = "bedrock"
SEA_LEVEL_M = 0.0

# Band names used inside the single server-side reduceRegion call. Not
# Sentinel-2 band names -- they name the derived 0/1 layers this module
# builds, and the keys `cloud_fraction_from_stats` reads back out.
WATER_MASK_BAND = "water_mask"
CLOUD_FLAG_BAND = "cloud_flag"


class NoCloudFreeImageryError(RuntimeError):
    """No Sentinel-2 image within the search window met the cloud-fraction
    threshold at this location. Distinct from GEEAuthError — auth worked,
    the data simply is not usable (e.g. deep monsoon cloud cover)."""


class NoWaterPixelsError(RuntimeError):
    """No pixel in the sample buffer survived the combined cloud+water
    mask — the point is likely on shore, or the buffer is too small for a
    coastal location. "Water" here means JRC Global Surface Water
    occurrence >= 50% where JRC has data, and ETOPO1 bedrock below sea
    level where it does not (see the module docstring's water test)."""


# --------------------------------------------------------------------------
# Pure functions, group 1 — executed in production.
#
# These parse the plain dict `reduceRegion(...).getInfo()` returns. That
# dict is a typed boundary: numbers, strings and None, no `ee` objects,
# so the interpretation of a GEE result is unit-testable offline even
# though the reduction itself is not.
# --------------------------------------------------------------------------


def cloud_fraction_from_stats(stats: dict, band: str = CLOUD_FLAG_BAND) -> float:
    """Cloud fraction from a combined mean+count `reduceRegion` result.

    `stats` is `image.reduceRegion(ee.Reducer.mean().combine(
    ee.Reducer.count(), sharedInputs=True), ...).getInfo()`, so it carries
    `f"{band}_mean"` and `f"{band}_count"`. The cloud-flag band is 1 for
    an SCL class in `DEFAULT_CLOUD_CLASSES` and 0 otherwise, and it keeps
    SCL's own mask — so its *mean* is exactly "fraction of valid SCL
    pixels in the buffer classified as cloud/invalid", the same quantity
    `compute_cloud_fraction` defines over a flat SCL array.

    A count of 0 (or a null mean — GEE returns null for a mean over no
    pixels) is treated as fully unusable, fraction 1.0, rather than
    raising: "no pixels returned" is itself evidence the reading can't be
    trusted, and the caller's candidate loop already rejects anything
    above `max_cloud_fraction`.
    """
    count = stats.get(f"{band}_count")
    mean = stats.get(f"{band}_mean")
    if not count or mean is None:
        return 1.0
    return float(min(1.0, max(0.0, float(mean))))


def band_means_from_stats(
    stats: dict, bands: tuple[str, ...] = BANDS
) -> dict[str, float]:
    """Per-band masked means from a combined mean+count `reduceRegion` result.

    The bands were `updateMask`-ed with the combined cloud+water mask
    before reduction, so `f"{band}_mean"` is already the water-and-cloud-
    masked mean and `f"{band}_count"` is how many pixels survived.

    Raises:
        NoWaterPixelsError: any requested band had zero surviving pixels
            (count 0, or a null mean). This is the same typed error the
            old parallel-list code raised for an all-land buffer, with the
            same meaning for callers: skip this candidate date, or surface
            `no_water_pixels` to the API.
    """
    means: dict[str, float] = {}
    for band in bands:
        count = stats.get(f"{band}_count")
        mean = stats.get(f"{band}_mean")
        if not count or mean is None:
            raise NoWaterPixelsError(
                f"No pixels passed the combined cloud/water mask in this "
                f"buffer (band {band}: count={count!r}, mean={mean!r}). The "
                f"point is likely on shore, or the buffer is too small for "
                f"a coastal location."
            )
        means[band] = float(mean)
    return means


# --------------------------------------------------------------------------
# Pure functions, group 2 — reference implementations, NOT executed.
#
# The masking rules below run server-side as `ee.Image` expressions
# (`_cloud_flag_image`, `_water_mask_image`), which cannot be evaluated
# without a live Earth Engine session. The rules are the single most
# important thing in this module to get right, so each is also written
# here as a plain numpy function the offline test suite can drive —
# including against the 499-point ground-truth fixture in
# `data/validation/water_mask_truth.json`. Keep the two sides in step:
# changing one without the other is a silent behaviour change that the
# tests will not catch.
# --------------------------------------------------------------------------


def compute_cloud_fraction(
    scl_values: Any, cloud_classes: tuple = DEFAULT_CLOUD_CLASSES
) -> float:
    """Fraction of pixels in `scl_values` classified as cloud/invalid.

    Reference implementation of what `_cloud_flag_image` + a `mean`
    reducer compute server-side (see `cloud_fraction_from_stats`). Takes a
    flat array of SCL classification codes and returns a float in [0, 1].
    An empty array is treated as fully unusable (fraction 1.0) rather than
    raising, since "no pixels returned" is itself evidence the reading
    can't be trusted.
    """
    arr = np.asarray(scl_values)
    if arr.size == 0:
        return 1.0
    is_cloud = np.isin(arr, cloud_classes)
    return float(np.count_nonzero(is_cloud) / arr.size)


def water_pixel_mask(
    occurrence_values: Any,
    etopo_values: Any,
    min_occurrence_pct: float = DEFAULT_MIN_WATER_OCCURRENCE_PCT,
) -> np.ndarray:
    """Boolean per-pixel water mask: JRC where it has data, else ETOPO1.

    Reference implementation of `_water_mask_image`. Per pixel:

      - JRC `occurrence` has data (not NaN) -> water iff
        `occurrence >= min_occurrence_pct`. JRC wins wherever it has an
        opinion; ETOPO1 never overrides it.
      - JRC has no data (NaN) -> water iff ETOPO1 bedrock elevation is
        below sea level (`< SEA_LEVEL_M`). Missing bathymetry (NaN, or
        `etopo_values=None` meaning no bathymetry at all) counts as land,
        the conservative direction.

    Args:
        occurrence_values: JRC GSW `occurrence` per pixel, 0-100, NaN
            where JRC has no data.
        etopo_values: ETOPO1 `bedrock` metres per pixel; a scalar (one
            elevation for the whole buffer, as the validation fixture
            stores it) or None (no bathymetry available) are also
            accepted.
        min_occurrence_pct: JRC occurrence threshold, percent.

    Raises:
        ValueError: `etopo_values` is an array of a different shape than
            `occurrence_values` — a caller mix-up, not a data condition,
            so it is not laundered into `NoWaterPixelsError`.
    """
    occurrence = np.asarray(occurrence_values, dtype=float)
    jrc_has_data = ~np.isnan(occurrence)
    jrc_says_water = jrc_has_data & (
        np.nan_to_num(occurrence, nan=0.0) >= min_occurrence_pct
    )

    if etopo_values is None:
        bathymetry_says_water = np.zeros(occurrence.shape, dtype=bool)
    else:
        etopo = np.asarray(etopo_values, dtype=float)
        if etopo.ndim == 0:
            etopo = np.full(occurrence.shape, float(etopo))
        if etopo.shape != occurrence.shape:
            raise ValueError(
                f"etopo_values shape {etopo.shape} != occurrence_values "
                f"shape {occurrence.shape}"
            )
        bathymetry_says_water = ~np.isnan(etopo) & (
            np.nan_to_num(etopo, nan=0.0) < SEA_LEVEL_M
        )

    return np.where(jrc_has_data, jrc_says_water, bathymetry_says_water)


# --------------------------------------------------------------------------
# GEE-backed extraction.
# --------------------------------------------------------------------------


def _cloud_flag_image(
    image: ee.Image, cloud_classes: tuple = DEFAULT_CLOUD_CLASSES
) -> ee.Image:
    """0/1 cloud flag from a Sentinel-2 L2A scene's SCL band.

    1 where SCL is one of `cloud_classes` (cloud, shadow, cirrus,
    saturated, unclassified, no-data), 0 otherwise. Inherits SCL's own
    mask, so pixels where SCL itself has no data are masked out rather
    than counted as clear — which makes this band's `mean` over a region
    exactly the cloud fraction of the *valid* pixels there, matching
    `compute_cloud_fraction`'s definition.
    """
    classes = list(cloud_classes)
    return (
        image.select("SCL")
        .remap(classes, [1] * len(classes), 0)
        .rename(CLOUD_FLAG_BAND)
    )


def _water_mask_image(
    min_occurrence_pct: float = DEFAULT_MIN_WATER_OCCURRENCE_PCT,
) -> ee.Image:
    """0/1 water mask: JRC GSW occurrence where it has data, else ETOPO1.

    Server-side counterpart of `water_pixel_mask` — see that function and
    the module docstring for the rule and for why the fallback is
    per-pixel rather than per-buffer. `occurrence.gte(...)` inherits JRC's
    mask, so `unmask(<bathymetry image>)` substitutes the ETOPO1 answer
    at exactly the pixels JRC has no data for and nowhere else. ETOPO1's
    own no-data is unmasked to 0 (land) first, so a pixel neither layer
    covers is excluded rather than admitted.

    The returned image is fully unmasked (a genuine 0/1 everywhere), so
    it can be handed to `updateMask` without silently masking pixels that
    should merely have been excluded.
    """
    occurrence = ee.Image(JRC_GSW_ASSET).select(JRC_GSW_OCCURRENCE_BAND)
    bedrock = ee.Image(ETOPO1_ASSET).select(ETOPO1_BEDROCK_BAND)

    jrc_says_water = occurrence.gte(min_occurrence_pct)
    bathymetry_says_water = bedrock.lt(SEA_LEVEL_M).unmask(0)

    return jrc_says_water.unmask(bathymetry_says_water).rename(WATER_MASK_BAND)




def default_max_scene_age_days() -> int:
    """Effective ceiling on the backward scene search, read at call time.

    `SENTINEL2_MAX_SCENE_AGE_DAYS` wins when it parses as a positive
    integer; anything else falls back to `DEFAULT_MAX_SCENE_AGE_DAYS`.
    Read lazily rather than frozen into a module constant at import time
    because the `.env` files carrying it are loaded by whichever bridge
    imports this package (`detection/src/_data_pipeline.py`, and
    `backend/src/config.py` for its own file), and the import order
    between those is not guaranteed.
    """
    raw = os.environ.get(MAX_SCENE_AGE_ENV_VAR, "").strip()
    if not raw:
        return DEFAULT_MAX_SCENE_AGE_DAYS
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_SCENE_AGE_DAYS
    return value if value > 0 else DEFAULT_MAX_SCENE_AGE_DAYS


# Carried alongside each candidate's `reduceRegion` output in the single
# batched round trip below. Leading underscore so neither can collide
# with a reducer output key ("B2_mean", "cloud_flag_count", ...).
_SCENE_ID_PROPERTY = "_scene_id"
_SCENE_TIME_PROPERTY = "_scene_time_start"


def _resolve_sentinel2_scene(
    lat: float,
    lng: float,
    date: str,
    max_scene_age_days: int | None = None,
    buffer_m: int = DEFAULT_BUFFER_M,
    max_cloud_fraction: float = DEFAULT_MAX_CLOUD_FRACTION,
) -> dict:
    """Newest usable Sentinel-2 scene acquired on or before `date`.

    Selection rule -- one policy, every caller: among the scenes covering
    this point, take the most recent acquisition whose sample buffer
    passes the cloud and water checks. Two things the rule is not:

      - It is not "nearest to `date`". A scene acquired *after* the
        requested day is never a candidate, at any distance. `date` means
        "as of this day", and answering it with imagery that did not
        exist yet would date a reading into the future of the very thing
        it claims to describe.
      - `max_scene_age_days` is not the selection rule either. It is only
        how far back the walk goes before giving up and raising, rather
        than reaching for something older still. It bounds the search; it
        never chooses within it. Defaults to
        `default_max_scene_age_days()`.

    This is the single place that logic lives. `get_sentinel2_bands`
    (numeric path) and `data-pipeline/src/imagery.py` (image-rendering
    path, added for the true-color/NDCI-heatmap panel thumbnails) both
    call this function rather than each running their own copy of the
    search/check loop — a second, independently written loop could drift
    (different default threshold, different ordering, a future bugfix
    applied to only one copy) and end up picking a different image than
    the one the numeric bands came from, which is exactly the
    inconsistency this project cannot tolerate: a caller must never be
    shown a picture from a different date than the numbers next to it.
    Given identical lat/lng/date/max-scene-age/buffer/cloud-threshold the
    underlying GEE query is deterministic (same collection filter, same
    acquisition-time ordering, same checks), so both callers land on the
    same scene by construction, not by luck — with no per-caller
    exception, since neither has a direction to disagree about any more.

    One round trip, not one per candidate: the masked statistics for
    every candidate in the window are computed server-side in a single
    `collection.map(...)` and returned by one `getInfo()`, after which
    the newest-first walk is plain Python over numbers already in hand.
    The previous implementation issued one `reduceRegion().getInfo()` per
    candidate, which made the walk-back cost proportional to how cloudy
    the period had been — the 2026-09-06 upper-Gulf scan spent ~10 round
    trips on a typical point and 36 minutes over 501 points, and that was
    against a 20-day ceiling. Server-side compute is unchanged (the same
    reduction over the same ~40-pixel buffer, just evaluated for every
    candidate instead of stopping early); only the number of network
    round trips falls, which is what makes a long ceiling affordable.

    Masking is done server-side: the combined cloud+water mask is built
    as an `ee.Image` and applied with `updateMask` before one
    `reduceRegion(ee.Reducer.mean().combine(ee.Reducer.count()))` per
    candidate. Pixels are never pulled back as parallel per-band Python
    lists, so there is no per-band alignment to get wrong (see the module
    docstring, "Historical GEE gotcha"). Pairing the scene id and its
    acquisition time onto the same feature as those statistics also
    removes the last place two separately-evaluated `aggregate_array`
    calls had to be trusted to come back in the same order.

    One measured, deliberate side effect of the `reduceRegion` switch:
    `toList` only returned pixels lying wholly inside the buffer (~26-28
    at the default 30 m radius / 10 m scale), whereas `reduceRegion`'s
    mean/count reducers include every pixel that *intersects* it (~40),
    weighted by the fraction covered. The sample is therefore a proper
    area-weighted mean over the 30 m disc rather than an unweighted mean
    over the pixels fully inside it. Live-checked 2026-09-05 at Bang
    Saen, Si Racha and the Chao Phraya mouth (grid point 23_10): every
    band moved by less than 1.4% (B2 -1.35% to +0.97%, B6 +0.10% to
    +1.34%). Units are unchanged, so ratio indices downstream are
    unaffected.

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
        NoCloudFreeImageryError: no scene on or before `date`, within
            `max_scene_age_days`, met the cloud threshold.
        NoWaterPixelsError: no pixel in the buffer survived the combined
            cloud+water mask on any candidate clear enough to check.
    """
    initialize_ee()

    if max_scene_age_days is None:
        max_scene_age_days = default_max_scene_age_days()

    point = ee.Geometry.Point([lng, lat])
    region = point.buffer(buffer_m)

    requested = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    window_start = (requested - timedelta(days=max_scene_age_days)).strftime("%Y-%m-%d")
    # filterDate's end is exclusive, so +1 day keeps the requested day's
    # own acquisitions as candidates and admits nothing later.
    window_end = (requested + timedelta(days=1)).strftime("%Y-%m-%d")

    collection = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(region)
        .filterDate(window_start, window_end)
        .sort("system:time_start")
    )

    # JRC Global Surface Water (multi-year "how often was this pixel
    # water", independent of any single day's turbidity/cloud), backed by
    # ETOPO1 bathymetry wherever JRC has no data at all -- see
    # `_water_mask_image`. Built once, reused for every candidate.
    water_mask_img = _water_mask_image()

    # mean + count together: mean gives the masked band means and the
    # cloud fraction, count says how many pixels each of those was
    # actually computed from (0 -> nothing survived the mask).
    reducer = ee.Reducer.mean().combine(ee.Reducer.count(), sharedInputs=True)

    def _candidate_stats(image):
        image = ee.Image(image)
        cloud_flag = _cloud_flag_image(image)

        # B2-B6 masked down to clear-sky water pixels; `cloud_flag` is
        # deliberately added AFTER updateMask so it keeps every valid SCL
        # pixel and its mean stays the buffer's true cloud fraction,
        # independent of how much water is in the buffer.
        sample_img = (
            image.select(list(BANDS))
            .updateMask(water_mask_img.And(cloud_flag.Not()))
            .addBands(cloud_flag)
        )
        stats = sample_img.reduceRegion(
            reducer=reducer,
            geometry=region,
            scale=DEFAULT_SCALE_M,
            maxPixels=1e7,
        )
        return ee.Feature(None, stats).set({
            _SCENE_ID_PROPERTY: image.get("system:index"),
            _SCENE_TIME_PROPERTY: image.get("system:time_start"),
        })

    features = ee.FeatureCollection(collection.map(_candidate_stats)).getInfo()["features"]
    if not features:
        raise NoCloudFreeImageryError(
            f"No Sentinel-2 scenes found for ({lat}, {lng}) between "
            f"{window_start} and {window_end}."
        )

    # Newest acquisition first, so the first candidate that passes both
    # checks is by construction the newest usable one.
    candidates = sorted(
        (feature["properties"] for feature in features),
        key=lambda stats: stats[_SCENE_TIME_PROPERTY],
        reverse=True,
    )

    best_error: Exception | None = None
    for stats in candidates:
        image_id = stats[_SCENE_ID_PROPERTY]
        cloud_fraction = cloud_fraction_from_stats(stats)
        if cloud_fraction > max_cloud_fraction:
            best_error = NoCloudFreeImageryError(
                f"Candidate {image_id} rejected: cloud_fraction={cloud_fraction:.2f} "
                f"> max_cloud_fraction={max_cloud_fraction}."
            )
            continue

        try:
            band_means = band_means_from_stats(stats)
        except NoWaterPixelsError as exc:
            best_error = exc
            continue

        actual_date = datetime.fromtimestamp(
            stats[_SCENE_TIME_PROPERTY] / 1000, tz=timezone.utc
        ).strftime("%Y-%m-%d")
        return {
            "image": ee.Image(f"COPERNICUS/S2_SR_HARMONIZED/{image_id}"),
            "image_id": image_id,
            "region": region,
            "band_means": band_means,
            "cloud_fraction": cloud_fraction,
            "actual_date": actual_date,
        }

    # Every candidate on or before `date` was rejected.
    raise best_error or NoCloudFreeImageryError(
        f"No usable Sentinel-2 image for ({lat}, {lng}) on or before {date}, "
        f"within {max_scene_age_days} days."
    )


def get_sentinel2_bands(
    lat: float,
    lng: float,
    date: str,
    max_scene_age_days: int | None = None,
    buffer_m: int = DEFAULT_BUFFER_M,
    max_cloud_fraction: float = DEFAULT_MAX_CLOUD_FRACTION,
) -> dict:
    """Sentinel-2 surface-reflectance bands at a point, cloud- and
    land-masked, from the newest usable scene acquired on or before the
    requested date.

    Args:
        lat, lng: WGS84 coordinates (upper Gulf of Thailand study area).
        date: the day being asked about, "YYYY-MM-DD", read as "as of
            this day". The reading comes from the most recent usable
            acquisition on or before it, which is routinely days or weeks
            older -- `actual_date` in the result says which, and callers
            showing the number to a human are expected to show that date
            (or its age) with it. A scene acquired after this day is
            never used.
        max_scene_age_days: how far back to keep looking before giving up
            and raising, rather than returning something older still.
            Defaults to `default_max_scene_age_days()`
            (`SENTINEL2_MAX_SCENE_AGE_DAYS`, else
            `DEFAULT_MAX_SCENE_AGE_DAYS`).
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
        NoCloudFreeImageryError: no scene on or before `date`, within
            `max_scene_age_days`, met the cloud threshold.
        NoWaterPixelsError: no pixel in the buffer survived the combined
            cloud+water mask on any candidate clear enough to check.
            "Water" = JRC GSW occurrence >= 50% where JRC has data,
            ETOPO1 bedrock below sea level where it does not.
    """
    resolved = _resolve_sentinel2_scene(
        lat, lng, date, max_scene_age_days, buffer_m, max_cloud_fraction
    )
    return {
        **resolved["band_means"],
        "cloud_fraction": resolved["cloud_fraction"],
        "actual_date": resolved["actual_date"],
    }
