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

from .. import _detection as bridge
from ..config import REGIONAL_SCAN_GRID_SPACING_KM, as_aware_utc
from ..db import get_db
from ..db_models import RegionalScanCluster, RegionalScanPoint, RegionalScanRun
from ..regional_scan.grid import generate_scan_grid
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

    points = db.execute(select(RegionalScanPoint)).scalars().all()
    # An aborted/running attempt can leave an older, differently spaced
    # snapshot on screen. Describe the coordinates actually being served.
    grid_run = db.get(RegionalScanRun, points[0].run_id) if points else latest_run
    grid_spacing_km = (
        grid_run.grid_spacing_km if grid_run else REGIONAL_SCAN_GRID_SPACING_KM
    )
    # Planned sampling coordinates are real geometry, not satellite readings.
    # Make the whole grid visible even before the first scan commits. Never
    # store these placeholders or invent an index, scene date, or scan run.
    planned_points = [] if points else [
        RegionalScanPointSchema(
            point_id=point["point_id"], lat=point["lat"], lng=point["lng"],
            status="no_data_yet",
        )
        for point in generate_scan_grid(grid_spacing_km)
    ]
    if latest_run is None:
        return RegionalScanResponse(
            run=None, points=planned_points, clusters=[], grid_spacing_km=grid_spacing_km,
            max_scene_age_days=bridge.default_max_scene_age_days(),
        )
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
        grid_spacing_km=grid_spacing_km,
        max_scene_age_days=bridge.default_max_scene_age_days(),
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
                index_values=p.index_values, spatial_anomaly_z=p.spatial_anomaly_z,
                threshold_tier=p.threshold_tier, actual_date=p.actual_date,
            )
            for p in points
        ] or planned_points,
        clusters=[
            RegionalScanClusterSchema(
                centroid_lat=c.centroid_lat, centroid_lng=c.centroid_lng,
                cell_count=c.cell_count, mean_spatial_anomaly_z=c.mean_spatial_anomaly_z,
                max_spatial_anomaly_z=c.max_spatial_anomaly_z, threshold_tier=c.threshold_tier,
                member_point_ids=c.member_point_ids,
                oldest_scene_date=c.oldest_scene_date,
                newest_scene_date=c.newest_scene_date,
                scene_date_span_days=c.scene_date_span_days,
            )
            for c in clusters
        ],
    )
