"""
Regional scan orchestration (spec §2/§3/§4/§9): run_scan() generates the
grid (backend/src/regional_scan/grid.py), calls detect()
(detection/src/prediction.py, via backend/src/_detection.py) for every
point, and persists real spectral indices and scene dates. No valid
anomaly baseline exists yet, so every score/tier is null and no point
can be sent to clustering.

Only one scan may run at a time. Two concurrent runs upsert the same
`RegionalScanPoint` rows by `point_id`, so the table would end up a
last-writer-wins mixture of two runs while `/regional-scan` reported it
under one run's metadata, and each run's end-of-scan cleanup deletes the
other's clusters. The scheduler's own cooldown (20 h) already made this
impossible on its path, but `scripts/run_regional_scan.py` bypasses the
cooldown entirely -- so the guard lives here, where both paths pass.

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
from ..config import REGIONAL_SCAN_STALE_RUN_HOURS, as_aware_utc
from ..db_models import RegionalScanCluster, RegionalScanPoint, RegionalScanRun
from .clustering import cluster_points
from .grid import generate_scan_grid

logger = logging.getLogger("backend.regional_scan.scan")


class ConcurrentScanError(RuntimeError):
    """Another scan is already in progress, so this one refused to start.

    Not a failure of the running scan and not a data error -- the caller
    should wait for the live run rather than retry. Raised before any row
    is written, so a refused call leaves the database untouched.
    """


def _refuse_if_a_scan_is_already_running(db: Session, now: datetime) -> None:
    """Guard against concurrent runs; expire a run that is stuck.

    A run still marked 'running' after REGIONAL_SCAN_STALE_RUN_HOURS is
    presumed dead (its process was killed, or the host restarted mid-scan)
    and is marked 'error' so it stops blocking every future scan and stops
    being served as an in-progress run. Anything younger than that is
    treated as genuinely live and this raises.
    """
    active = db.execute(
        select(RegionalScanRun)
        .where(RegionalScanRun.status == "running")
        .order_by(RegionalScanRun.started_at.desc())
    ).scalars().first()
    if active is None:
        return

    age_hours = (now - as_aware_utc(active.started_at)).total_seconds() / 3600
    if age_hours < REGIONAL_SCAN_STALE_RUN_HOURS:
        raise ConcurrentScanError(
            f"regional scan {active.id} has been running for {age_hours:.1f}h "
            f"({active.total_points} points, started {active.started_at}). "
            "Two scans would overwrite each other's points and clusters. "
            "Wait for it to finish, or pass allow_concurrent=True "
            "(scripts/run_regional_scan.py --force) if you are certain it is dead."
        )

    logger.warning(
        "regional_scan: run %s still 'running' after %.1fh (> %dh) -- presuming it "
        "died and marking it error so this scan can proceed",
        active.id, age_hours, REGIONAL_SCAN_STALE_RUN_HOURS,
    )
    active.status = "error"
    active.completed_at = now
    db.commit()


def run_scan(
    db: Session,
    target_date: str,
    grid_spacing_km: float,
    newest_scene_date: str | None = None,
    allow_concurrent: bool = False,
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
        allow_concurrent: skip the one-scan-at-a-time guard. Only for a
            caller that knows the other run is dead -- concurrent runs
            corrupt each other's points (see the module docstring).

    Returns:
        The persisted RegionalScanRun row (status='ok', 'partial_error',
        or 'error').

    Raises:
        ConcurrentScanError: another scan is already running and
            `allow_concurrent` is False. Nothing is written.
    """
    now = datetime.now(timezone.utc)
    if not allow_concurrent:
        _refuse_if_a_scan_is_already_running(db, now)

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

    counts = {"ok": 0, "no_imagery": 0, "no_water_pixels": 0, "no_climatology": 0, "error": 0}
    logger.info(
        "regional_scan: run %s started -- target=%s spacing_km=%s total_points=%d",
        run.id, target_date, grid_spacing_km, len(grid),
    )

    try:
        for processed, point in enumerate(grid, start=1):
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
                    "status": "error",
                    "index_used": None, "index_values": None,
                    "reason": f"{type(exc).__name__}: {exc}",
                }

            status = result["status"]
            counts[status] = counts.get(status, 0) + 1

            existing = db.get(RegionalScanPoint, point["point_id"])
            fields = dict(
                lat=point["lat"], lng=point["lng"],
                row_idx=point["row_idx"], col_idx=point["col_idx"],
                status=status, index_values=result.get("index_values"),
                spatial_anomaly_z=None, threshold_tier=None,
                # Per-point scene date from detect(), not the run's target
                # date -- .get() because the per-point error dict built
                # above carries no scene at all (stays null).
                actual_date=result.get("actual_date"),
                run_id=run.id,
            )
            if existing is None:
                db.add(RegionalScanPoint(point_id=point["point_id"], **fields))
            else:
                for key, value in fields.items():
                    setattr(existing, key, value)

            if processed % 100 == 0 or processed == len(grid):
                logger.info(
                    "regional_scan: run %s processed=%d/%d counts=%s",
                    run.id, processed, len(grid), counts,
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
    clusters = cluster_points([])
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
