"""Unit tests for grid-adjacency connected-components clustering (spec
§4) -- pure, no GEE, no DB."""

from __future__ import annotations

from src.regional_scan.clustering import cluster_points


def _point(point_id, row, col, z, tier, actual_date=None):
    return {
        "point_id": point_id, "lat": 13.0 + row * 0.01, "lng": 100.0 + col * 0.01,
        "row_idx": row, "col_idx": col, "anomaly_z": z, "threshold_tier": tier,
        "actual_date": actual_date,
    }


def test_empty_input_returns_empty_list():
    assert cluster_points([]) == []


def test_single_point_forms_its_own_cluster():
    points = [_point("0_0", 0, 0, 1.6, "elevated")]
    clusters = cluster_points(points)
    assert len(clusters) == 1
    c = clusters[0]
    assert c["cell_count"] == 1
    assert c["member_point_ids"] == ["0_0"]
    assert c["centroid_lat"] == points[0]["lat"]
    assert c["mean_anomaly_z"] == 1.6
    assert c["max_anomaly_z"] == 1.6
    assert c["threshold_tier"] == "elevated"


def test_8_connected_points_merge_into_one_cluster():
    # A 2x2 block: every cell touches every other cell within radius 1.
    points = [
        _point("0_0", 0, 0, 1.6, "elevated"),
        _point("0_1", 0, 1, 1.7, "elevated"),
        _point("1_0", 1, 0, 2.1, "warning"),
        _point("1_1", 1, 1, 1.8, "elevated"),
    ]
    clusters = cluster_points(points)
    assert len(clusters) == 1
    c = clusters[0]
    assert c["cell_count"] == 4
    assert set(c["member_point_ids"]) == {"0_0", "0_1", "1_0", "1_1"}
    # Highest tier among members wins.
    assert c["threshold_tier"] == "warning"
    assert c["max_anomaly_z"] == 2.1
    assert c["mean_anomaly_z"] == (1.6 + 1.7 + 2.1 + 1.8) / 4


def test_diagonal_adjacency_merges():
    # (0,0) and (1,1) differ by 1 in both row and col -- 8-connectivity,
    # not 4-connectivity.
    points = [_point("0_0", 0, 0, 1.6, "elevated"), _point("1_1", 1, 1, 1.7, "elevated")]
    clusters = cluster_points(points)
    assert len(clusters) == 1
    assert clusters[0]["cell_count"] == 2


def test_far_apart_points_form_separate_clusters():
    points = [_point("0_0", 0, 0, 1.6, "elevated"), _point("10_10", 10, 10, 1.7, "elevated")]
    clusters = cluster_points(points)
    assert len(clusters) == 2
    assert {c["cell_count"] for c in clusters} == {1}


def test_transitive_chain_merges_into_one_cluster():
    # (0,0)-(1,1)-(2,2) each pair is 8-adjacent, so the whole chain is
    # one connected component even though (0,0) and (2,2) are not
    # directly adjacent to each other.
    points = [
        _point("0_0", 0, 0, 1.6, "elevated"),
        _point("1_1", 1, 1, 1.7, "elevated"),
        _point("2_2", 2, 2, 1.8, "elevated"),
    ]
    clusters = cluster_points(points)
    assert len(clusters) == 1
    assert clusters[0]["cell_count"] == 3


# --------------------------------------------------------------------------
# Scene-freshness range per cluster (spec §12).
#
# Cells are merged by grid adjacency alone -- never by date -- and
# get_sentinel2_bands resolves each point's nearest cloud-free scene
# independently within +/-10 days, so one cluster genuinely can span
# several days of imagery. Measured spans among the 'ok' points of a
# single scan: 7 days (2025-12-15), 5 days (2026-03-15), 10 days
# (2026-06-15). These fields state the spread; they never hide it and
# never change which cells cluster together.
# --------------------------------------------------------------------------


def test_cluster_with_one_shared_scene_date_reports_span_zero():
    points = [
        _point("0_0", 0, 0, 1.6, "elevated", "2026-06-15"),
        _point("0_1", 0, 1, 1.7, "elevated", "2026-06-15"),
        _point("1_0", 1, 0, 1.8, "elevated", "2026-06-15"),
    ]
    clusters = cluster_points(points)
    assert len(clusters) == 1
    c = clusters[0]
    assert c["oldest_scene_date"] == "2026-06-15"
    assert c["newest_scene_date"] == "2026-06-15"
    # 0, not None -- "all members share one scene date" is a real,
    # positive statement, distinct from "the range is unknown".
    assert c["scene_date_span_days"] == 0


def test_cluster_spanning_scene_dates_reports_oldest_newest_and_span():
    # The measured 10-day worst case from the 2026-06-15 scan, inside a
    # single 8-connected cluster.
    points = [
        _point("0_0", 0, 0, 1.6, "elevated", "2026-06-14"),
        _point("0_1", 0, 1, 1.7, "elevated", "2026-06-05"),
        _point("1_1", 1, 1, 2.4, "warning", "2026-06-15"),
    ]
    clusters = cluster_points(points)
    assert len(clusters) == 1
    c = clusters[0]
    # Chronological min/max, not first/last in input order.
    assert c["oldest_scene_date"] == "2026-06-05"
    assert c["newest_scene_date"] == "2026-06-15"
    assert c["scene_date_span_days"] == 10
    assert isinstance(c["scene_date_span_days"], int)


