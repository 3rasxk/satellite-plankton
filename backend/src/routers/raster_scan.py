"""
`/raster-scan` -- the whole-polygon raster overlay and its metadata.

Serves what `src/raster_scan/` already produced: cached PNG assets on
disk and the run row describing them. Nothing here calls Earth Engine,
renders, or computes an index; a request that arrives before any scan
has run gets an explicit "no raster yet", never a placeholder picture.

Four endpoints, deliberately split:
  - `GET /raster-scan` returns metadata only (bounds, legend, scene
    dates, coverage). Small, JSON, safe to poll.
  - `GET /raster-scan/overlay.png` returns the image bytes. Megabytes,
    cacheable, and fetched by the browser as an ordinary image rather
    than pulled through the JSON payload as base64.
  - `GET /raster-scan/pixel?lat=&lng=` reads one cell out of the stored
    blob the overlay was drawn from. Also not a live call: a click asks
    what was already measured, and the answer must be the number behind
    the pixel on screen, identical every time it is asked.
  - `GET /raster-scan/highlights` ranks the same stored cells by NDCI
    (src/raster_scan/highlights.py): the top-N measured cells of one run
    after spatial de-duplication. A ranking by value inside one scan --
    no threshold, no baseline, no tier. With BASELINE_MODE=test and a
    usable Level B cell baseline it can instead (`mode=anomaly`, then the
    default) pin cells whose NDCI is >= 2 robust z above the cell's OWN
    TEST seasonal baseline (src/raster_scan/cell_anomaly.py) -- a
    separately labelled statistical anomaly, never a risk level.

Metadata binds the image URL and pixel queries to its run_id. Explicit
run IDs never fall back to a newer render; callers omitting the ID retain
the legacy newest-render behavior. Serving a click from a newer run than
the picture would silently report readings from a different image.

The legend travels with the metadata rather than being written into the
frontend, so the swatches a reader sees are the same bytes the renderer
painted with (see render.legend_swatches). A legend that re-derives the
ramp is a second implementation, and one that drifts is a quiet lie
about what a colour means.

`GET /raster-scan` also carries the latest-scene policy's state
(`latest_scene`, `last_used_scene_date`, `poll`), read from the
`scene_assessments` and `scene_poll_status` tables the hourly poll writes
(src/raster_scan/trigger.py). They answer "which acquisition is the newest
one we know of, did it reach this picture, and can the poll currently see
new scenes at all". They are metadata about scene selection, served
whatever BASELINE_MODE is, and a stale or failing poll is reported as such
-- never as "no newer scene".

Truth boundary: the raster carries index readings with their own
per-pixel acquisition dates. No risk level and no classification
anywhere. With the mode off (the default) there is no anomaly statistic
either -- no valid spectral-index baseline exists (CLAUDE.md §0/§1). In
TEST baseline mode the anomaly fields (highlights `mode=anomaly`, the
pixel `anomaly` block) are a provisional, uncalibrated comparison of a
cell with its own record, never called a risk. While a TEST baseline is
valid every response here carries the TEST-baseline disclaimer, with or
without an anomaly in it (the standard text says no anomaly is computed,
which is false then); otherwise every response carries the standard text.

Blocking work: every handler that reads a blob or a baseline file is a
plain `def` (run in the threadpool), and each request resolves the
baseline ONCE (`baseline_status()` + one season file, same version). The
one exception is `GET /raster-scan` (async), whose disclaimer comes from
DisclaimerMixin's default: one stat-cached `baseline_status()` on the
event loop in test mode (no file touched with the mode off).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import _detection as bridge
from .. import scientific_status
from ..config import as_aware_utc
from ..db import get_db
from ..db_models import RasterScanRun, SceneAssessmentRow, ScenePollStatus
from ..raster_scan import cell_anomaly
from ..raster_scan import highlights as highlight_ranking
from ..raster_scan import pixel as pixel_lookup
from ..raster_scan.trigger import POLL_STATUS_ID, PASSED, is_settled
from ..schemas import (
    LatestSceneInfo,
    RasterAnomalyHighlightsResponse,
    RasterCoverage,
    RasterHighlightsResponse,
    RasterPixelResponse,
    RasterScanResponse,
    ScenePollInfo,
)
from ..site_anomaly import disclaimer_for

logger = logging.getLogger("backend.routers.raster_scan")

router = APIRouter(tags=["raster-scan"])

OVERLAY_BAND = "ndci"

# The 404 for "no rendered run to read cells from", shared by every
# endpoint that reads the stored cells so the wording cannot drift apart.
NO_RASTER_TO_QUERY = "No raster overlay is available to query. Run a raster scan first."

# The 409 message for `mode=anomaly` when no cell anomaly can be computed;
# the machine-readable `reason`/`cause` travel next to it.
ANOMALY_MODE_UNAVAILABLE = (
    "anomaly mode needs BASELINE_MODE=test and a valid Level B (per-cell) TEST baseline "
    "for this run's season; use mode=ndci for the highest-NDCI ranking"
)


def _anomaly_unavailable(unavailable: cell_anomaly.Unavailable) -> HTTPException:
    return HTTPException(status_code=409, detail={
        "reason": unavailable.reason,
        "cause": unavailable.cause,
        "season_key": unavailable.season_key,
        "message": ANOMALY_MODE_UNAVAILABLE,
    })


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
    hide the last picture that still exists.

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


def _asset_on_disk(overlay: dict, name: str) -> bool:
    """True when the named asset is recorded AND its PNG still exists."""
    asset = (overlay.get("assets") or {}).get(name)
    return bool(asset) and "path" in asset and Path(asset["path"]).exists()


def _iso_utc(value) -> str | None:
    """A stored (SQLite: naive, UTC) timestamp as an ISO 8601 UTC string."""
    return None if value is None else as_aware_utc(value).isoformat()


def _scene_thresholds() -> tuple[float | None, int | None]:
    """The scene-screen thresholds as currently configured.

    `scene_thresholds()` raises on an invalid environment value rather than
    substituting a default. Metadata must still be served in that case, but
    a guessed threshold would misstate the criterion, so both are null.
    """
    try:
        max_cloud_fraction, min_water_pixels = bridge.scene_thresholds()
    except ValueError as exc:
        logger.warning("scene thresholds unavailable for /raster-scan: %s", exc)
        return None, None
    return max_cloud_fraction, min_water_pixels


def _latest_scene(db: Session, served_run_id: int | None) -> LatestSceneInfo | None:
    """The assessment row with the greatest acquisition date, or None."""
    row = db.execute(
        select(SceneAssessmentRow)
        .order_by(SceneAssessmentRow.acquisition_date.desc())
        .limit(1)
    ).scalars().first()
    if row is None:
        return None
    max_cloud_fraction, min_water_pixels = _scene_thresholds()
    used = row.used_in_run_id is not None
    return LatestSceneInfo(
        acquisition_date=row.acquisition_date,
        decision=row.decision,
        cloud_fraction=row.cloud_fraction,
        threshold_cloud_fraction=max_cloud_fraction,
        min_water_pixels=min_water_pixels,
        reason=row.reason,
        used_in_run_id=row.used_in_run_id,
        assessed_at=_iso_utc(row.assessed_at),
        settled=is_settled(row.acquisition_date, row.assessed_at),
        used_in_served_run=used and row.used_in_run_id == served_run_id,
        # Used by a scan, yet no longer assessed as passing: the raster was
        # built from the date before it was re-assessed (trigger.py keeps
        # `used_in_run_id` through a re-assessment).
        reassessed_after_use=used and row.decision != PASSED,
    )


def _last_used_scene_date(db: Session) -> str | None:
    """The greatest acquisition date any raster scan has used."""
    return db.execute(
        select(func.max(SceneAssessmentRow.acquisition_date)).where(
            SceneAssessmentRow.used_in_run_id.is_not(None)
        )
    ).scalar_one_or_none()


def _poll_info(db: Session) -> ScenePollInfo | None:
    """The newer-scene poll's recorded health, or None when it has none."""
    status = db.get(ScenePollStatus, POLL_STATUS_ID)
    if status is None:
        return None
    return ScenePollInfo(
        last_poll_started_at=_iso_utc(status.last_poll_started_at),
        last_poll_ok_at=_iso_utc(status.last_poll_ok_at),
        last_error=status.last_error,
        last_error_at=_iso_utc(status.last_error_at),
        last_error_kind=status.last_error_kind,
    )


