"""Unit tests for grid-adjacency connected-components clustering (spec
§4) -- pure, no GEE, no DB."""

from __future__ import annotations

from src.regional_scan.clustering import cluster_points


def _point(point_id, row, col, z, tier):
    return {
        "point_id": point_id, "lat": 13.0 + row * 0.01, "lng": 100.0 + col * 0.01,
        "row_idx": row, "col_idx": col, "anomaly_z": z, "threshold_tier": tier,
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
