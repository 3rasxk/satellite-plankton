"""
Study-area boundary — the Gulf of Thailand on the Thai side, as a real
polygon.

Data source: N/A — this is a project-defined boundary, not a satellite
product and not an official maritime limit. Human-confirmed 2026-08-24 as
a four-vertex quadrilateral over the upper Gulf; widened 2026-09-06 to
the whole Thai side of the Gulf, from the Bangkok bight south to the
Malaysian border. Supersedes the never-implemented "study area bounding
box" placeholder referenced in `CLAUDE.md` §4.3 and
`docs/FRONTEND_PLAN.md`.

NOT a maritime boundary. The offshore edge (roughly 102.6–103.0°E) is a
hand-drawn approximation of where Thai Gulf waters give way to
Cambodian, Vietnamese and Malaysian ones, chosen to keep the scan inside
water Thailand would plausibly act on. It is not an EEZ claim, it does
not encode the Thailand–Cambodia overlapping claims area or the
Thailand–Malaysia Joint Development Area, and it must not be cited as
any of those. Move a vertex if it excludes water you care about —
nothing in this project depends on its exact position beyond deciding
which points get scanned and which `/detect` queries are flagged
out-of-area.

Coverage is not calibration. Widening the polygon widened where the
system will *read*; it did not validate anything anywhere. The indices
remain uncalibrated and the anomaly layer inactive (see LIMITATIONS.md),
equally so at every point inside this boundary.

Scope: this module stores the boundary and answers "is this point inside
it". Two consumers, with different relationships to it:
  - `backend/src/regional_scan/grid.py` walks this polygon's bounding
    box at a km spacing and keeps the points `check_point_in_study_area`
    accepts — so this boundary determines the regional scan grid.
  - `/risk-map` does NOT: it iterates a fixed, hand-picked list of 7
    named sites (`backend/src/grid.py`), all of which happen to fall
    inside this polygon but none of which are derived from it.
It also exists so an arbitrary `/detect` query can be told plainly when
a requested point falls outside the area this project is scoped for,
rather than silently returning a reading for, say, a point in Bangkok or
in the middle of the South China Sea.

The point-in-polygon check (`point_in_polygon`) is a pure, GEE-free
function (standard ray-casting), so it's unit-testable without a live
Earth Engine session. `study_area_ee_polygon()` is provided for any
future GEE-side use (e.g. `filterBounds` against the whole area) but is
not currently called by anything in this codebase.
"""

from __future__ import annotations

# Thai-side Gulf of Thailand, clockwise from the upper Gulf's west shore:
# east across the head of the bight, down the eastern seaboard to Trat,
# out to the approximate offshore limit, south past the Malaysian border,
# then back up the peninsula's east coast. Order as given; the polygon is
# implicitly closed (last point connects back to the first) by every
# function below -- do not duplicate the first point at the end here.
#
# Coastal vertices trace the shoreline coarsely, so the polygon does
# can include land. The live cloud/water checks determine whether each
# point has a usable water reading; the polygon alone cannot establish
# a land count or predict its final reading status.
#
# The offshore vertices are an approximation, not a maritime boundary --
# see this module's docstring before quoting them anywhere.
STUDY_AREA_POLYGON_LATLNG: tuple[tuple[float, float], ...] = (
    (13.55, 100.00),   # upper Gulf, western side
    (13.60, 100.60),   # head of the Bangkok bight, off the Chao Phraya mouth
    (13.55, 101.05),   # upper Gulf, eastern side
    (12.60, 101.70),   # Rayong
    (12.35, 102.35),   # Chanthaburi / Trat
    (11.60, 103.00),   # offshore, approaching the Cambodian maritime limit
    (9.50, 103.00),    # mid-Gulf offshore limit
    (7.80, 102.60),    # offshore, approaching the Thai-Malaysian JDA
    (6.50, 102.10),    # Narathiwat, at the Malaysian border
    (6.90, 101.30),    # Pattani
    (7.20, 100.60),    # Songkhla
    (8.50, 99.95),     # Nakhon Si Thammarat
    (9.50, 99.25),     # Surat Thani
    (10.50, 99.20),    # Chumphon
    (11.80, 99.75),    # Prachuap Khiri Khan
    (12.50, 99.90),    # back toward Hua Hin, closing the ring
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
    scope (CLAUDE.md's "geographic scope is the Gulf of Thailand, Thai
    side" limitation, made checkable rather than just stated).

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
            f"({lat}, {lng}) is outside the Gulf of Thailand (Thai side) study "
            "area this project is scoped for (CLAUDE.md §0). A reading here is "
            "not fabricated or blocked, but falls outside the water this system "
            "is built to watch."
        ),
    }
