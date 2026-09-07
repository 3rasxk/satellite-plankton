"""
Study-area boundary — upper Gulf of Thailand, as a real polygon.

Data source: N/A — this is a project-defined boundary (human-confirmed
2026-08-24), not a satellite product. Supersedes the never-implemented
"study area bounding box" placeholder referenced in `CLAUDE.md` §4.3 and
`docs/FRONTEND_PLAN.md` (see those files' own updated notes for the
correction: no code in this project ever computed an axis-aligned bbox,
so there was nothing to "convert" — this module is the first real
definition of the boundary).

Scope: this module stores the boundary and answers "is this point inside
it," nothing more. It does NOT generate a scan grid, and `/risk-map`
does not use this to enumerate points — `/risk-map` iterates a fixed,
hand-picked list of 6 named sites (`backend/src/grid.py`), independent
of this polygon. This module exists so a caller (e.g. an arbitrary
`/detect` query) can be told plainly when a requested point falls
outside the area this project is actually calibrated/scoped for,
rather than silently returning a reading for, say, a point in Bangkok
or the open ocean far outside the upper Gulf.

The point-in-polygon check (`point_in_polygon`) is a pure, GEE-free
function (standard ray-casting), so it's unit-testable without a live
Earth Engine session. `study_area_ee_polygon()` is provided for any
future GEE-side use (e.g. `filterBounds` against the whole area) but is
not currently called by anything in this codebase.
"""

from __future__ import annotations

# Human-confirmed 2026-08-24, a rotated quadrilateral (not an axis-aligned
# box) covering the upper Gulf of Thailand. Order as given; the polygon is
# implicitly closed (last point connects back to the first) by every
# function below -- do not duplicate the first point at the end here.
STUDY_AREA_POLYGON_LATLNG: tuple[tuple[float, float], ...] = (
    (13.5411806, 99.9136220),
    (13.6147835, 101.0259840),
    (12.7135259, 100.9986423),
    (12.5046552, 99.9359575),
)


def study_area_geojson_polygon() -> dict:
    """The study area as a GeoJSON Polygon dict.

    GeoJSON coordinate order is [lng, lat] (the opposite of
    `STUDY_AREA_POLYGON_LATLNG`'s (lat, lng) order) -- converted here,
    once, so every caller doesn't have to remember to flip it. The ring
    is explicitly closed (first point repeated at the end), per the
    GeoJSON Polygon spec (RFC 7946 §3.1.6).
    """
    ring = [[lng, lat] for lat, lng in STUDY_AREA_POLYGON_LATLNG]
    ring.append(ring[0])
    return {"type": "Polygon", "coordinates": [ring]}


def study_area_ee_polygon():
    """The study area as an `ee.Geometry.Polygon`.

    Requires `initialize_ee()` to have been called (imports `ee` lazily,
    same reasoning as every other GEE-touching function in this
    package -- importing `ee` at module load time is harmless, but
    constructing a Geometry before auth is confirmed would produce a
    confusing error far from its real cause).

    Returns:
        ee.Geometry.Polygon
    """
    import ee

    ring = [[lng, lat] for lat, lng in STUDY_AREA_POLYGON_LATLNG]
    return ee.Geometry.Polygon([ring])


def point_in_polygon(
    lat: float, lng: float, polygon: tuple[tuple[float, float], ...] = STUDY_AREA_POLYGON_LATLNG
) -> bool:
    """Standard ray-casting point-in-polygon test. Pure function, no `ee`
    dependency -- unit-testable without a live GEE session.

    Args:
        lat, lng: the point to test.
        polygon: (lat, lng) vertices in order, implicitly closed (do not
            repeat the first vertex at the end). Defaults to this
            project's study area.

    Returns:
        True if (lat, lng) is inside `polygon` (boundary-inclusive is not
        guaranteed either way -- ray-casting's edge-case behavior on the
        boundary itself is not a claim this function makes; it is
        reliable for points clearly inside or clearly outside).
    """
    n = len(polygon)
    inside = False
    x, y = lng, lat  # treat (lng, lat) as (x, y) for the standard algorithm
    x1, y1 = polygon[-1][1], polygon[-1][0]
    for i in range(n):
        x2, y2 = polygon[i][1], polygon[i][0]
        if ((y1 > y) != (y2 > y)) and (x < (x2 - x1) * (y - y1) / (y2 - y1) + x1):
            inside = not inside
        x1, y1 = x2, y2
    return inside


def check_point_in_study_area(lat: float, lng: float) -> dict:
    """Caller-facing check: is (lat, lng) inside the study area?

    Returns a clear flag rather than a bare bool, so a caller like
    `/detect` can surface a real warning to the user instead of silently
    accepting an out-of-area query as if it were within this project's
    scope (CLAUDE.md's "geographic scope is the upper Gulf of Thailand
    only" limitation, made checkable rather than just stated).

    Returns:
        {'in_study_area': bool,
         'warning': str | None}  # non-None only when False
    """
    inside = point_in_polygon(lat, lng)
    if inside:
        return {"in_study_area": True, "warning": None}
    return {
        "in_study_area": False,
        "warning": (
            f"({lat}, {lng}) is outside the upper Gulf of Thailand study area "
            "this project is scoped and calibrated for (CLAUDE.md §0). A reading "
            "here is not fabricated or blocked, but should not be trusted to the "
            "same degree as a reading inside the study area."
        ),
    }
