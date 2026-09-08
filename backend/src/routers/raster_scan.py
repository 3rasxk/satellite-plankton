"""
`/raster-scan` -- the whole-polygon raster overlay and its metadata.

Serves what `src/raster_scan/` already produced: cached PNG assets on
disk and the run row describing them. Nothing here calls Earth Engine,
renders, or computes an index; a request that arrives before any scan
has run gets an explicit "no raster yet", never a placeholder picture.

Three endpoints, deliberately split:
  - `GET /raster-scan` returns metadata only (bounds, legend, scene
    dates, coverage). Small, JSON, safe to poll.
  - `GET /raster-scan/overlay.png` returns the image bytes. Megabytes,
    cacheable, and fetched by the browser as an ordinary image rather
    than pulled through the JSON payload as base64.
  - `GET /raster-scan/pixel?lat=&lng=` reads one cell out of the stored
    blob the overlay was drawn from. Also not a live call: a click asks
    what was already measured, and the answer must be the number behind
    the pixel on screen, identical every time it is asked.

Metadata binds the image URL and pixel queries to its run_id. Explicit
run IDs never fall back to a newer render; callers omitting the ID retain
the legacy newest-render behavior. Serving a click from a newer run than
the picture would silently report readings from a different image.

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

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import as_aware_utc
from ..db import get_db
from ..db_models import RasterScanRun
from ..raster_scan import pixel as pixel_lookup
from ..schemas import RasterCoverage, RasterPixelResponse, RasterScanResponse

router = APIRouter(tags=["raster-scan"])

OVERLAY_BAND = "ndci"


def _coverage(overlay: dict) -> RasterCoverage | None:
    """Coverage, straight from the stats the renderer recorded.

    Every number is the one `render.render_overlay` recorded when it drew
    the picture. Nothing is recomputed here and nothing is reconstructed:
    an overlay rendered before `measured_pixels` was recorded keeps its
    real fraction and reports a null count, rather than having a count
    invented by multiplying a rounded fraction back out against the
    total. An overlay with no coverage stats at all reports no coverage.
    """
    asset = (overlay.get("assets") or {}).get(OVERLAY_BAND) or {}
    fraction = asset.get("measured_fraction")
    total = asset.get("inside_polygon_pixels")
    if fraction is None or total is None:
        return None
    measured = asset.get("measured_pixels")
    return RasterCoverage(
        measured_fraction=float(fraction),
        measured_pixels=None if measured is None else int(measured),
        polygon_pixels=int(total),
    )


def _rendered_run(db: Session, run_id: int | None = None) -> RasterScanRun | None:
    """The requested render, or the newest usable one when no ID is given.

    Not simply the newest run: a later attempt can be running, failed,
    or have had its blob expired by retention, and none of those should
    hide the last picture that still exists. Mirrors the regional scan's
    "serve the newest usable snapshot" rule.

    An explicit ID is restricted to its own row even when that render
    has expired. A missing image must never be replaced by another run.
    """
    query = select(RasterScanRun)
    if run_id is None:
        query = query.order_by(RasterScanRun.started_at.desc()).limit(25)
    else:
        query = query.where(RasterScanRun.id == run_id)
    runs = db.execute(query).scalars().all()
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
    rendered = _rendered_run(db)

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
        # The span above says when; this says how much came from when.
        # Recorded at scan time from the stored date band, never derived
        # here from the span (which could not carry it).
        scene_dates=rendered.scene_dates,
        completed_at=(
            as_aware_utc(rendered.completed_at).isoformat() if rendered.completed_at else None
        ),
        coverage=_coverage(overlay),
        bounds=(overlay.get("bounds") or {}).get("leaflet_bounds"),
        legend=overlay.get("legend"),
        overlay_url=f"/raster-scan/overlay.png?run_id={rendered.id}",
        stale_run_id=latest.id if latest and latest.id != rendered.id else None,
    )


@router.get("/raster-scan/overlay.png")
async def get_raster_overlay(
    run_id: int | None = Query(None, ge=1, le=2**63 - 1,
                               description="Exact rendered run; omit for the latest available."),
    db: Session = Depends(get_db),
) -> FileResponse:
    """The overlay image itself, straight off disk.

    404 rather than a blank or placeholder image when nothing has been
    rendered: an empty overlay drawn over the study area would say "we
    looked and saw nothing", which is exactly the claim this project
    refuses to make by accident.
    """
    rendered = _rendered_run(db, run_id)
    if rendered is None:
        raise HTTPException(
            status_code=404,
            detail="No rendered raster overlay is available. Run a raster scan first.",
        )
    path = Path(rendered.overlay["assets"][OVERLAY_BAND]["path"])
    return FileResponse(path, media_type="image/png", filename=path.name)


@router.get("/raster-scan/pixel", response_model=RasterPixelResponse)
async def get_raster_pixel(
    lat: float = Query(..., ge=-90, le=90, description="Latitude of the clicked point."),
    lng: float = Query(..., ge=-180, le=180, description="Longitude of the clicked point."),
    run_id: int | None = Query(None, ge=1, le=2**63 - 1,
                               description="Exact rendered run; omit for the latest available."),
    db: Session = Depends(get_db),
) -> RasterPixelResponse:
    """The stored cell under one coordinate of the served overlay.

    Reads the blob, not Earth Engine. Everything about the answer -- the
    four index values, the cell's own acquisition date, its own
    coordinate -- comes out of the file the picture was drawn from, so
    clicking the same pixel twice cannot produce two different readings,
    and a reading can never appear for a pixel the map draws as
    unmeasured.

    A coordinate with no cell is answered, not refused: `state` says
    whether that is unmeasured water inside the study area or somewhere
    outside it entirely. Those are different facts and a viewer can see
    the difference on the map, so the API keeps it too.

    404 when there is no raster to query at all, and when the run whose
    overlay is on screen has lost its cells -- the picture can still be
    shown, but no number behind it can honestly be quoted.
    """
    rendered = _rendered_run(db, run_id)
    if rendered is None:
        raise HTTPException(
            status_code=404,
            detail="No raster overlay is available to query. Run a raster scan first.",
        )
    try:
        found = pixel_lookup.inspect_run(rendered, lat, lng)
    except pixel_lookup.RasterCellsUnavailableError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return RasterPixelResponse(
        run_id=rendered.id,
        date_used=rendered.date_used,
        scale_m=rendered.scale_m,
        **found,
    )
