"""
Sentinel-2 scene-freshness poll for the raster scan's event-driven trigger.

A single server-side metadata query (filterBounds + filterDate +
aggregate_max('system:time_start')) -- no per-point loop, no pixel
reduction. Measured live, 2026-08-31: 0.75s -- roughly 10,000x cheaper
than the full grid scan it gates (spec §5). Not itself a detection call:
tells the caller only whether any new Sentinel-2 scene has landed over
the study area since `since_date`, nothing about bloom status.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import ee

from .auth import initialize_ee


def get_newest_scene_timestamp(
    polygon_latlng: tuple[tuple[float, float], ...], since_date: str
) -> str | None:
    """Newest Sentinel-2 scene's acquisition timestamp intersecting
    `polygon_latlng` since `since_date`, as an ISO 8601 UTC string, or
    None if no scene was found in that window.

    Args:
        polygon_latlng: (lat, lng) vertices in order, implicitly closed
            (e.g. study_area.py's STUDY_AREA_POLYGON_LATLNG).
        since_date: "YYYY-MM-DD", the start of the lookback window.

    Raises:
        GEEAuthError: propagated, never caught.
    """
    initialize_ee()

    ring = [[lng, lat] for lat, lng in polygon_latlng]
    polygon = ee.Geometry.Polygon([ring])
    # ee.ImageCollection.filterDate(start, end)'s end bound is EXCLUSIVE
    # (system:time_start < end), and a bare "today" date string implies
    # 00:00:00Z today -- so a scene acquired earlier today (S2 over the
    # upper Gulf is typically ~03:30 UTC) would be invisible to this
    # query until tomorrow's date rolls over. Using tomorrow's date as
    # the exclusive end bound correctly includes all of today
    # (00:00:00Z through 23:59:59.999Z). This only changes what THIS
    # poll query can see -- it does not change trigger/cooldown logic
    # or the full-polygon scan behavior in backend/src/raster_scan/trigger.py.
    now_date = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")

    max_ts = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(polygon)
        .filterDate(since_date, now_date)
        .aggregate_max("system:time_start")
        .getInfo()
    )
    if max_ts is None:
        return None
    return datetime.fromtimestamp(max_ts / 1000, tz=timezone.utc).isoformat()
