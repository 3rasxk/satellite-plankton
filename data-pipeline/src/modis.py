"""
MODIS-Aqua Ocean Color — climatology archive (chlorophyll + SST).

Data source: NASA-processed MODIS-Aqua Level-3 mapped ocean color,
`NASA/OCEANDATA/MODIS-Aqua/L3SMI`, accessed via Google Earth Engine.
Bands used: `chlor_a` (OCI/OC3 chlorophyll-a, mg/m^3) and `sst` (sea
surface temperature, deg C). Archive begins 2002-07-04 (MODIS-Aqua
launch) through present.
Resolution: this is the daily Level-3 *mapped* product, gridded at
~4.6 km — coarser than the "~1 km" figure in CLAUDE.md's project summary,
which refers to the MODIS instrument's native nadir resolution for
ocean-color bands before Level-3 binning. State the true grid resolution
(~4.6 km) whenever this data is reported; it is still the intended
climatology baseline (CLAUDE.md §1) precisely because of its long, dense
time series, not its spatial detail.
Limitation: daily coverage has gaps from cloud, sun glint, and (for
`chlor_a`) high-sediment coastal water where the standard NASA algorithm
is known to be unreliable — the returned series is masked-pixel-filtered,
not gap-filled or interpolated. Land/very-turbid pixels return no value
for that day rather than a fabricated one; callers building a
climatology (bloom-detection) must handle sparse series, not assume one
value per day.

MODIS-history parsing/aggregation logic is implemented as pure,
GEE-free functions (`parse_get_region_rows`, `day_of_year_climatology`)
operating on plain Python/numpy structures, so it is unit-testable
against synthetic time-series data without a live Earth Engine session.
Only `get_modis_chlorophyll_history` and `get_modis_sst` themselves talk
to GEE.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import ee
import numpy as np

from .auth import initialize_ee

COLLECTION_ID = "NASA/OCEANDATA/MODIS-Aqua/L3SMI"
CHLOR_A_BAND = "chlor_a"
SST_BAND = "sst"
DEFAULT_SCALE_M = 4638  # native L3SMI grid resolution
ARCHIVE_START = "2002-07-04"
DEFAULT_CLIMATOLOGY_WINDOW_DAYS = 7
DEFAULT_SST_SEARCH_WINDOW_DAYS = 5


# --------------------------------------------------------------------------
# Pure functions — no `ee` calls, unit-testable with synthetic data.
# --------------------------------------------------------------------------


def parse_get_region_rows(rows: list, value_band: str) -> list[dict]:
    """Parse raw `ImageCollection.getRegion(...).getInfo()` output into a
    clean, sorted, deduplicated time series.

    Pure function — `rows` is the plain nested-list structure GEE returns
    (header row `['id', 'longitude', 'latitude', 'time', <bands...>]`
    followed by one row per image), so this is testable with a synthetic
    list, no `ee` import required at call time.

    Masked/no-data pixels come back as `None` in `value_band` and are
    dropped rather than coerced to 0 (a land/cloud pixel is not a
    legitimate zero chlorophyll reading). Same-day duplicate observations
    (rare overlapping swaths) are averaged together.

    Returns:
        Sorted list of {'date': 'YYYY-MM-DD', value_band: float}.
    """
    if not rows:
        return []

    header = rows[0]
    try:
        time_idx = header.index("time")
        value_idx = header.index(value_band)
    except ValueError as exc:
        raise ValueError(
            f"Expected columns 'time' and '{value_band}' in getRegion rows, got {header}"
        ) from exc

    by_date: dict[str, list[float]] = {}
    for row in rows[1:]:
        value = row[value_idx]
        if value is None:
            continue
        date_str = datetime.fromtimestamp(row[time_idx] / 1000, tz=timezone.utc).strftime(
            "%Y-%m-%d"
        )
        by_date.setdefault(date_str, []).append(float(value))

    return [
        {"date": date_str, value_band: float(np.mean(values))}
        for date_str, values in sorted(by_date.items())
    ]


def day_of_year_climatology(
    series: list[dict],
    value_key: str,
    target_date: str,
    window_days: int = DEFAULT_CLIMATOLOGY_WINDOW_DAYS,
) -> dict | None:
    """Mean/std of `value_key` across all years within +/- window_days of
    `target_date`'s day-of-year, wrapping around the year boundary.

    Pure function over a list of {'date': 'YYYY-MM-DD', value_key: float}
    (the shape `parse_get_region_rows` produces) — no `ee` dependency, so
    this is directly unit-testable with synthetic multi-year series. This
    is the day-of-year climatology CLAUDE.md §1 specifies as the anomaly
    baseline; `bloom-detection` is expected to build on this rather than
    reimplement it.

    Returns:
        {'mean': float, 'std': float, 'n': int} or None if no
        observations fall in the window (e.g. an empty series).
    """
    target = datetime.strptime(target_date, "%Y-%m-%d")
    target_doy = target.timetuple().tm_yday

    matched = []
    for row in series:
        d = datetime.strptime(row["date"], "%Y-%m-%d")
        doy = d.timetuple().tm_yday
        diff = abs(doy - target_doy)
        diff = min(diff, 365 - diff)  # wrap around year boundary
        if diff <= window_days:
            matched.append(row[value_key])

    if not matched:
        return None

    return {
        "mean": float(np.mean(matched)),
        "std": float(np.std(matched)),
        "n": len(matched),
    }


# --------------------------------------------------------------------------
# GEE-backed extraction.
# --------------------------------------------------------------------------


def _fetch_band_series(lat: float, lng: float, band: str, scale: int = DEFAULT_SCALE_M) -> list[dict]:
    """Shared GEE call: full-archive time series for one L3SMI band at a point."""
    initialize_ee()
    point = ee.Geometry.Point([lng, lat])
    collection = ee.ImageCollection(COLLECTION_ID).select(band).filterDate(
        ARCHIVE_START, datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    )
    rows = collection.getRegion(point, scale).getInfo()
    return parse_get_region_rows(rows, band)


def get_modis_chlorophyll_history(lat: float, lng: float) -> list[dict]:
    """Full MODIS-Aqua chlor_a time series at a point, 2002-present.

    This is the archive `bloom-detection` builds its per-location,
    per-day-of-year climatology from (CLAUDE.md §1) — it intentionally
    returns the full masked-pixel-filtered series, not a single latest
    value or a pre-aggregated climatology.

    Args:
        lat, lng: WGS84 coordinates.

    Returns:
        [{'date': 'YYYY-MM-DD', 'chlor_a': float}, ...] sorted ascending,
        one entry per day with a valid (cloud-free, non-land) reading.
        Gaps in the series are expected, not an error.

    Raises:
        GEEAuthError: GEE not authenticated.
    """
    return _fetch_band_series(lat, lng, CHLOR_A_BAND)


def get_modis_sst(
    lat: float,
    lng: float,
    date: str,
    search_window_days: int = DEFAULT_SST_SEARCH_WINDOW_DAYS,
    climatology_window_days: int = DEFAULT_CLIMATOLOGY_WINDOW_DAYS,
) -> dict:
    """Sea surface temperature at a point/date plus its seasonal normal.

    Pulls the full MODIS-Aqua `sst` history at the point (same product as
    chlorophyll), picks the reading nearest `date` within
    `search_window_days`, and separately computes the day-of-year
    climatology (mean/std across all archive years) via
    `day_of_year_climatology` — this is the "SST anomaly" input the
    prediction layer in docs/DETECTION_PLAN.md §3 needs (warm water
    favouring dinoflagellate growth).

    Args:
        lat, lng: WGS84 coordinates.
        date: target date, "YYYY-MM-DD".
        search_window_days: how far from `date` to look for the nearest
            valid SST reading (cloud/land gaps are common day-to-day).
        climatology_window_days: day-of-year window for the seasonal mean.

    Returns:
        {'sst': float | None, 'sst_date': str | None,
         'sst_climatology': {'mean': float, 'std': float, 'n': int} | None}
        `sst` is None if no valid reading fell within the search window
        (e.g. persistent cloud) — this is reported, not silently dropped.

    Raises:
        GEEAuthError: GEE not authenticated.
    """
    series = _fetch_band_series(lat, lng, SST_BAND)

    target = datetime.strptime(date, "%Y-%m-%d")
    nearest = None
    nearest_diff = None
    for row in series:
        d = datetime.strptime(row["date"], "%Y-%m-%d")
        diff = abs((d - target).days)
        if diff <= search_window_days and (nearest_diff is None or diff < nearest_diff):
            nearest = row
            nearest_diff = diff

    climatology = day_of_year_climatology(series, SST_BAND, date, climatology_window_days)

    return {
        "sst": nearest[SST_BAND] if nearest else None,
        "sst_date": nearest["date"] if nearest else None,
        "sst_climatology": climatology,
    }
