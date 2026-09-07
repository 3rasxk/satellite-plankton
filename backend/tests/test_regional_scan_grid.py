"""Unit tests for regional-scan grid generation -- pure, GEE-free (spec
§1/§11). No live Earth Engine session required or contacted."""

from __future__ import annotations


def test_study_area_bridge_reexports_polygon_and_check():
    from src import _study_area

    assert len(_study_area.STUDY_AREA_POLYGON_LATLNG) == 4
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
    """Spec §1 measured 500 in-polygon points at 5km spacing over the
    real ~120.6km x 123.2km bounding box. Exact count depends on grid
    origin/rounding choices, so this asserts a plausible range rather
    than the literal 500 -- a brittle exact match would break on any
    reasonable, still-correct implementation choice."""
    from src.regional_scan.grid import generate_scan_grid

    points = generate_scan_grid(5.0)
    assert 350 <= len(points) <= 650


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