def test_wide_span_cluster_is_still_reported_whole_never_split_or_dropped():
    """The hard rule: a mixed-vintage cluster is labelled, not suppressed.
    Splitting it by date would invent a spatial boundary no measurement
    supports."""
    points = [
        _point("0_0", 0, 0, 1.6, "elevated", "2026-06-05"),
        _point("0_1", 0, 1, 1.7, "elevated", "2026-06-15"),
    ]
    clusters = cluster_points(points)
    assert len(clusters) == 1, "a wide scene-date span must not split the cluster"
    assert clusters[0]["cell_count"] == 2
    assert set(clusters[0]["member_point_ids"]) == {"0_0", "0_1"}
    assert clusters[0]["scene_date_span_days"] == 10


def test_one_day_span_is_reported_as_one_not_rounded_away():
    points = [
        _point("0_0", 0, 0, 1.6, "elevated", "2026-03-14"),
        _point("0_1", 0, 1, 1.7, "elevated", "2026-03-15"),
    ]
    assert cluster_points(points)[0]["scene_date_span_days"] == 1


def test_span_crosses_a_month_boundary_correctly():
    points = [
        _point("0_0", 0, 0, 1.6, "elevated", "2026-05-30"),
        _point("0_1", 0, 1, 1.7, "elevated", "2026-06-03"),
    ]
    c = cluster_points(points)[0]
    assert c["oldest_scene_date"] == "2026-05-30"
    assert c["newest_scene_date"] == "2026-06-03"
    assert c["scene_date_span_days"] == 4


def test_single_member_cluster_reports_its_own_date_with_zero_span():
    clusters = cluster_points([_point("0_0", 0, 0, 1.6, "elevated", "2026-06-09")])
    assert len(clusters) == 1
    c = clusters[0]
    assert c["cell_count"] == 1
    assert c["oldest_scene_date"] == "2026-06-09"
    assert c["newest_scene_date"] == "2026-06-09"
    assert c["scene_date_span_days"] == 0


def test_single_member_cluster_with_no_scene_date_reports_all_three_null():
    clusters = cluster_points([_point("0_0", 0, 0, 1.6, "elevated", None)])
    c = clusters[0]
    assert c["cell_count"] == 1
    assert c["oldest_scene_date"] is None
    assert c["newest_scene_date"] is None
    assert c["scene_date_span_days"] is None


def test_any_null_member_scene_date_nulls_all_three_fields():
    """All-or-nothing: a range computed from only the dated members would
    understate the real spread while reading as if it covered the whole
    cluster."""
    points = [
        _point("0_0", 0, 0, 1.6, "elevated", "2026-06-05"),
        _point("0_1", 0, 1, 1.7, "elevated", "2026-06-15"),
        _point("1_0", 1, 0, 1.8, "elevated", None),
    ]
    clusters = cluster_points(points)
    assert len(clusters) == 1
    c = clusters[0]
    # Still one cluster of three cells -- the unknown range changes
    # nothing about membership.
    assert c["cell_count"] == 3
    assert c["oldest_scene_date"] is None
    assert c["newest_scene_date"] is None
    # Not 10 (the span of the two members that DO have dates), not 0.
    assert c["scene_date_span_days"] is None


def test_missing_actual_date_key_is_treated_as_unknown_not_as_same_day():
    """A member dict with no 'actual_date' key at all must behave exactly
    like an explicit None -- never as "shares everyone else's date"."""
    dated = _point("0_0", 0, 0, 1.6, "elevated", "2026-06-15")
    undated = _point("0_1", 0, 1, 1.7, "elevated")
    del undated["actual_date"]

    c = cluster_points([dated, undated])[0]
    assert c["oldest_scene_date"] is None
    assert c["newest_scene_date"] is None
    assert c["scene_date_span_days"] is None


def test_unparseable_member_scene_date_nulls_all_three_fields():
    points = [
        _point("0_0", 0, 0, 1.6, "elevated", "2026-06-15"),
        _point("0_1", 0, 1, 1.7, "elevated", "not-a-date"),
    ]
    c = cluster_points(points)[0]
    assert c["oldest_scene_date"] is None
    assert c["newest_scene_date"] is None
    assert c["scene_date_span_days"] is None


def test_separate_clusters_get_independent_scene_ranges():
    points = [
        # Cluster A: two cells, 6 days apart.
        _point("0_0", 0, 0, 1.6, "elevated", "2026-06-09"),
        _point("0_1", 0, 1, 1.7, "elevated", "2026-06-15"),
        # Cluster B, far away: one undated cell -> unknown range.
        _point("10_10", 10, 10, 2.2, "warning", None),
        # Cluster C, far away: two cells sharing one date.
        _point("20_20", 20, 20, 1.9, "elevated", "2026-06-12"),
        _point("20_21", 20, 21, 1.9, "elevated", "2026-06-12"),
    ]
    clusters = cluster_points(points)
    assert len(clusters) == 3
    by_first_member = {c["member_point_ids"][0]: c for c in clusters}

    a = next(c for c in clusters if "0_0" in c["member_point_ids"])
    assert (a["oldest_scene_date"], a["newest_scene_date"], a["scene_date_span_days"]) == (
        "2026-06-09", "2026-06-15", 6,
    )

    b = by_first_member["10_10"]
    assert (b["oldest_scene_date"], b["newest_scene_date"], b["scene_date_span_days"]) == (
        None, None, None,
    )

    c_cluster = next(c for c in clusters if "20_20" in c["member_point_ids"])
    assert c_cluster["scene_date_span_days"] == 0
    assert c_cluster["oldest_scene_date"] == "2026-06-12"


def test_every_cluster_carries_all_three_keys():
    """A consumer must never have to tell "range unknown" apart from
    "this build forgot the field"."""
    clusters = cluster_points([_point("0_0", 0, 0, 1.6, "elevated", "2026-06-15")])
    for key in ("oldest_scene_date", "newest_scene_date", "scene_date_span_days"):
        assert key in clusters[0]
