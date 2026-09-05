"""GET /regional-scan -- pure cache read of the latest full-polygon
regional bloom scan (docs/superpowers/specs/2026-08-31-regional-scan-design.md).
Never calls GEE live, same convention as /risk-map and /summary -- the
scan itself runs on the poll/cooldown scheduler job
(backend/src/regional_scan/trigger.py) or the manual CLI script
(backend/scripts/run_regional_scan.py), never inside a request."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import as_aware_utc
from ..db import get_db
from ..db_models import RegionalScanCluster, RegionalScanPoint, RegionalScanRun
from ..schemas import (
    RegionalScanClusterSchema,
    RegionalScanPointSchema,
    RegionalScanResponse,
    RegionalScanRunMeta,
)

router = APIRouter()


@router.get("/regional-scan", response_model=RegionalScanResponse, tags=["regional-scan"])
async def get_regional_scan(db: Session = Depends(get_db)) -> RegionalScanResponse:
    latest_run = db.execute(
        select(RegionalScanRun).order_by(RegionalScanRun.started_at.desc())
    ).scalars().first()

    if latest_run is None:
        return RegionalScanResponse(run=None, points=[], clusters=[])

    points = db.execute(select(RegionalScanPoint)).scalars().all()
    # No run_id filter here either -- RegionalScanCluster is documented in
    # db_models.py as a whole-table latest-snapshot, same category as
    # RegionalScanPoint above ("deleted and reinserted whole each run"),
    # not a per-run history table. On a successful run, scan.py deletes
    # every prior-run cluster row and reinserts the new ones under the new
    # run.id, so at any given moment every cluster row already belongs to
    # one and the same run -- whichever run last completed successfully.
    # But on a GEEAuthError abort, scan.py rolls back and returns *before*
    # reaching that delete-and-reinsert code, so cluster rows are left
    # completely untouched by the aborted run. If the latest RegionalScanRun
    # is that aborted one, filtering by run_id == latest_run.id would match
    # zero rows (no cluster ever carries an aborted run's id) and wrongly
    # report clusters: [] even though the real, still-current cluster
    # snapshot exists in the table. Querying unfiltered -- exactly like
    # points -- always returns that current snapshot regardless of whether
    # the latest run row succeeded or aborted.
    clusters = db.execute(select(RegionalScanCluster)).scalars().all()

    return RegionalScanResponse(
        run=RegionalScanRunMeta(
            run_id=latest_run.id,
            started_at=as_aware_utc(latest_run.started_at).isoformat(),
            completed_at=(
                as_aware_utc(latest_run.completed_at).isoformat()
                if latest_run.completed_at else None
            ),
            status=latest_run.status,
            grid_spacing_km=latest_run.grid_spacing_km,
            date_used=latest_run.date_used,
            newest_scene_date=latest_run.newest_scene_date,
            total_points=latest_run.total_points,
            count_ok=latest_run.count_ok,
            count_no_imagery=latest_run.count_no_imagery,
            count_no_water_pixels=latest_run.count_no_water_pixels,
            count_no_climatology=latest_run.count_no_climatology,
            count_error=latest_run.count_error,
        ),
        points=[
            RegionalScanPointSchema(
                point_id=p.point_id, lat=p.lat, lng=p.lng, status=p.status,
                index_values=p.index_values, anomaly_z=p.anomaly_z,
                threshold_tier=p.threshold_tier, actual_date=p.actual_date,
            )
            for p in points
        ],
        clusters=[
            RegionalScanClusterSchema(
                centroid_lat=c.centroid_lat, centroid_lng=c.centroid_lng,
                cell_count=c.cell_count, mean_anomaly_z=c.mean_anomaly_z,
                max_anomaly_z=c.max_anomaly_z, threshold_tier=c.threshold_tier,
                member_point_ids=c.member_point_ids,
                oldest_scene_date=c.oldest_scene_date,
                newest_scene_date=c.newest_scene_date,
                scene_date_span_days=c.scene_date_span_days,
            )
            for c in clusters
        ],
    )
