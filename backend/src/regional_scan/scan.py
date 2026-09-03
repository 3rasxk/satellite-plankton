"""
Regional scan orchestration (spec §2/§3/§4/§9): run_scan() generates the
grid (backend/src/regional_scan/grid.py), calls detect() unchanged
(detection/src/prediction.py, via backend/src/_detection.py) for every
point, tiers each 'ok' point against config.yaml's elevated_z/warning_z
cutoffs (the same cutoffs risk_level() uses -- no new numbers), clusters
the flagged points, and persists a latest-run snapshot.

GEEAuthError aborts the entire run (status='error') without touching
whatever RegionalScanPoint/RegionalScanCluster rows a prior successful
run already wrote -- it means the whole pipeline is unusable, not that
one point's reading is unavailable (see detect()'s own docstring;
mirrors scheduler.py's identical distinction for DetectionCache). Any
other per-point exception is caught individually (mirroring
scheduler.py's refresh_one_site) and stored as that point's 'error'
status, without killing the run.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import _detection as bridge
from ..db_models import RegionalScanCluster, RegionalScanPoint, RegionalScanRun
from .clustering import cluster_points
from .grid import generate_scan_grid

logger = logging.getLogger("backend.regional_scan.scan")


def _tier(anomaly_z: float, index_used: str, config: dict) -> str | None:
    """'warning' | 'elevated' | None, per config.yaml's thresholds --
    same cutoffs risk_level() reads, no new numbers (spec §3)."""
    index_thresholds = config["thresholds"][index_used]
    if anomaly_z >= index_thresholds["warning_z"]:
        return "warning"
    if anomaly_z >= index_thresholds["elevated_z"]:
        return "elevated"
    return None


def run_scan(
    db: Session,
    target_date: str,
    grid_spacing_km: float,
    newest_scene_date: str | None = None,
) -> RegionalScanRun:
    """Run one full regional scan and persist its results.

    Args:
        db: an open SQLAlchemy session (caller owns commit/close lifecycle
            for anything beyond this function's own commits).
        target_date: "YYYY-MM-DD" passed to detect() for every point.
        grid_spacing_km: grid spacing in km (backend/src/config.py
            REGIONAL_SCAN_GRID_SPACING_KM by default).
        newest_scene_date: the triggering poll's measured newest-scene
            timestamp, stored on the run row as the next poll's
            comparison baseline (spec §5/§6). None for a manually
            triggered run (backend/scripts/run_regional_scan.py) that
            didn't go through the poll.

    Returns:
        The persisted RegionalScanRun row (status='ok', 'partial_error',
        or 'error').
    """
    grid = generate_scan_grid(grid_spacing_km)
    run = RegionalScanRun(
        started_at=datetime.now(timezone.utc),
        status="running",
        grid_spacing_km=grid_spacing_km,
        date_used=target_date,
        newest_scene_date=newest_scene_date,
        total_points=len(grid),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    config = bridge.load_prediction_config()
    flagged_for_clustering: list[dict] = []
    counts = {"ok": 0, "no_imagery": 0, "no_water_pixels": 0, "no_climatology": 0, "error": 0}

    try:
        for point in grid:
            try:
                result = bridge.detect(point["lat"], point["lng"], target_date)
            except bridge.GEEAuthError:
                raise
            except Exception as exc:  # noqa: BLE001 -- per-point guard, mirrors scheduler.py
                logger.warning(
                    "regional_scan: point %s failed: %s: %s",
                    point["point_id"], type(exc).__name__, exc,
                )
                result = {
                    "status": "error", "detected": False, "anomaly_z": None,
                    "index_used": None, "index_values": None,
                    "reason": f"{type(exc).__name__}: {exc}",
                }

            status = result["status"]
            counts[status] = counts.get(status, 0) + 1

            tier = None
            if status == "ok" and result["anomaly_z"] is not None:
                tier = _tier(result["anomaly_z"], result["index_used"], config)

            existing = db.get(RegionalScanPoint, point["point_id"])
            fields = dict(
                lat=point["lat"], lng=point["lng"],
                row_idx=point["row_idx"], col_idx=point["col_idx"],
                status=status, index_values=result.get("index_values"),
                anomaly_z=result.get("anomaly_z"), threshold_tier=tier,
                run_id=run.id,
            )
            if existing is None:
                db.add(RegionalScanPoint(point_id=point["point_id"], **fields))
            else:
                for key, value in fields.items():
                    setattr(existing, key, value)

            if status == "ok" and tier is not None:
                flagged_for_clustering.append(
                    {
                        "point_id": point["point_id"], "lat": point["lat"], "lng": point["lng"],
                        "row_idx": point["row_idx"], "col_idx": point["col_idx"],
                        "anomaly_z": result["anomaly_z"], "threshold_tier": tier,
                    }
                )
    except bridge.GEEAuthError as exc:
        # Deliberately does NOT touch any RegionalScanPoint/RegionalScanCluster
        # row written by a prior successful run -- an aborted run must
        # never discard the last known-good snapshot (mirrors
        # scheduler.py's stale-marking, not deleting, on failure).
        #
        # db.rollback() first: discards this run's own pending, uncommitted
        # per-point db.add()/setattr() upserts from the loop above (points
        # processed before the failure point) -- without a rollback, the
        # commit() below would persist those as a partial, mixed-vintage
        # overwrite of prior-run data, even though this whole run is
        # untrustworthy. `run` itself was already committed earlier (the
        # db.add(run); db.commit(); db.refresh(run) at the top of this
        # function), so rolling back the *next* transaction doesn't undo
        # that -- but SQLAlchemy's rollback expires all session objects,
        # `run` included, so it's refreshed before its fields are set.
        db.rollback()
        db.refresh(run)
        run.status = "error"
        run.completed_at = datetime.now(timezone.utc)
        db.commit()
        logger.error("regional_scan: run %s aborted, GEEAuthError: %s", run.id, exc)
        return run

    # Grid points not touched this run (a spacing change from a prior
    # run) are stale -- drop them so /regional-scan never serves a point
    # from a grid resolution that's no longer in effect.
    current_point_ids = {p["point_id"] for p in grid}
    stale_points = db.execute(
        select(RegionalScanPoint).where(RegionalScanPoint.point_id.not_in(current_point_ids))
    ).scalars().all()
    for row in stale_points:
        db.delete(row)

    # Clusters are recomputed whole every run -- unlike points, cluster
    # membership has no stable identity across runs to upsert by.
    prior_clusters = db.execute(
        select(RegionalScanCluster).where(RegionalScanCluster.run_id != run.id)
    ).scalars().all()
    for row in prior_clusters:
        db.delete(row)
    clusters = cluster_points(flagged_for_clustering)
    for cluster in clusters:
        db.add(RegionalScanCluster(run_id=run.id, **cluster))

    run.completed_at = datetime.now(timezone.utc)
    run.count_ok = counts["ok"]
    run.count_no_imagery = counts["no_imagery"]
    run.count_no_water_pixels = counts["no_water_pixels"]
    run.count_no_climatology = counts["no_climatology"]
    run.count_error = counts["error"]
    run.status = "partial_error" if counts["error"] > 0 else "ok"
    db.commit()
    logger.info(
        "regional_scan: run %s done -- status=%s ok=%d no_imagery=%d no_water_pixels=%d "
        "no_climatology=%d error=%d clusters=%d",
        run.id, run.status, counts["ok"], counts["no_imagery"], counts["no_water_pixels"],
        counts["no_climatology"], counts["error"], len(clusters),
    )
    return run
