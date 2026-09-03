"""
Grid-adjacency connected-components clustering for flagged regional-scan
points -- union-find over (row_idx, col_idx), 8-connectivity (differ by
<=1 in both row and col). O(n), deterministic, no tunable parameter.
DBSCAN was considered and rejected: its eps/min_samples would be an
unvalidated parameter with no real spatial ground-truth to tune against,
and it would add scikit-learn as a new backend dependency (currently
pulled in only by the orphaned, unwired ensemble_service.py files
flagged in CLAUDE.md §9) -- see
docs/superpowers/specs/2026-08-31-regional-scan-design.md §4.
"""

from __future__ import annotations

_TIER_RANK = {"elevated": 0, "warning": 1}


def cluster_points(points: list[dict]) -> list[dict]:
    """Cluster already-flagged points by 8-connected grid adjacency.

    Args:
        points: list of {'point_id', 'lat', 'lng', 'row_idx', 'col_idx',
                          'anomaly_z', 'threshold_tier'}. Every member is
                already real/'ok' -- callers only ever pass flagged
                (status='ok', tiered) points, so this function's output
                satisfies spec §4's "computed only over real, status='ok'
                member cells" invariant by construction, not by filtering
                here.

    Returns:
        list of {'centroid_lat', 'centroid_lng', 'cell_count',
                  'mean_anomaly_z', 'max_anomaly_z', 'threshold_tier',
                  'member_point_ids'}, one per connected component.
        Empty list if `points` is empty.
    """
    by_coord = {(p["row_idx"], p["col_idx"]): p for p in points}
    parent: dict[tuple[int, int], tuple[int, int]] = {coord: coord for coord in by_coord}

    def find(coord):
        while parent[coord] != coord:
            parent[coord] = parent[parent[coord]]
            coord = parent[coord]
        return coord

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for row, col in by_coord:
        for d_row in (-1, 0, 1):
            for d_col in (-1, 0, 1):
                if d_row == 0 and d_col == 0:
                    continue
                neighbor = (row + d_row, col + d_col)
                if neighbor in by_coord:
                    union((row, col), neighbor)

    groups: dict[tuple[int, int], list[dict]] = {}
    for coord, point in by_coord.items():
        groups.setdefault(find(coord), []).append(point)

    clusters = []
    for members in groups.values():
        lats = [m["lat"] for m in members]
        lngs = [m["lng"] for m in members]
        z_values = [m["anomaly_z"] for m in members]
        highest_tier = max(members, key=lambda m: _TIER_RANK[m["threshold_tier"]])["threshold_tier"]
        clusters.append(
            {
                "centroid_lat": sum(lats) / len(lats),
                "centroid_lng": sum(lngs) / len(lngs),
                "cell_count": len(members),
                "mean_anomaly_z": sum(z_values) / len(z_values),
                "max_anomaly_z": max(z_values),
                "threshold_tier": highest_tier,
                "member_point_ids": [m["point_id"] for m in members],
            }
        )
    return clusters
