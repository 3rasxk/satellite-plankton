"""
Rainfall proxy for nutrient-loading — upper Gulf of Thailand river mouths.

Data source: CHIRPS daily precipitation, `UCSB-CHG/CHIRPS/DAILY`
(Climate Hazards Group InfraRed Precipitation with Station data),
accessed via Google Earth Engine.
Resolution: ~5.5 km (0.05 degree) grid, daily.
Limitation: this is a rainfall proxy for river runoff / nutrient loading
(docs/DETECTION_PLAN.md §3), not a hydrological model — it does not
account for upstream catchment size, reservoir regulation, or travel
time from rainfall to river-mouth discharge, all of which matter for the
four named rivers (Chao Phraya, Tha Chin, Mae Klong, Bang Pakong) and
differ substantially between them. `RIVER_MOUTHS` coordinates below are
approximate estuary locations for identifying the nearest named river
mouth to a query point; they are hand-placed from public map references,
not sourced from a hydrological dataset, and should be treated as
indicative only.

The nearest-river-mouth lookup is implemented as a pure, GEE-free
function (`nearest_river_mouth`) using plain haversine distance, so it
is unit-testable without a live Earth Engine session. Only
`get_rainfall_proxy` itself talks to GEE.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

import ee

from .auth import initialize_ee

COLLECTION_ID = "UCSB-CHG/CHIRPS/DAILY"
PRECIP_BAND = "precipitation"
DEFAULT_SCALE_M = 5566  # ~0.05 degree CHIRPS grid
DEFAULT_LOOKBACK_DAYS = 7
DEFAULT_BUFFER_M = 5000

# Approximate estuary coordinates (WGS84) for the four river mouths named
# in docs/DETECTION_PLAN.md §3 as the upper Gulf's main nutrient sources.
# Hand-placed from public map references — not a surveyed/cited dataset.
RIVER_MOUTHS = {
    "Chao Phraya": (13.5410, 100.5850),
    "Tha Chin": (13.5470, 100.2700),
    "Mae Klong": (13.3670, 99.9950),
    "Bang Pakong": (13.4990, 100.9750),
}


# --------------------------------------------------------------------------
# Pure functions — no `ee` calls, unit-testable with synthetic coordinates.
# --------------------------------------------------------------------------


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in km between two WGS84 points. Pure function."""
    r_km = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * r_km * math.asin(math.sqrt(a))


def nearest_river_mouth(lat: float, lng: float) -> dict:
    """Nearest named river mouth to (lat, lng) and the distance to it.

    Pure function over the `RIVER_MOUTHS` constant — no `ee` dependency,
    so directly unit-testable with synthetic coordinates.

    Returns:
        {'name': str, 'distance_km': float}
    """
    best_name = None
    best_distance = math.inf
    for name, (mouth_lat, mouth_lng) in RIVER_MOUTHS.items():
        distance = haversine_km(lat, lng, mouth_lat, mouth_lng)
        if distance < best_distance:
            best_name = name
            best_distance = distance
    return {"name": best_name, "distance_km": round(best_distance, 1)}


# --------------------------------------------------------------------------
# GEE-backed extraction.
# --------------------------------------------------------------------------


def get_rainfall_proxy(
    lat: float,
    lng: float,
    date: str,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    buffer_m: int = DEFAULT_BUFFER_M,
) -> dict:
    """Recent cumulative rainfall near a point, as a nutrient-loading proxy.

    Sums CHIRPS daily precipitation over the `lookback_days` ending on
    `date` (inclusive), sampled over a small buffer around the point.
    Also reports the nearest of the four named river mouths for context,
    since rainfall's relevance to nutrient loading in the upper Gulf is
    concentrated at those outflows (docs/DETECTION_PLAN.md §3) — this is
    informational only, the function does not relocate the query point.

    Args:
        lat, lng: WGS84 coordinates.
        date: end date of the lookback window, "YYYY-MM-DD".
        lookback_days: number of days (inclusive of `date`) to sum.
        buffer_m: radius (metres) of the sample buffer around the point.

    Returns:
        {'recent_rainfall_mm': float, 'lookback_days': int,
         'window_start': str, 'window_end': str,
         'nearest_river_mouth': str, 'river_mouth_distance_km': float}

    Raises:
        GEEAuthError: GEE not authenticated.
    """
    initialize_ee()

    end = datetime.strptime(date, "%Y-%m-%d")
    start = end - timedelta(days=lookback_days - 1)
    # CHIRPS filterDate end is exclusive, so add one day to include `date`.
    window_end_exclusive = (end + timedelta(days=1)).strftime("%Y-%m-%d")

    point = ee.Geometry.Point([lng, lat])
    region = point.buffer(buffer_m)

    total_precip_img = (
        ee.ImageCollection(COLLECTION_ID)
        .select(PRECIP_BAND)
        .filterDate(start.strftime("%Y-%m-%d"), window_end_exclusive)
        .filterBounds(region)
        .sum()
    )

    result = total_precip_img.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=region,
        scale=DEFAULT_SCALE_M,
        maxPixels=1e7,
    ).getInfo()

    recent_rainfall_mm = result.get(PRECIP_BAND)
    mouth = nearest_river_mouth(lat, lng)

    return {
        "recent_rainfall_mm": recent_rainfall_mm,
        "lookback_days": lookback_days,
        "window_start": start.strftime("%Y-%m-%d"),
        "window_end": date,
        "nearest_river_mouth": mouth["name"],
        "river_mouth_distance_km": mouth["distance_km"],
    }
