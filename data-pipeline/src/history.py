"""
Per-site NDCI history from Sentinel-2 -- the input rows for the TEST baseline.

Data source: Copernicus Sentinel-2 Level-2A surface reflectance,
`COPERNICUS/S2_SR_HARMONIZED`, via Google Earth Engine, masked by exactly
the same cloud flag (Scene Classification Layer) and water mask (JRC Global
Surface Water, with the ETOPO1 fallback where JRC has no data) that
`sentinel2.py` uses for a live reading. Nothing in the masking is
re-implemented here: `_fetch_features` calls `sentinel2._cloud_flag_image`
and `sentinel2._water_mask_image`, and the per-scene statistics are parsed
by `sentinel2.cloud_fraction_from_stats` / `sentinel2.band_means_from_stats`.
A historical row therefore describes the same quantity, built the same way,
as the live NDCI it will later be compared with. That sameness is what
`preprocessing_params()` writes down so the baseline can refuse to mix
history made under different settings.

What one row is: for one scene over one site, the NDCI
`(B5 - B4) / (B5 + B4)` of the *band means* over the clear-sky water pixels
of a small circular buffer around the point (`DEFAULT_BUFFER_M`, reduced at
`DEFAULT_SCALE_M`). It is the ratio of two means, not the mean of per-pixel
ratios, which is how `get_sentinel2_bands` + `detection/src/indices.py`
form the live reading.

Limitations -- read before using the rows as evidence:
  - Point-buffer mean, not raster sampling. Each row summarises roughly a
    30 m disc at one coordinate. It says nothing about the surrounding
    water, and it is not the per-cell values the full-area raster stores.
    Detection is at satellite pixel resolution: water-colour signatures
    only, never individual organisms, and a small or dispersed bloom can be
    missed.
  - Cloud-masked days only. A scene is kept only if its buffer cloud
    fraction is within `max_cloud_fraction` and every band retains at
    least one water pixel. Clear days are not a random sample of days --
    during the southwest monsoon most acquisitions are rejected -- so the
    surviving history over-represents calm, clear weather. Absence of a
    row is not evidence of an absent bloom.
  - No atmospheric validation. Surface reflectance is Google's/ESA's L2A
    product taken as given; this module does not check the atmospheric
    correction, sun glint, or turbid river-mouth water, where the
    JRC/ETOPO1 water mask is the least trustworthy. The values are
    dimensionless index readings, not chlorophyll concentrations.
  - Several tiles can cover one site on one date and each yields its own
    row; reducing them to one value per day is the consumer's job
    (`assess_signal_anomaly`), not done here.

Everything that touches `ee` lives in `_fetch_features`. The rest -- row
extraction and the preprocessing parameter dict -- is pure, offline-testable
code that parses plain dicts.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Callable

import ee

from . import sentinel2
from .auth import initialize_ee
from .sentinel2 import NoWaterPixelsError

S2_COLLECTION = "COPERNICUS/S2_SR_HARMONIZED"

# Property names `_fetch_features` attaches to each feature next to the
# reducer outputs ("B2_mean", "cloud_flag_count", ...). Plain names, no
# leading underscore, because they are part of the contract with
# `rows_from_stats`; neither can collide with a reducer output key.
TIME_PROPERTY = "t"  # system:time_start, milliseconds since the Unix epoch
SCENE_ID_PROPERTY = "scene_id"  # system:index

# Spectral index written into the preprocessing parameters, so a change of
# index definition changes the baseline signature too.
NDCI_DEFINITION = "ndci=(B5-B4)/(B5+B4)"
SAMPLING_DEFINITION = "point-buffer-mean"


def preprocessing_params() -> dict:
    """Canonical description of how history rows are produced.

    Built from the *live* constants in `sentinel2` on every call (module
    attribute lookups, not names bound at import), so changing any of them
    changes the returned dict and therefore the baseline's preprocessing
    signature. Returns plain JSON types (lists, not tuples) and a fresh dict
    each time.
    """
    return {
        "collection": S2_COLLECTION,
        "bands": list(sentinel2.BANDS),
        "cloud_classes": list(sentinel2.DEFAULT_CLOUD_CLASSES),
        "max_cloud_fraction": sentinel2.DEFAULT_MAX_CLOUD_FRACTION,
        "min_water_occurrence_pct": sentinel2.DEFAULT_MIN_WATER_OCCURRENCE_PCT,
        "buffer_m": sentinel2.DEFAULT_BUFFER_M,
        "scale_m": sentinel2.DEFAULT_SCALE_M,
        "sampling": SAMPLING_DEFINITION,
        "index": NDCI_DEFINITION,
    }


def _utc_date(time_ms: object) -> str | None:
    """`YYYY-MM-DD` (UTC) from epoch milliseconds; None if not a usable time."""
    if isinstance(time_ms, bool) or not isinstance(time_ms, (int, float)):
        return None
    if not math.isfinite(time_ms):
        return None
    try:
        return datetime.fromtimestamp(time_ms / 1000, tz=timezone.utc).strftime(
            "%Y-%m-%d"
        )
    except (OverflowError, OSError, ValueError):
        return None


def rows_from_stats(
    features: list[dict], *, max_cloud_fraction: float | None = None
) -> list[dict]:
    """Turn per-scene `reduceRegion` features into NDCI history rows.

    Pure: parses the plain dicts `FeatureCollection.getInfo()["features"]`
    returns, with no `ee` objects and no network. Each feature's
    `properties` carries the band means/counts and the cloud-flag
    mean/count that `sentinel2` produces, plus `t` (acquisition time,
    milliseconds since the epoch) and optionally `scene_id`.

    A feature is skipped, never repaired, when:
      - its buffer cloud fraction is above `max_cloud_fraction`
        (`sentinel2.cloud_fraction_from_stats`; a buffer with no valid SCL
        pixel counts as fully cloudy);
      - any band kept zero water pixels (`sentinel2.band_means_from_stats`
        raises `NoWaterPixelsError`) -- the same all-bands-or-nothing rule
        a live reading obeys;
      - B5 + B4 is zero or the resulting NDCI is not finite;
      - it has no usable acquisition time (a row is never given a guessed
        date).

    `max_cloud_fraction=None` means `sentinel2.DEFAULT_MAX_CLOUD_FRACTION`,
    read at call time so it always agrees with `preprocessing_params()`.

    Returns one row per surviving feature, sorted by date (then scene id):
        {"acquisition_date": "YYYY-MM-DD" (UTC), "ndci": float,
         "cloud_fraction": float, "scene_id": str | None}
    Several tiles over one date are all returned.
    """
    if max_cloud_fraction is None:
        max_cloud_fraction = sentinel2.DEFAULT_MAX_CLOUD_FRACTION

    rows: list[dict] = []
    for feature in features:
        stats = feature.get("properties") or {}

        acquisition_date = _utc_date(stats.get(TIME_PROPERTY))
        if acquisition_date is None:
            continue

        cloud_fraction = sentinel2.cloud_fraction_from_stats(stats)
        if cloud_fraction > max_cloud_fraction:
            continue

        try:
            means = sentinel2.band_means_from_stats(stats, tuple(sentinel2.BANDS))
        except NoWaterPixelsError:
            continue

        b4 = means.get("B4")
        b5 = means.get("B5")
        if b4 is None or b5 is None:
            continue
        denominator = b5 + b4
        if denominator == 0:
            continue
        ndci = (b5 - b4) / denominator
        if not math.isfinite(ndci):
            continue

        rows.append(
            {
                "acquisition_date": acquisition_date,
                "ndci": ndci,
                "cloud_fraction": cloud_fraction,
                "scene_id": stats.get(SCENE_ID_PROPERTY),
            }
        )

    rows.sort(key=lambda row: (row["acquisition_date"], row["scene_id"] or ""))
    return rows


def _fetch_features(
    region_lat: float, region_lng: float, start: str, end: str
) -> list[dict]:
    """Per-scene masked statistics for one site over `[start, end)`.

    The only function in this module that talks to Earth Engine. It mirrors
    `_candidate_stats` inside `sentinel2._resolve_sentinel2_scene`: the same
    point buffer, the same B2-B6 selection, the same
    `updateMask(water AND NOT cloud)` followed by `addBands(cloud_flag)`
    (added after the mask so its mean stays the buffer's true cloud
    fraction), the same mean+count reducer, scale and `maxPixels`. The
    difference is the window: every scene between `start` (inclusive) and
    `end` (exclusive, like `filterDate`), not a backward walk from one day.

    One batched `getInfo()` round trip for the whole window. Constants are
    read from `sentinel2` at call time and passed explicitly so what is
    reduced here is exactly what `preprocessing_params()` reports.

    Returns the raw feature dicts; filtering and NDCI are `rows_from_stats`.

    Raises:
        GEEAuthError: GEE not authenticated (propagated, never swallowed).
    """
    initialize_ee()

    region = ee.Geometry.Point([region_lng, region_lat]).buffer(
        sentinel2.DEFAULT_BUFFER_M
    )
    collection = (
        ee.ImageCollection(S2_COLLECTION)
        .filterBounds(region)
        .filterDate(start, end)
    )

    water_mask_img = sentinel2._water_mask_image(
        sentinel2.DEFAULT_MIN_WATER_OCCURRENCE_PCT
    )
    reducer = ee.Reducer.mean().combine(ee.Reducer.count(), sharedInputs=True)
    bands = list(sentinel2.BANDS)
    scale = sentinel2.DEFAULT_SCALE_M
    cloud_classes = tuple(sentinel2.DEFAULT_CLOUD_CLASSES)

    def _scene_stats(image):
        image = ee.Image(image)
        cloud_flag = sentinel2._cloud_flag_image(image, cloud_classes)
        sample_img = (
            image.select(bands)
            .updateMask(water_mask_img.And(cloud_flag.Not()))
            .addBands(cloud_flag)
        )
        stats = sample_img.reduceRegion(
            reducer=reducer,
            geometry=region,
            scale=scale,
            maxPixels=1e7,
        )
        return ee.Feature(None, stats).set(
            {
                TIME_PROPERTY: image.get("system:time_start"),
                SCENE_ID_PROPERTY: image.get("system:index"),
            }
        )

    return ee.FeatureCollection(collection.map(_scene_stats)).getInfo()["features"]


def get_ndci_history(
    lat: float,
    lng: float,
    start: str,
    end: str,
    *,
    max_cloud_fraction: float | None = None,
    _fetch: Callable[[float, float, str, str], list[dict]] | None = None,
) -> list[dict]:
    """NDCI history rows for one point over `[start, end)`.

    Args:
        lat, lng: WGS84 coordinates of the site.
        start, end: ISO dates "YYYY-MM-DD". `end` is exclusive, like Earth
            Engine's `filterDate`, so pass the day after the last day wanted.
        max_cloud_fraction: reject scenes whose buffer cloud fraction is
            above this. None means `sentinel2.DEFAULT_MAX_CLOUD_FRACTION`.
        _fetch: test seam, `(lat, lng, start, end) -> list[feature dict]`.
            Defaults to `_fetch_features` (the only Earth Engine call).

    Returns:
        Rows as described in `rows_from_stats`, sorted by date. See the
        module docstring for what these rows do and do not represent.

    Raises:
        GEEAuthError: GEE not authenticated (default fetch only).
    """
    fetch = _fetch if _fetch is not None else _fetch_features
    features = fetch(lat, lng, start, end)
    return rows_from_stats(features, max_cloud_fraction=max_cloud_fraction)
