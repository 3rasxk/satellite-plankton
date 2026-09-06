"""Unit tests for regional-scan grid generation -- pure, GEE-free (spec
§1/§11). No live Earth Engine session required or contacted."""

from __future__ import annotations


def test_study_area_bridge_reexports_polygon_and_check():
    from src import _study_area

    assert len(_study_area.STUDY_AREA_POLYGON_LATLNG) == 16
    result = _study_area.check_point_in_study_area(13.45, 100.65)
    assert result == {"in_study_area": True, "warning": None}


def test_generate_scan_grid_returns_only_in_polygon_points():
    from src.regional_scan.grid import generate_scan_grid
    from src._study_area import check_point_in_study_area

    points = generate_scan_grid(5.0)
    assert len(points) > 0
    for p in points:
        assert check_point_in_study_area(p["lat"], p["lng"])["in_study_area"] is True


def test_generate_scan_grid_point_count_is_plausible_at_5km():
    """The expanded Gulf polygon yields about 9,100 points at 5 km.
    Check both coverage and size so the old upper-Gulf grid cannot pass
    merely by satisfying the shared point-in-polygon predicate."""
    from src.regional_scan.grid import generate_scan_grid

    points = generate_scan_grid(5.0)
    assert 8500 <= len(points) <= 10000
    assert min(p["lat"] for p in points) < 7.0
    assert max(p["lat"] for p in points) > 13.5
    assert min(p["lng"] for p in points) < 99.5
    assert max(p["lng"] for p in points) > 102.8


def test_generate_scan_grid_point_ids_are_unique_and_row_col_derived():
    from src.regional_scan.grid import generate_scan_grid

    points = generate_scan_grid(5.0)
    ids = [p["point_id"] for p in points]
    assert len(ids) == len(set(ids))
    for p in points:
        assert p["point_id"] == f"{p['row_idx']}_{p['col_idx']}"


def test_generate_scan_grid_larger_spacing_yields_fewer_points():
    from src.regional_scan.grid import generate_scan_grid

    assert len(generate_scan_grid(10.0)) < len(generate_scan_grid(5.0))