def _scene_fields(db: Session, served_run_id: int | None) -> dict:
    """The three latest-scene response fields, independent of whether an
    overlay is served (a failing poll matters most when there is none)."""
    return {
        "latest_scene": _latest_scene(db, served_run_id),
        "last_used_scene_date": _last_used_scene_date(db),
        "poll": _poll_info(db),
    }


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
            **_scene_fields(db, None),
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
        source_metadata=rendered.source_metadata,
        completed_at=(
            as_aware_utc(rendered.completed_at).isoformat() if rendered.completed_at else None
        ),
        coverage=_coverage(overlay),
        bounds=(overlay.get("bounds") or {}).get("leaflet_bounds"),
        legend=overlay.get("legend"),
        overlay_url=f"/raster-scan/overlay.png?run_id={rendered.id}",
        true_color_url=(
            f"/raster-scan/true-color.png?run_id={rendered.id}"
            if _asset_on_disk(overlay, "true_color")
            else None
        ),
        stale_run_id=latest.id if latest and latest.id != rendered.id else None,
        **_scene_fields(db, rendered.id),
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


@router.get("/raster-scan/ndci-hires.png")
def get_raster_ndci_hires(
    run_id: int | None = Query(None, ge=1, le=2**63 - 1,
                               description="Exact rendered run; omit for the latest available."),
    db: Session = Depends(get_db),
) -> FileResponse:
    """NDCI of a Sentinel-2 composite over the whole map extent, about 80 m per pixel.

    Rendered by Earth Engine as of the run's date, newest clear pixel within
    a 180-day window (cloud-masked pixels may carry older scenes), with
    the same ramp, transparent where nothing was measured; cached on disk
    after the first request (which can take a minute or more). Sync, so the
    render runs in the threadpool. Never a placeholder: failures are typed
    HTTP errors (503 Earth Engine unusable, 404 no scene or no water, 502 the
    thumbnail download failed).
    """
    from ..raster_scan import hires

    rendered = _rendered_run(db, run_id)
    if rendered is None:
        raise HTTPException(status_code=404, detail=NO_RASTER_TO_QUERY)
    try:
        path = hires.render(rendered.id, rendered.date_used)
    except bridge.GEEAuthError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (bridge.NoCloudFreeImageryError, bridge.NoWaterPixelsError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=502, detail=f"The Earth Engine thumbnail could not be fetched: {exc}") from exc
    return FileResponse(path, media_type="image/png", filename=path.name)


