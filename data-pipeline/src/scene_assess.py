"""
Per-date Sentinel-2 scene assessment for the latest-scene policy: did the
newest acquisition over the study polygon pass the cloud criterion?

Data source: Copernicus Sentinel-2 Level-2A surface reflectance,
`COPERNICUS/S2_SR_HARMONIZED`, via Google Earth Engine -- only its Scene
Classification Layer (SCL) is read. Cloud and water are decided by exactly
the production masking functions, `sentinel2._cloud_flag_image` (SCL classes
in `sentinel2.DEFAULT_CLOUD_CLASSES`: cloud, shadow, cirrus, saturated,
unclassified, no-data) and `sentinel2._water_mask_image` (JRC Global Surface
Water occurrence >= 50 %, ETOPO1 below sea level where JRC has no data).
Nothing about either rule is restated here.

What is assessed, and the criterion
-----------------------------------
The unit is one UTC acquisition DATE over the polygon: every Sentinel-2
granule (tile/orbit) whose `system:time_start` falls on that UTC day is
combined into one decision. A date passes when, over the WATER part of the
polygon that the date's granules observed:

  - at least `min_water_pixels` water pixels were observed
    (`RASTER_SCENE_MIN_WATER_PIXELS`, default 1000), and
  - the cloud-flagged share of those pixels is <= `max_cloud_fraction`
    (`RASTER_SCENE_MAX_CLOUD_FRACTION`, default
    `sentinel2.DEFAULT_MAX_CLOUD_FRACTION`, 0.5; strictly greater rejects,
    the same comparison the point path uses).

The water check runs first, so the two rejections name different causes:
`rejected_no_water` means the date's granules did not see enough of the
polygon's water (a granule grazing a corner, an all-masked scene), while
`rejected_cloud` means they saw it and it was cloudy. A fully overcast
monsoon day is therefore `rejected_cloud` at 100 %, never "no water".
Passing guarantees at least `min_water_pixels * (1 - max_cloud_fraction)`
clear water pixels (500 at the defaults).

Note the denominator differs from the point path's: `cloud_fraction_from_stats`
there is the cloud share of every valid SCL pixel in a 30 m buffer, land
included; here it is the share of observed WATER pixels only, because land
cloud says nothing about whether the water reading is usable.

Partial-sum keys (the `_fetch` seam contract)
---------------------------------------------
`_fetch` returns one dict per granule; every count is a non-negative int,
an unweighted sum of a 0/1 band over the polygon at `scale_m`:

  - `date`        -- "YYYY-MM-DD", the granule's UTC acquisition date.
  - `water_count` -- water pixels (production water mask = 1) that this
                     granule observed, i.e. where its SCL band is not
                     masked. The denominator of the cloud fraction, and the
                     `water_pixels` reported (the "unmasked water pixels"
                     of the rejection reason: unmasked by the water mask
                     and by the scene's own footprint).
  - `cloud_count` -- of `water_count`, pixels `_cloud_flag_image` flags.
  - `valid_count` -- of `water_count`, pixels it does not flag: clear water,
                     the pixels that survive the combined water + cloud
                     mask -- what a raster read of this granule can use.
  - `scene_id`    -- optional, `system:index`, informational only.

`cloud_count + valid_count == water_count` holds per granule by
construction (all three bands share one mask), and `combine_tiles` refuses
a tile that breaks it. A date's cloud fraction is
`sum(cloud_count) / sum(water_count)` over its granules -- a ratio of
summed pixel counts, never a mean of per-granule fractions: a 100-pixel
clear granule and a 900-pixel overcast one give 0.9, not 0.5.

Limitations -- read before relying on a decision
------------------------------------------------
  - Coarse grid, not every native pixel. The reduction runs at `scale_m`
    (200 m by default, the raster's scale), so Earth Engine evaluates the
    SCL and water layers on its resampled 200 m grid and each count is of
    200 m cells, not of native 20 m SCL pixels. `raster.py` ("Resolution")
    measured that its own 200 m read samples one native pixel per cell
    rather than averaging; this reduction was not separately measured. The
    fraction is therefore a sample estimate -- ample for a 0.5 threshold
    over tens of thousands of cells, not an exact cloud area.
  - Granule overlap is counted twice. Adjacent Sentinel-2 granules of one
    pass overlap by roughly 10 km, and each granule is reduced separately,
    so a water pixel in an overlap strip is counted once per granule.
    `water_pixels` overstates distinct pixels by that share, and overlap
    strips weigh double in the fraction. Accepted: the error is bounded by
    the overlap area and does not turn into a mean of means.
  - Multi-year water mask, not today's water. Turbid river-mouth water and
    newly exposed mudflats can be misclassified, exactly as for every other
    reading in this project.
  - "Cloud" is the production SCL definition of unusable (it includes
    shadow, cirrus, saturated, unclassified and no-data), not a
    meteorological cloud product.
  - Partial ingestion. A date is assessed with the granules Earth Engine
    holds at poll time. If a date's granules arrive over several hours, an
    early assessment describes only the part already ingested.
  - A pass says the water was visible. It says nothing about blooms:
    detection stays at satellite pixel resolution (water-colour signatures,
    never organisms), and small or dispersed blooms can be missed.

Earth Engine use and failure policy
-----------------------------------
Everything that touches `ee` is `_fetch_scene_stats` (plus the expression
builder `_scene_count_image`). It asks for every granule since `since_date`
that is not on an already-assessed date (`skip_dates` is filtered
server-side, so a date is reduced once, not on every poll), reduces each
with `ee.Reducer.sum().unweighted()`, `bestEffort=False` and a high
`maxPixels`, and returns everything in ONE `getInfo()` round trip. Any
Earth Engine failure raises out of `assess_new_scenes`; it is never turned
into a decision, so the caller leaves those dates unassessed and retries.
Because the round trip is batched, one failing granule fails the whole poll.
"""

