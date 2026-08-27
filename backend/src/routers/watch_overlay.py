"""GET /watch-overlay -- serve the scheduler-cached NDCI watch overlay.

This router only reads ``WatchOverlayCache``. It intentionally does not
import the detection bridge, scheduler, Earth Engine, or data pipeline, so a
request remains available before the first scheduler run and never triggers
Google Earth Engine work.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..config import as_aware_utc
from ..db import get_db
from ..db_models import WatchOverlayCache
from ..schemas import WATCH_OVERLAY_CAVEAT, WatchOverlayResponse

router = APIRouter()


@router.get("/watch-overlay", response_model=WatchOverlayResponse, tags=["watch-overlay"])
def get_watch_overlay(db: Session = Depends(get_db)) -> WatchOverlayResponse:
    """Return the singleton cache row, or an explicit pre-initialization state."""
    row = db.get(WatchOverlayCache, 1)
    if row is None:
        return WatchOverlayResponse(
            status="error",
            stale=True,
            error="Watch overlay cache is not initialized; the scheduler has not completed a run.",
            caveat=WATCH_OVERLAY_CAVEAT,
        )

    return WatchOverlayResponse(
        status=row.status,
        tile_url=row.tile_url,
        generated_at=as_aware_utc(row.generated_at).isoformat() if row.generated_at else None,
        target_date=row.target_date,
        source_window_start=row.source_window_start,
        source_window_end=row.source_window_end,
        newest_scene_date=row.newest_scene_date,
        baseline_periods=row.baseline_periods,
        threshold_z=row.threshold_z,
        baseline_years=row.baseline_years,
        seasonal_window_days=row.seasonal_window_days,
        min_baseline_observations=row.min_baseline_observations,
        water_occurrence_pct=row.water_occurrence_pct,
        water_mask=row.water_mask,
        output_grid_m=row.output_grid_m,
        effective_resolution_m=row.effective_resolution_m,
        color=row.color,
        analysis_metadata=row.analysis_metadata,
        stale=row.stale,
        error=row.error,
        caveat=WATCH_OVERLAY_CAVEAT,
    )
