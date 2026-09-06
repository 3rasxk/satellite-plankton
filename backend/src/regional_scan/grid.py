"""
Regional bloom scan grid generation (spec §1): a regular lat/lng grid at
a configurable km spacing across the study-area polygon's bounding box,
filtered to points actually inside the polygon
(`backend/src/_study_area.py`'s `check_point_in_study_area`).

The polygon covers the Thai side of the whole Gulf of Thailand as of
2026-09-06, so the default 5 km spacing yields ~9,100 points (it was
~500 while the polygon was the upper-Gulf quadrilateral). Grid size is
therefore driven entirely by that polygon: widening it multiplies scan
cost quadratically in the linear extent, and `spacing_km` is the only
lever here for bringing that back down.

Pure, GEE-free -- unit-testable without a live Earth Engine session
(docs/superpowers/specs/2026-08-31-regional-scan-design.md §1/§11).

Points are indexed by (row_idx, col_idx) -- their position in the
regular pre-filter grid -- so `backend/src/regional_scan/clustering.py`'s
8-connectivity adjacency check is an O(1) dict lookup, never a distance
computation.
"""

from __future__ import annotations

import math

from .. import _study_area

_KM_PER_DEGREE_LAT = 111.32  # standard WGS84 approximation, same order docs/DETECTION_PLAN.md uses


def generate_scan_grid(spacing_km: float) -> list[dict]:
    """Generate the in-polygon scan grid at `spacing_km` spacing.

    Args:
        spacing_km: grid spacing in kilometers (spec §1 default: 5).

    Returns:
        list of {'lat': float, 'lng': float, 'row_idx': int, 'col_idx': int,
                  'point_id': str}, one per in-polygon grid cell.
        `point_id` is f"{row_idx}_{col_idx}" -- a stable key across runs
        at the same spacing (used as RegionalScanPoint's primary key and
        for cluster member traceability, spec §4/§6).
    """
    lats = [lat for lat, _ in _study_area.STUDY_AREA_POLYGON_LATLNG]
    lngs = [lng for _, lng in _study_area.STUDY_AREA_POLYGON_LATLNG]
    min_lat, max_lat = min(lats), max(lats)
    min_lng, max_lng = min(lngs), max(lngs)

    mean_lat_rad = math.radians((min_lat + max_lat) / 2)
    lat_step_deg = spacing_km / _KM_PER_DEGREE_LAT
    lng_step_deg = spacing_km / (_KM_PER_DEGREE_LAT * math.cos(mean_lat_rad))

    n_rows = int((max_lat - min_lat) / lat_step_deg) + 1
    n_cols = int((max_lng - min_lng) / lng_step_deg) + 1

    points: list[dict] = []
    for row_idx in range(n_rows):
        lat = min_lat + row_idx * lat_step_deg
        for col_idx in range(n_cols):
            lng = min_lng + col_idx * lng_step_deg
            if _study_area.check_point_in_study_area(lat, lng)["in_study_area"]:
                points.append(
                    {
                        "lat": lat,
                        "lng": lng,
                        "row_idx": row_idx,
                        "col_idx": col_idx,
                        "point_id": f"{row_idx}_{col_idx}",
                    }
                )
    return points