from __future__ import annotations

import math
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable

import ee

from . import sentinel2
from .auth import GEEConfigError, initialize_ee
from .raster import DEFAULT_RASTER_SCALE_M

S2_COLLECTION = "COPERNICUS/S2_SR_HARMONIZED"

MAX_CLOUD_FRACTION_ENV_VAR = "RASTER_SCENE_MAX_CLOUD_FRACTION"
MIN_WATER_PIXELS_ENV_VAR = "RASTER_SCENE_MIN_WATER_PIXELS"
DEFAULT_MIN_WATER_PIXELS = 1000

PASSED = "passed"
REJECTED_CLOUD = "rejected_cloud"
REJECTED_NO_WATER = "rejected_no_water"
DECISIONS = (PASSED, REJECTED_CLOUD, REJECTED_NO_WATER)

# The partial-sum keys documented in the module docstring. The count keys
# are also the band names of `_scene_count_image`, so the sum reducer's
# output dict is keyed by them directly -- one spelling, no mapping step.
DATE_KEY = "date"
CLOUD_COUNT_KEY = "cloud_count"
VALID_COUNT_KEY = "valid_count"
WATER_COUNT_KEY = "water_count"
SCENE_ID_KEY = "scene_id"
COUNT_KEYS = (CLOUD_COUNT_KEY, VALID_COUNT_KEY, WATER_COUNT_KEY)

# The study polygon is ~1.26e4 km2: ~3.2e5 pixels at 200 m, ~1.3e8 at 10 m.
# A ceiling far above either, so a large read is computed in full; with
# bestEffort=False an over-limit request errors instead of silently
# coarsening the scale.
MAX_PIXELS = 1e13

_ISO_DATE = "%Y-%m-%d"
_EE_ISO_DATE = "YYYY-MM-dd"  # Joda pattern for ee.Date.format


@dataclass(frozen=True)
class SceneAssessment:
    """The decision for one UTC acquisition date over the study polygon.

    `cloud_fraction` is None only when the date's granules observed no
    water pixel at all (then `decision` is `rejected_no_water`).
    `water_pixels` is the observed-water count (`water_count` summed).
    `reason` is None for `passed`.
    """

    acquisition_date: str
    cloud_fraction: float | None
    water_pixels: int
    decision: str
    reason: str | None


# --------------------------------------------------------------------------
# Thresholds -- validated, read from the environment at call time.
# --------------------------------------------------------------------------


