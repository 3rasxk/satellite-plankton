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


def test_polygon_vertices_are_not_repeated():
    """16 vertices tracing the Thai side of the Gulf (widened 2026-09-06
    from the original 4-vertex upper-Gulf quadrilateral). The ring is
    closed implicitly, so the first vertex must not be repeated."""
    assert len(STUDY_AREA_POLYGON_LATLNG) == 16
    assert STUDY_AREA_POLYGON_LATLNG[0] != STUDY_AREA_POLYGON_LATLNG[-1]


def test_known_grid_site_is_in_study_area():
    """One of backend/src/grid.py's monitored sites -- confirms the
    polygon actually covers real, already-in-use monitoring points."""
    chaophraya_mouth = (13.45, 100.65)
    assert point_in_polygon(*chaophraya_mouth) is True


def test_all_seven_monitored_sites_are_in_study_area():
    """Every site in backend/src/grid.py's MONITORED_GRID, at its real
    coordinates -- if any of these ever fell outside the polygon, the
    polygon and the monitoring grid would have drifted apart."""
    sites = {
        "bangsaen": (13.2600, 100.8800),
        "siracha": (13.1600, 100.8800),
        "thachin_mouth": (13.4200, 100.2700),
        "chaophraya_mouth": (13.4000, 100.5800),
        "chaam": (12.7800, 100.0400),
        "bangpakong_mouth": (13.4200, 100.9000),
        "pattaya": (12.9400, 100.8400),
    }
    for name, (lat, lng) in sites.items():
        assert point_in_polygon(lat, lng) is True, f"{name} unexpectedly outside study area"


def test_bangkok_city_center_is_outside_study_area():
    bangkok = (13.7563, 100.5018)
    assert point_in_polygon(*bangkok) is False


def test_the_lower_gulf_is_inside_after_the_2026_09_06_widening():
    """The whole point of widening past the upper Gulf: water off the
    peninsula's east coast, which the original quadrilateral excluded,
    is now in scope. (10.0, 100.5) in particular used to be asserted as
    OUTSIDE -- it is mid-Gulf water off Surat Thani and is now inside."""
    lower_gulf = {
        "mid_gulf_off_surat_thani": (10.00, 100.50),
        "off_songkhla": (7.30, 100.80),
        "off_pattani": (7.00, 101.40),
        "off_chumphon": (10.40, 99.60),
        "mid_gulf_open_water": (9.50, 101.50),
        "off_trat": (12.10, 102.40),
    }
    for name, (lat, lng) in lower_gulf.items():
        assert point_in_polygon(lat, lng) is True, f"{name} unexpectedly outside study area"


def test_neighbouring_countries_waters_stay_outside():
    """The offshore edge is a rough approximation of where Thai Gulf
    water gives way to its neighbours' (see the module docstring: it is
    NOT a maritime boundary). It must still be far enough west that the
    scan does not wander into clearly foreign water."""
    outside = {
        "sihanoukville_cambodia": (10.63, 103.50),
        "ca_mau_vietnam": (8.60, 104.80),
        "kota_bharu_malaysia": (6.13, 102.24),
        "south_china_sea": (9.00, 105.50),
    }
    for name, (lat, lng) in outside.items():
        assert point_in_polygon(lat, lng) is False, f"{name} unexpectedly inside study area"


def test_the_andaman_side_of_the_peninsula_is_outside():
    """Phuket is at a similar latitude to in-scope Gulf water but on the
    wrong coast -- a polygon that accepted it would be catching the
    wrong sea entirely."""
    assert point_in_polygon(7.90, 98.30) is False


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
