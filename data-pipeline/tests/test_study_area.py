"""
Unit tests for the GEE-free study-area polygon check in
`src/study_area.py` — no Earth Engine session required or contacted.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.study_area import (
    STUDY_AREA_POLYGON_LATLNG,
    check_point_in_study_area,
    point_in_polygon,
    study_area_geojson_polygon,
)


def test_polygon_has_four_vertices_not_repeated():
    assert len(STUDY_AREA_POLYGON_LATLNG) == 4
    assert STUDY_AREA_POLYGON_LATLNG[0] != STUDY_AREA_POLYGON_LATLNG[-1]


def test_known_grid_site_is_in_study_area():
    """One of backend/src/grid.py's six monitored sites -- confirms the
    polygon actually covers real, already-in-use monitoring points."""
    chaophraya_mouth = (13.45, 100.65)
    assert point_in_polygon(*chaophraya_mouth) is True


def test_all_six_monitored_sites_are_in_study_area():
    """Every site in backend/src/grid.py's MONITORED_GRID -- if any of
    these ever fell outside the confirmed polygon, that would mean the
    polygon and the monitoring grid have drifted apart."""
    sites = {
        "bangsaen": (13.22, 100.99),
        "siracha": (13.12, 100.98),
        "thachin_mouth": (13.50, 100.35),
        "chaophraya_mouth": (13.45, 100.65),
        "upper_gulf_open_water": (13.00, 100.70),
        "chaam": (12.75, 100.05),
    }
    for name, (lat, lng) in sites.items():
        assert point_in_polygon(lat, lng) is True, f"{name} unexpectedly outside study area"


def test_bangkok_city_center_is_outside_study_area():
    bangkok = (13.7563, 100.5018)
    assert point_in_polygon(*bangkok) is False


def test_far_south_open_ocean_is_outside_study_area():
    far_south = (10.0, 100.5)
    assert point_in_polygon(*far_south) is False


def test_check_point_in_study_area_flags_in_area_point_cleanly():
    result = check_point_in_study_area(13.45, 100.65)
    assert result == {"in_study_area": True, "warning": None}


def test_check_point_in_study_area_warns_on_out_of_area_point():
    result = check_point_in_study_area(13.7563, 100.5018)
    assert result["in_study_area"] is False
    assert result["warning"] is not None
    assert "13.7563" in result["warning"]
    assert "100.5018" in result["warning"]


def test_geojson_polygon_shape_is_valid_and_closed():
    geojson = study_area_geojson_polygon()
    assert geojson["type"] == "Polygon"
    ring = geojson["coordinates"][0]
    assert ring[0] == ring[-1], "GeoJSON polygon ring must be explicitly closed"
    assert len(ring) == len(STUDY_AREA_POLYGON_LATLNG) + 1
    # GeoJSON order is [lng, lat] -- opposite of STUDY_AREA_POLYGON_LATLNG.
    first_lat, first_lng = STUDY_AREA_POLYGON_LATLNG[0]
    assert ring[0] == [first_lng, first_lat]