def _is_count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_max_cloud_fraction(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number in (0, 1], got {value!r}")
    if not math.isfinite(value) or not 0 < value <= 1:
        raise ValueError(f"{name} must be a number in (0, 1], got {value!r}")
    return float(value)


def _check_min_water_pixels(value: Any, name: str) -> int:
    if not _is_count(value) or value <= 0:
        raise ValueError(f"{name} must be a positive integer, got {value!r}")
    return value


def _max_cloud_fraction_from_env() -> float:
    raw = os.environ.get(MAX_CLOUD_FRACTION_ENV_VAR, "").strip()
    if not raw:
        # Module attribute lookup, not a name bound at import: the default
        # follows the system-wide constant if it ever changes.
        return float(sentinel2.DEFAULT_MAX_CLOUD_FRACTION)
    try:
        value = float(raw)
    except ValueError:
        value = float("nan")
    if not math.isfinite(value) or not 0 < value <= 1:
        raise GEEConfigError(
            f"{MAX_CLOUD_FRACTION_ENV_VAR} must be a number in (0, 1], got {raw!r}"
        )
    return value


def _min_water_pixels_from_env() -> int:
    raw = os.environ.get(MIN_WATER_PIXELS_ENV_VAR, "").strip()
    if not raw:
        return DEFAULT_MIN_WATER_PIXELS
    try:
        value = int(raw)
    except ValueError:
        value = 0
    if value <= 0:
        raise GEEConfigError(
            f"{MIN_WATER_PIXELS_ENV_VAR} must be a positive integer, got {raw!r}"
        )
    return value


def scene_thresholds() -> tuple[float, int]:
    """Effective `(max_cloud_fraction, min_water_pixels)`, read at call time.

    `RASTER_SCENE_MAX_CLOUD_FRACTION` must parse as a finite number in
    (0, 1]; blank or unset means `sentinel2.DEFAULT_MAX_CLOUD_FRACTION`.
    `RASTER_SCENE_MIN_WATER_PIXELS` must parse as a positive integer; blank
    or unset means `DEFAULT_MIN_WATER_PIXELS` (1000). Read lazily, not at
    import, because the `.env` files carrying them are loaded by whichever
    bridge imports this package, in no guaranteed order (same reasoning as
    `sentinel2.default_max_scene_age_days`).

    Raises:
        GEEConfigError (a ValueError): a variable is set to an invalid value.
            The message names the variable. Never silently replaced by the
            default -- a typo in a threshold must not change which scenes
            trigger a scan without anyone noticing.
    """
    return _max_cloud_fraction_from_env(), _min_water_pixels_from_env()


# --------------------------------------------------------------------------
# Pure decision logic -- executed in production, no `ee`.
# --------------------------------------------------------------------------


def decide(
    *,
    cloud_fraction: float | None,
    water_pixels: int,
    max_cloud_fraction: float,
    min_water_pixels: int,
) -> tuple[str, str | None]:
    """Decision and reason for one date's combined statistics.

    In order:
      - `cloud_fraction is None`: allowed only with `water_pixels == 0`
        (nothing observed, so no fraction exists) -> `rejected_no_water`.
        Any other None raises; it is a broken input, never a default.
      - `water_pixels < min_water_pixels` -> `("rejected_no_water",
        "<n> unmasked water pixels < <min>")`.
      - `cloud_fraction > max_cloud_fraction` -> `("rejected_cloud",
        "cloud <x:.0%> > <max:.0%>")`. Equality passes.
      - otherwise `("passed", None)`.

    Raises:
        ValueError: an input is out of range (negative or non-int
            `water_pixels`, a non-finite or out-of-[0, 1] `cloud_fraction`,
            an invalid threshold) or None is inconsistent as above. A NaN
            fraction in particular would otherwise pass (`nan > x` is False).
    """
    max_cloud_fraction = _check_max_cloud_fraction(max_cloud_fraction, "max_cloud_fraction")
    min_water_pixels = _check_min_water_pixels(min_water_pixels, "min_water_pixels")
    if not _is_count(water_pixels) or water_pixels < 0:
        raise ValueError(f"water_pixels must be a non-negative integer, got {water_pixels!r}")

    if cloud_fraction is None:
        if water_pixels != 0:
            raise ValueError(
                f"cloud_fraction is None but water_pixels={water_pixels}: a cloud "
                "fraction is undefined only when no water pixel was observed"
            )
        return REJECTED_NO_WATER, f"0 unmasked water pixels < {min_water_pixels}"

    if isinstance(cloud_fraction, bool) or not isinstance(cloud_fraction, (int, float)):
        raise ValueError(f"cloud_fraction must be a number in [0, 1], got {cloud_fraction!r}")
    if not math.isfinite(cloud_fraction) or not 0 <= cloud_fraction <= 1:
        raise ValueError(f"cloud_fraction must be a number in [0, 1], got {cloud_fraction!r}")

    if water_pixels < min_water_pixels:
        return (
            REJECTED_NO_WATER,
            f"{water_pixels} unmasked water pixels < {min_water_pixels}",
        )
    if cloud_fraction > max_cloud_fraction:
        return (
            REJECTED_CLOUD,
            f"cloud {cloud_fraction:.0%} > {max_cloud_fraction:.0%}",
        )
    return PASSED, None


def combine_tiles(tile_stats: list[dict]) -> dict:
    """Merge one date's per-granule partial sums into one set of statistics.

    Pure. Each tile carries the integer `cloud_count`, `valid_count` and
    `water_count` described in the module docstring (extra keys such as
    `scene_id` are ignored). Counts are summed across tiles, then:

        cloud_fraction = sum(cloud_count) / sum(water_count)   (None if 0)
        water_pixels   = sum(water_count)

    -- weighted by pixel counts, never a mean of the per-tile fractions.

    Returns:
        {"cloud_fraction": float | None, "water_pixels": int,
         "cloud_count": int, "valid_count": int, "water_count": int}

    Raises:
        ValueError: no tiles; a count missing, not a non-negative int, or
            breaking `cloud_count + valid_count == water_count`; or tiles
            carrying different `date`s. A broken partial sum is refused,
            never repaired into a decision.
    """
    if not tile_stats:
        raise ValueError("combine_tiles needs at least one tile")

    dates = {tile[DATE_KEY] for tile in tile_stats if DATE_KEY in tile}
    if len(dates) > 1:
        raise ValueError(f"combine_tiles got tiles from several dates: {sorted(dates)}")

    totals = {key: 0 for key in COUNT_KEYS}
    for tile in tile_stats:
        for key in COUNT_KEYS:
            if key not in tile:
                raise ValueError(f"tile is missing {key}: {tile!r}")
            value = tile[key]
            if not _is_count(value) or value < 0:
                raise ValueError(f"{key} must be a non-negative integer, got {value!r}")
        if tile[CLOUD_COUNT_KEY] + tile[VALID_COUNT_KEY] != tile[WATER_COUNT_KEY]:
            raise ValueError(
                f"{CLOUD_COUNT_KEY} + {VALID_COUNT_KEY} != {WATER_COUNT_KEY} in "
                f"{tile!r}: cloud and clear water must partition observed water"
            )
        for key in COUNT_KEYS:
            totals[key] += tile[key]

    water = totals[WATER_COUNT_KEY]
    return {
        "cloud_fraction": totals[CLOUD_COUNT_KEY] / water if water else None,
        "water_pixels": water,
        **totals,
    }


def _iso_date(value: Any, what: str) -> str:
    """`value` if it is a canonical "YYYY-MM-DD" string, else ValueError.

    Canonical (zero-padded) matters beyond tidiness: dates are grouped and
    ordered as strings, which is chronological only in this form.
    """
    if isinstance(value, str):
        try:
            if datetime.strptime(value, _ISO_DATE).strftime(_ISO_DATE) == value:
                return value
        except ValueError:
            pass
    raise ValueError(f"{what} must be a 'YYYY-MM-DD' date string, got {value!r}")


def _sum_as_count(value: Any, key: str) -> int:
    """An unweighted sum from `getInfo` as an int pixel count.

    None (and a property `getInfo` dropped because it was null) is a sum
    over zero pixels -> 0. An integral float is accepted (JSON numbers); a
    fractional one means a weighted reducer was used and is refused.
    """
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be a pixel count, got {value!r}")
    if not math.isfinite(value) or value < 0 or not float(value).is_integer():
        raise ValueError(f"{key} must be a non-negative whole pixel count, got {value!r}")
    return int(value)


def tile_stats_from_features(features: list[dict]) -> list[dict]:
    """Parse `_fetch_scene_stats`'s `getInfo()["features"]` into tile dicts.

    Pure. Each feature's `properties` carries the reducer outputs keyed by
    `COUNT_KEYS` plus `date` and `scene_id`. Returns one
    `{"date", "cloud_count", "valid_count", "water_count", "scene_id"}` dict
    per feature, in input order.

    Raises:
        ValueError: a feature has no canonical `date` (a granule is never
            given a guessed date) or a count that is not a whole number.
    """
    tiles: list[dict] = []
    for feature in features:
        props = feature.get("properties") or {}
        tile = {DATE_KEY: _iso_date(props.get(DATE_KEY), "feature date")}
        for key in COUNT_KEYS:
            tile[key] = _sum_as_count(props.get(key), key)
        tile[SCENE_ID_KEY] = props.get(SCENE_ID_KEY)
        tiles.append(tile)
    return tiles


# --------------------------------------------------------------------------
# GEE-backed reduction.
# --------------------------------------------------------------------------


def _scene_count_image(
    image: ee.Image, water_mask: ee.Image, cloud_classes: tuple
) -> ee.Image:
    """The three 0/1 bands whose sums are one granule's partial sums.

    The production cloud flag (`sentinel2._cloud_flag_image`, which keeps
    SCL's own mask, so pixels outside the granule stay masked) is masked to
    production water (`sentinel2._water_mask_image`, a 0/1 image), giving
    the flag on observed water only. From that one masked band:

      - `cloud_count` = the flag itself (1 = cloud/unusable),
      - `valid_count` = its negation (1 = clear water),
      - `water_count` = 1 wherever it is unmasked (observed water),

    so the three share one mask and `cloud + valid == water` per pixel.
    `unmask(0)` (footprint kept) turns land and unobserved water inside the
    granule into explicit zeros, so each sum is a plain count.
    """
    flag = sentinel2._cloud_flag_image(image, cloud_classes)
    on_water = flag.updateMask(water_mask)
    return (
        on_water.rename(CLOUD_COUNT_KEY)
        .addBands(on_water.Not().rename(VALID_COUNT_KEY))
        .addBands(on_water.gte(0).rename(WATER_COUNT_KEY))
        .unmask(0)
    )


def _fetch_scene_stats(
    polygon_latlng: tuple[tuple[float, float], ...],
    since_date: str,
    scale_m: int,
    *,
    skip_dates: frozenset[str] = frozenset(),
) -> list[dict]:
    """Per-granule partial sums for every granule since `since_date`.

    The only function in this module that talks to Earth Engine. Granules
    intersecting the polygon from `since_date` (inclusive) through today
    (UTC; the exclusive end bound is tomorrow, as in `scene_poll.py`) are
    tagged with their UTC acquisition date; granules on a date in
    `skip_dates` are dropped server-side; each remaining granule's
    `_scene_count_image` is reduced over the polygon with an unweighted sum
    at `scale_m`, `bestEffort=False`, `maxPixels=MAX_PIXELS`. One
    `getInfo()` round trip.

    Masking parameters are read from `sentinel2` at call time, so this
    reduces exactly what a live reading masks with.

    Returns:
        Tile dicts as `tile_stats_from_features` describes.

    Raises:
        GEEAuthError: GEE not authenticated (propagated).
        ee.EEException: any per-granule computation failure (propagated;
            never converted into a decision).
    """
    initialize_ee()

    ring = [[lng, lat] for lat, lng in polygon_latlng]
    region = ee.Geometry.Polygon([ring])
    end = (datetime.now(timezone.utc) + timedelta(days=1)).strftime(_ISO_DATE)

    def _with_utc_date(image):
        image = ee.Image(image)
        return image.set(DATE_KEY, image.date().format(_EE_ISO_DATE, "UTC"))

    collection = (
        ee.ImageCollection(S2_COLLECTION)
        .filterBounds(region)
        .filterDate(since_date, end)
        .map(_with_utc_date)
    )
    if skip_dates:
        collection = collection.filter(
            ee.Filter.inList(DATE_KEY, sorted(skip_dates)).Not()
        )

    water_mask = sentinel2._water_mask_image(sentinel2.DEFAULT_MIN_WATER_OCCURRENCE_PCT)
    cloud_classes = tuple(sentinel2.DEFAULT_CLOUD_CLASSES)
    reducer = ee.Reducer.sum().unweighted()

    def _granule_sums(image):
        image = ee.Image(image)
        sums = _scene_count_image(image, water_mask, cloud_classes).reduceRegion(
            reducer=reducer,
            geometry=region,
            scale=scale_m,
            maxPixels=MAX_PIXELS,
            bestEffort=False,
        )
        return ee.Feature(None, sums).set(
            {
                DATE_KEY: image.get(DATE_KEY),
                SCENE_ID_KEY: image.get("system:index"),
            }
        )

    features = ee.FeatureCollection(collection.map(_granule_sums)).getInfo()["features"]
    return tile_stats_from_features(features)


# --------------------------------------------------------------------------
# Public entry point.
# --------------------------------------------------------------------------


def assess_new_scenes(
    polygon_latlng: tuple[tuple[float, float], ...],
    since_date: str,
    *,
    max_cloud_fraction: float | None = None,
    min_water_pixels: int | None = None,
    scale_m: int = DEFAULT_RASTER_SCALE_M,
    skip_dates: Iterable[str] = frozenset(),
    _fetch: Callable[..., list[dict]] | None = None,
) -> list[SceneAssessment]:
    """Assess every acquisition date since `since_date` not in `skip_dates`.

    Args:
        polygon_latlng: (lat, lng) vertices, implicitly closed
            (`study_area.STUDY_AREA_POLYGON_LATLNG`).
        since_date: "YYYY-MM-DD", inclusive start of the window.
        max_cloud_fraction, min_water_pixels: None reads `scene_thresholds()`
            (each variable only when its argument is None).
        scale_m: reduction scale in metres; defaults to the raster's
            `DEFAULT_RASTER_SCALE_M` (200).
        skip_dates: dates already assessed; neither reduced (filtered in the
            fetch) nor returned.
        _fetch: test seam, `(polygon_latlng, since_date, scale_m, *,
            skip_dates) -> list[tile dict]` with the partial-sum keys of the
            module docstring. Defaults to `_fetch_scene_stats`.

    Returns:
        One `SceneAssessment` per date, newest date first.

    Raises:
        ValueError (GEEConfigError for an invalid env threshold): invalid
            arguments or thresholds -- checked before any fetch -- or a
            malformed tile from the fetch.
        Anything the fetch raises (GEEAuthError, ee.EEException, ...),
        unchanged. A failure never becomes a decision.
    """
    _iso_date(since_date, "since_date")
    if max_cloud_fraction is None:
        max_cloud_fraction = _max_cloud_fraction_from_env()
    else:
        max_cloud_fraction = _check_max_cloud_fraction(max_cloud_fraction, "max_cloud_fraction")
    if min_water_pixels is None:
        min_water_pixels = _min_water_pixels_from_env()
    else:
        min_water_pixels = _check_min_water_pixels(min_water_pixels, "min_water_pixels")
    if not _is_count(scale_m) or scale_m <= 0:
        raise ValueError(f"scale_m must be a positive integer, got {scale_m!r}")
    skip = frozenset(skip_dates)

    fetch = _fetch if _fetch is not None else _fetch_scene_stats
    tiles = fetch(polygon_latlng, since_date, scale_m, skip_dates=skip)

    by_date: dict[str, list[dict]] = defaultdict(list)
    for tile in tiles:
        date = _iso_date(tile.get(DATE_KEY), "tile date")
        if date in skip:
            continue
        by_date[date].append(tile)

    assessments: list[SceneAssessment] = []
    for date in sorted(by_date, reverse=True):
        combined = combine_tiles(by_date[date])
        decision, reason = decide(
            cloud_fraction=combined["cloud_fraction"],
            water_pixels=combined["water_pixels"],
            max_cloud_fraction=max_cloud_fraction,
            min_water_pixels=min_water_pixels,
        )
        assessments.append(
            SceneAssessment(
                acquisition_date=date,
                cloud_fraction=combined["cloud_fraction"],
                water_pixels=combined["water_pixels"],
                decision=decision,
                reason=reason,
            )
        )
    return assessments