@router.get("/raster-scan/true-color.png")
async def get_raster_true_color(
    run_id: int | None = Query(None, ge=1, le=2**63 - 1,
                               description="Exact rendered run; omit for the latest available."),
    db: Session = Depends(get_db),
) -> FileResponse:
    """True-color companion generated from this run's stored RGB bands."""
    rendered = _rendered_run(db, run_id)
    asset = (
        ((rendered.overlay or {}).get("assets") or {}).get("true_color")
        if rendered is not None
        else None
    )
    if not asset or not Path(asset["path"]).exists():
        raise HTTPException(
            status_code=404,
            detail="This raster run has no run-aligned true-color image.",
        )
    path = Path(asset["path"])
    return FileResponse(path, media_type="image/png", filename=path.name)


@router.get("/raster-scan/pixel", response_model=RasterPixelResponse)
def get_raster_pixel(
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
        raise HTTPException(status_code=404, detail=NO_RASTER_TO_QUERY)
    # `pixel.inspect_run`, opened up so the one blob read also serves the
    # anomaly block (which needs the cell's stored visible bands): same
    # read, same errors and messages, same `inspect_cell` and grid.
    try:
        cells = highlight_ranking.read_run_cells(rendered)
    except pixel_lookup.RasterCellsUnavailableError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    found = pixel_lookup.inspect_cell(cells, lat, lng, pixel_lookup.grid_for_run(rendered, cells))

    # One baseline resolution for the anomaly block AND the disclaimer; mode
    # off returns before any file is read and leaves every existing field as
    # it was. The disclaimer follows the baseline in force even when this
    # cell gets no anomaly (no usable Level B season, say).
    status = scientific_status.baseline_status()
    context = cell_anomaly.resolve(status, rendered.date_used)
    anomaly = None
    if isinstance(context, cell_anomaly.AnomalyContext):
        anomaly = cell_anomaly.pixel_anomaly(found, context, cells)

    return RasterPixelResponse(
        run_id=rendered.id,
        date_used=rendered.date_used,
        scale_m=rendered.scale_m,
        **found,
        anomaly=anomaly,
        disclaimer=disclaimer_for(status),
    )


@router.get(
    "/raster-scan/highlights",
    response_model=RasterHighlightsResponse | RasterAnomalyHighlightsResponse,
)
def get_raster_highlights(
    run_id: int | None = Query(None, ge=1, le=2**63 - 1,
                               description="Exact rendered run; omit for the latest available."),
    n: int = Query(5, ge=3, le=200, description="Number of pins wanted (3-200)."),
    min_separation_m: int = Query(
        3000, ge=1000, le=10000,
        description="De-duplication radius in metres: a cell closer than this to a "
        "higher-ranked pin is skipped."),
    mode: Literal["ndci", "anomaly"] | None = Query(
        None, description="'ndci' ranks by NDCI. 'anomaly' pins cells at least 2 robust z "
        "above their own TEST seasonal baseline (BASELINE_MODE=test and a usable Level B "
        "baseline, else 409 with the reason). Omitted: 'anomaly' when it can be "
        "computed for this run, else 'ndci'."),
    db: Session = Depends(get_db),
) -> RasterHighlightsResponse | RasterAnomalyHighlightsResponse:
    """Highlight pins for one stored run, de-duplicated.

    Reads the blob the overlay was drawn from, like `/raster-scan/pixel`
    (sync, so the read and the baseline file reads run in the threadpool)
    -- never Earth Engine. The same run and baseline always yield the same
    pins.

    'ndci': the highest-NDCI measured cells -- a ranking by value inside
    one scan: high NDCI can also come from suspended sediment, shallow
    bottom, sun glint or cloud edges, and does not by itself identify a
    bloom. Never ranks against the baseline and never loads a cell
    baseline; its disclaimer, like every response's, is the one for the
    TEST baseline in force (one ``baseline_status()``).

    'anomaly': measured cells whose NDCI is >= 2 robust z above the cell's
    own TEST seasonal baseline (src/raster_scan/cell_anomaly.py), with the
    counts of how many cells were assessable and why the rest were not,
    the baseline block and the TEST disclaimer. A statistical anomaly,
    uncalibrated; never a risk level.

    Run resolution and 404s are the pixel endpoint's: no rendered run, an
    explicit run that is not servable, or a run whose cells are gone.
    `mode=anomaly` answers 409 (`detail.reason`: mode_off,
    no_cell_baseline, invalid:<code>, run_date_unusable,
    visible_bands_missing) -- checked for mode_off before the run, since no
    run could change that answer. Both modes apply the data-quality
    screens (src/raster_scan/cell_anomaly.py): degenerate NDCI and low
    visible signal never pin.
    """
    # One resolution per request in every mode: 'ndci' needs it only for the
    # disclaimer, the other modes also for the cell season below.
    status = scientific_status.baseline_status()
    if mode == "anomaly" and status.get("mode") != "test":
        raise _anomaly_unavailable(
            cell_anomaly.Unavailable(reason=cell_anomaly.MODE_OFF, cause=None, season_key=None))
    rendered = _rendered_run(db, run_id)
    if rendered is None:
        raise HTTPException(status_code=404, detail=NO_RASTER_TO_QUERY)

    context = None if mode == "ndci" else cell_anomaly.resolve(status, rendered.date_used)
    if isinstance(context, cell_anomaly.Unavailable) and mode == "anomaly":
        raise _anomaly_unavailable(context)

    try:
        cells = highlight_ranking.read_run_cells(rendered)
    except pixel_lookup.RasterCellsUnavailableError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    grid = pixel_lookup.grid_for_run(rendered, cells)

    ranked = None
    if isinstance(context, cell_anomaly.AnomalyContext):
        try:
            ranked = highlight_ranking.rank_anomaly_cells(
                cells, grid=grid, context=context, n=n, min_separation_m=min_separation_m,
            )
        except cell_anomaly.VisibleBandsMissing:
            # Never score unscreened cells: refuse an explicit request, and
            # let the default fall back to the NDCI ranking (which says so).
            if mode == "anomaly":
                raise _anomaly_unavailable(cell_anomaly.Unavailable(
                    reason=cell_anomaly.VISIBLE_BANDS_MISSING, cause=None,
                    season_key=context.season_key)) from None
    metric = "ndci"  # ndci mode: the band the overlay draws
    if ranked is None:
        ranked = highlight_ranking.rank_cells(
            cells, grid=grid, n=n, min_separation_m=min_separation_m, metric=metric,
        )
        context = None

    if isinstance(context, cell_anomaly.AnomalyContext):
        return RasterAnomalyHighlightsResponse(
            run_id=rendered.id,
            mode="anomaly",
            metric="robust_z",
            n_requested=n,
            min_separation_m=min_separation_m,
            baseline=context.baseline(),
            disclaimer=context.disclaimer,
            **ranked,
        )
    return RasterHighlightsResponse(
        run_id=rendered.id,
        mode="ndci",
        metric=metric,
        n_requested=n,
        min_separation_m=min_separation_m,
        disclaimer=disclaimer_for(status),
        **ranked,
    )
