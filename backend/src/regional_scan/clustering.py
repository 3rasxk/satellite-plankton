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

Scene freshness: adjacency is the ONLY thing that merges cells here, and
a cluster's members are not required to come from the same Sentinel-2
scene -- they routinely do not. get_sentinel2_bands resolves the nearest
cloud-free scene within +/-10 days of the scan's target date
independently per point, and measured scene-date spans among the 'ok'
points of a single scan were 7 days (2025-12-15), 5 days (2026-03-15)
and 10 days (2026-06-15). So each cluster reports its own freshness
range (`oldest_scene_date` / `newest_scene_date` /
`scene_date_span_days`), which spec §12 named as the precondition for
showing mixed-vintage cells under one undifferentiated pin at all.
A wide span is never a reason to hide, split or filter a cluster --
splitting one would invent a spatial boundary no measurement supports.
The range is labelled and the reader judges it.
"""

from __future__ import annotations

import logging
from datetime import date

logger = logging.getLogger("backend.regional_scan.clustering")

_TIER_RANK = {"elevated": 0, "warning": 1}


def _scene_date_range(
    members: list[dict],
) -> tuple[str | None, str | None, int | None]:
    """(oldest, newest, span_days) over one cluster's member scene dates.

    Returns (None, None, None) if ANY member's `actual_date` is missing,
    null, or unparseable -- all-or-nothing on purpose. A range computed
    from only the members that happen to carry a date would understate
    the cluster's real spread while reading as though it covered the
    whole cluster, and the run's `date_used` is a requested target date,
    not a scene date, so it cannot stand in either. There is no honest
    partial answer, so callers are told the range is unknown instead.
    """
    parsed: list[date] = []
    for member in members:
        raw = member.get("actual_date")
        if not raw:
            return None, None, None
        try:
            parsed.append(date.fromisoformat(str(raw)))
        except ValueError:
            # Upstream contract is strictly "YYYY-MM-DD" (detect() ->
            # get_sentinel2_bands). Anything else means we cannot state
            # this cluster's range, so we say so rather than guess --
            # loudly, because it also means something upstream is wrong.
            logger.warning(
                "regional_scan.clustering: unparseable actual_date %r on point %s "
                "-- reporting this cluster's scene range as unknown",
                raw, member.get("point_id"),
            )
            return None, None, None

    oldest, newest = min(parsed), max(parsed)
    return oldest.isoformat(), newest.isoformat(), (newest - oldest).days


def cluster_points(points: list[dict]) -> list[dict]:
    """Cluster already-flagged points by 8-connected grid adjacency.

    Args:
        points: list of {'point_id', 'lat', 'lng', 'row_idx', 'col_idx',
                          'anomaly_z', 'threshold_tier', 'actual_date'}.
                Every member is already real/'ok' -- callers only ever
                pass flagged (status='ok', tiered) points, so this
                function's output satisfies spec §4's "computed only over
                real, status='ok' member cells" invariant by
                construction, not by filtering here. 'actual_date' is
                that point's own Sentinel-2 scene date ("YYYY-MM-DD") or
                None; it is read with .get(), so a caller that omits the
                key gets the same treatment as an explicit None.

    Returns:
        list of {'centroid_lat', 'centroid_lng', 'cell_count',
                  'mean_anomaly_z', 'max_anomaly_z', 'threshold_tier',
                  'member_point_ids', 'oldest_scene_date',
                  'newest_scene_date', 'scene_date_span_days'}, one per
        connected component. Empty list if `points` is empty.

        The last three describe the cluster's scene-freshness range, not
        its geometry: `oldest_scene_date`/`newest_scene_date` are the
        min/max of its members' own scene dates and
        `scene_date_span_days` is their difference in whole days -- 0
        when every member shares one scene date. All three are None
        together, and only together, when any member's scene date is
        missing or unparseable (see _scene_date_range). Membership is
        decided purely by adjacency and is never split, filtered or
        suppressed on the strength of this range; it is reported so the
        reader can judge it.
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
        oldest_scene_date, newest_scene_date, scene_date_span_days = _scene_date_range(members)
        clusters.append(
            {
                "centroid_lat": sum(lats) / len(lats),
                "centroid_lng": sum(lngs) / len(lngs),
                "cell_count": len(members),
                "mean_anomaly_z": sum(z_values) / len(z_values),
                "max_anomaly_z": max(z_values),
                "threshold_tier": highest_tier,
                "member_point_ids": [m["point_id"] for m in members],
                "oldest_scene_date": oldest_scene_date,
                "newest_scene_date": newest_scene_date,
                "scene_date_span_days": scene_date_span_days,
            }
        )
    return clusters
