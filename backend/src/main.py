"""
FastAPI app entrypoint. Wires up DB init, monitored-grid seed, the
scheduler, and the API routers.

Run with: `uvicorn src.main:app --reload` from `backend/` (see README.md).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import func, select

from . import _detection as bridge
from . import shutdown
from .config import SCHEDULER_ENABLED
from .db import SessionLocal, get_db, init_db  # noqa: F401  (get_db re-exported for routers/tests)
from .db_models import DetectionCache, MonitoredSite
from .routers import (
    alerts, detect, raster_scan, regional_scan, risk_map, satellite,
    satellite_image, summary, timeseries,
)
from .scheduler import create_scheduler, ensure_monitored_sites

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("backend.main")

_scheduler = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Startup/shutdown, replacing the deprecated @app.on_event hooks.

    Everything before the `yield` blocks the server from accepting
    requests, so only work that every route depends on belongs here.
    Measured at ~1.1s total, almost all of it the module import chain
    (detection/src -> data-pipeline/src -> earthengine-api); the three
    DB steps are ~0.01s each and are kept blocking deliberately -- every
    router queries the tables they create and seed, so deferring them
    would only trade 30ms for a window where routes hit missing tables.

    When scheduling is enabled (the production default), create_scheduler()
    returns a BackgroundScheduler whose .start() hands its jobs to its own
    thread pool and returns immediately. Its refresh_grid job fires at boot
    (scheduler.py's next_run_time=now) and makes real, multi-second GEE calls
    concurrently with serving. refresh_grid commits per site, so /risk-map
    fills in site by site; sites it has not reached yet report the honest
    `no_data_yet` status. Tests set SCHEDULER_ENABLED=false before importing
    this module. Shutdown first raises the cooperative stop flag
    (src/shutdown.py), then waits for any active job to reach its next
    checkpoint and return.
    """
    global _scheduler
    logger.info("startup: init_db")
    init_db()
    logger.info("startup: ensure_monitored_sites")
    ensure_monitored_sites()
    scheduler = None
    # A previous lifespan in this process (tests, --reload) may have left it set.
    shutdown.clear_stop()
    try:
        if SCHEDULER_ENABLED:
            logger.info("startup: starting scheduler")
            scheduler = create_scheduler()
            scheduler.start()
            _scheduler = scheduler
        else:
            logger.info("startup: scheduler disabled")

        yield
    finally:
        # APScheduler cannot interrupt a job that is already running.
        # Waiting here is therefore essential: shutdown(wait=False)
        # leaves its ThreadPoolExecutor workers alive, and Python waits
        # for those non-daemon threads later during interpreter exit.
        # The wait is NOT bounded by one network call on its own: an
        # active job loops over many GEE round trips (7 grid sites, or up
        # to hundreds of bootstrap archive windows). So the stop flag is
        # raised first, and every job checks it between sites/windows;
        # the wait then lasts until the in-flight step returns -- one
        # site's few GEE calls or one bootstrap window, each request
        # bounded by data-pipeline auth.py's deadline -- not until the
        # whole job would have finished.
        shutdown.request_stop()
        if scheduler is not None and scheduler.running:
            logger.info("shutdown: waiting for scheduler jobs")
            scheduler.shutdown(wait=True)
        # Every job has returned; a flag left set would stop direct
        # (non-scheduled) calls later in this process, e.g. in tests.
        shutdown.clear_stop()
        _scheduler = None


app = FastAPI(
    title="Gulf of Thailand Algal Bloom Monitor -- API",
    description=(
        "Physics-based (not ML) early-warning API for harmful algal blooms in the upper "
        "Gulf of Thailand. Reports Sentinel-2 spectral index values and scene dates. "
        "Anomaly detection and risk evaluation are not computed because no valid "
        "spectral-index baseline exists. MODIS chlor_a time-series anomalies remain "
        "a separate, same-quantity calculation. Every response carries a "
        "`disclaimer` field -- see CLAUDE.md's truth boundary."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# Local dev only: the frontend (frontend-dashboard agent) runs on Vite's
# dev server (default http://localhost:5173), a different origin than
# this API (http://localhost:8000) -- without CORS the browser blocks
# every request. Not a security-hardening decision (no auth/cookies on
# this API to begin with, CLAUDE.md: no accounts), just what's needed for
# the web dashboard to reach the API at all in local development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(alerts.router)
app.include_router(risk_map.router)
app.include_router(timeseries.router)
app.include_router(detect.router)
app.include_router(satellite.router)
app.include_router(satellite_image.router)
app.include_router(summary.router)
app.include_router(regional_scan.router)
app.include_router(raster_scan.router)


@app.exception_handler(bridge.GEEAuthError)
def gee_auth_error_handler(request, exc: bridge.GEEAuthError) -> JSONResponse:
    # Belt-and-suspenders: routers already convert this to a 503 where
    # they call detect()/risk_level() directly, but this app-level
    # handler ensures it is never a raw 500 anywhere it might still
    # propagate un-translated.
    return JSONResponse(
        status_code=503,
        content={"detail": f"Google Earth Engine is not authenticated: {exc}"},
    )


@app.get("/", tags=["meta"])
def root() -> dict:
    """Service metadata plus honest first-refresh progress.

    `first_refresh` reports how far the scheduler's boot-time
    refresh_grid pass has got, counted from real DetectionCache rows --
    nothing here is estimated or synthesised. A caller can distinguish
    "the server is up but the grid has not been read yet" from "the
    grid has been read and this is genuinely all the data there is",
    which the per-site statuses on /risk-map also express individually
    (`no_data_yet` vs no_imagery/no_water_pixels/no_climatology/error).
    """
    db = SessionLocal()
    try:
        total_sites = db.execute(select(func.count()).select_from(MonitoredSite)).scalar_one()
        # A cache row means the scheduler reached this site. Whether that
        # attempt produced a usable reading is a separate question, so it
        # is a separate number -- an attempted site with status != 'ok' is
        # real data about a real failure, not a reading.
        sites_attempted = db.execute(select(func.count()).select_from(DetectionCache)).scalar_one()
        sites_with_usable_reading = db.execute(
            select(func.count()).select_from(DetectionCache).where(DetectionCache.status == "ok")
        ).scalar_one()
    finally:
        db.close()

    if total_sites == 0:
        state = "no_sites_configured"
    elif sites_attempted == 0:
        state = "not_started"
    elif sites_attempted < total_sites:
        state = "in_progress"
    else:
        state = "complete"

    return {
        "service": "Gulf of Thailand Algal Bloom Monitor -- API",
        "docs": "/docs",
        "first_refresh": {
            "state": state,
            "sites_attempted": sites_attempted,
            "sites_with_usable_reading": sites_with_usable_reading,
            "total_sites": total_sites,
            "note": (
                "sites_attempted counts sites the scheduler has reached; "
                "sites_with_usable_reading counts those whose attempt returned "
                "status='ok'. Sites not yet reached are reported as "
                "status='no_data_yet' by /risk-map -- never as a risk level, "
                "never with a placeholder value."
            ),
        },
        "endpoints": [
            "/risk-map",
            "/risk-map/{site_id}/image",
            "/timeseries",
            "/detect",
            "/satellite-image",
            "/summary",
            "/raster-scan",
            "/raster-scan/pixel",
        ],
    }
