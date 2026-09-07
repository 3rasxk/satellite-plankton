"""
`/raster-scan` -- the whole-polygon raster overlay and its metadata.

Serves what `src/raster_scan/` already produced: cached PNG assets on
disk and the run row describing them. Nothing here calls Earth Engine,
renders, or computes an index; a request that arrives before any scan
has run gets an explicit "no raster yet", never a placeholder picture.

Two endpoints, deliberately split:
  - `GET /raster-scan` returns metadata only (bounds, legend, scene
    dates, coverage). Small, JSON, safe to poll.
  - `GET /raster-scan/overlay.png` returns the image bytes. Megabytes,
    cacheable, and fetched by the browser as an ordinary image rather
    than pulled through the JSON payload as base64.

The legend travels with the metadata rather than being written into the
frontend, so the swatches a reader sees are the same bytes the renderer
painted with (see render.legend_swatches). A legend that re-derives the
ramp is a second implementation, and one that drifts is a quiet lie
about what a colour means.

Truth boundary, unchanged from every other endpoint here: the raster
carries index readings with their own per-pixel acquisition dates. No
anomaly statistic, no risk level, no classification -- no valid
spectral-index baseline exists (CLAUDE.md §0/§1).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import as_aware_utc
from ..db import get_db
from ..db_models import RasterScanRun
from ..schemas import RasterScanResponse

router = APIRouter(tags=["raster-scan"])

OVERLAY_BAND = "ndci"


def _latest_rendered_run(db: Session) -> RasterScanRun | None:
    """The newest run that actually has an overlay on disk.

    Not simply the newest run: a later attempt can be running, failed,
    or have had its blob expired by retention, and none of those should
    hide the last picture that still exists. Mirrors the regional scan's
    "serve the newest usable snapshot" rule.
    """
    runs = db.execute(
        select(RasterScanRun).order_by(RasterScanRun.started_at.desc()).limit(25)
    ).scalars().all()
    for run in runs:
        overlay = run.overlay
        if not isinstance(overlay, dict) or overlay.get("status") != "ok":
            continue
        asset = (overlay.get("assets") or {}).get(OVERLAY_BAND)
        if asset and Path(asset["path"]).exists():
            return run
    return None


@router.get("/raster-scan", response_model=RasterScanResponse)
async def get_raster_scan(db: Session = Depends(get_db)) -> RasterScanResponse:
    """Metadata for the newest raster overlay that still exists on disk."""
    latest = db.execute(
        select(RasterScanRun).order_by(RasterScanRun.started_at.desc())
    ).scalars().first()
    rendered = _latest_rendered_run(db)

    if rendered is None:
        return RasterScanResponse(
            run_id=None,
            status=latest.status if latest else None,
            date_used=latest.date_used if latest else None,
            reason=(
                "No raster overlay has been rendered yet."
                if latest is None
                else "The most recent runs have no overlay on disk "
                "(never rendered, failed to render, or expired by retention)."
            ),
        )

    overlay = rendered.overlay
    return RasterScanResponse(
        run_id=rendered.id,
        status=rendered.status,
        date_used=rendered.date_used,
        scale_m=rendered.scale_m,
        cell_count=rendered.cell_count,
        scene_count=rendered.scene_count,
        oldest_scene_date=rendered.oldest_scene_date,
        newest_scene_date=rendered.newest_scene_date,
        completed_at=(
            as_aware_utc(rendered.completed_at).isoformat() if rendered.completed_at else None
        ),
        bounds=(overlay.get("bounds") or {}).get("leaflet_bounds"),
        legend=overlay.get("legend"),
        overlay_url="/raster-scan/overlay.png",
        stale_run_id=latest.id if latest and latest.id != rendered.id else None,
    )


@router.get("/raster-scan/overlay.png")
async def get_raster_overlay(db: Session = Depends(get_db)) -> FileResponse:
    """The overlay image itself, straight off disk.

    404 rather than a blank or placeholder image when nothing has been
    rendered: an empty overlay drawn over the study area would say "we
    looked and saw nothing", which is exactly the claim this project
    refuses to make by accident.
    """
    rendered = _latest_rendered_run(db)
    if rendered is None:
        raise HTTPException(
            status_code=404,
            detail="No rendered raster overlay is available. Run a raster scan first.",
        )
    path = Path(rendered.overlay["assets"][OVERLAY_BAND]["path"])
    return FileResponse(path, media_type="image/png", filename=path.name)
