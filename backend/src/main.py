"""
FastAPI app entrypoint. Wires up: DB init, monitored-grid seed,
validation-events seed (read-only mirror of data/validation/events.csv),
the scheduler, and the five routers.

Run with: `uvicorn src.main:app --reload` from `backend/` (see README.md).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import _detection as bridge
from .db import SessionLocal, get_db, init_db  # noqa: F401  (get_db re-exported for routers/tests)
from .db_models import ValidationEvent
from .routers import alerts, detect, risk_map, satellite, satellite_image, summary, timeseries, validation
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

    The scheduler is started, not awaited: create_scheduler() returns a
    BackgroundScheduler whose .start() hands its jobs to its own thread
    pool and returns immediately. Its refresh_grid job fires at boot
    (scheduler.py's next_run_time=now) and makes real, multi-second GEE
    calls -- concurrently with serving, never blocking it. refresh_grid
    commits per site, so /risk-map fills in site by site rather than
    all at once; sites it has not reached yet report the honest
    `no_data_yet` status, never a placeholder reading.
    """
    global _scheduler
    logger.info("startup: init_db")
    init_db()
    logger.info("startup: ensure_monitored_sites")
    ensure_monitored_sites()
    logger.info("startup: seed_validation_events")
    _seed_validation_events()

    logger.info("startup: starting scheduler")
    _scheduler = create_scheduler()
    _scheduler.start()

    yield

    if _scheduler is not None:
        _scheduler.shutdown(wait=False)


app = FastAPI(
    title="Gulf of Thailand Algal Bloom Monitor -- API",
    description=(
        "Physics-based (not ML) early-warning API for harmful algal blooms in the upper "
        "Gulf of Thailand. Wraps detection/src's spectral-index + MODIS-climatology "
        "anomaly detection and rule-based risk escalation. Every response carries a "
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
app.include_router(validation.router)


def _seed_validation_events() -> None:
    """Upsert data/validation/events.csv into validation_events -- read-
    only relative to the file; never written to via any API route."""
    rows = bridge.load_events()
    db = SessionLocal()
    try:
        for row in rows:
            existing = db.get(ValidationEvent, row["event_id"])
            fields = dict(
                date=row.get("date") or None,
                date_start=row.get("date_start") or None,
                date_end=row.get("date_end") or None,
                lat=float(row["lat"]) if row.get("lat") else None,
                lng=float(row["lng"]) if row.get("lng") else None,
                location_name=row["location_name"],
                location_precision=row["location_precision"],
                species=row["species"],
                cell_count=row.get("cell_count") or None,
                event_type=row["event_type"],
                source_type=row["source_type"],
                source_citation=row["source_citation"],
                confidence=row["confidence"],
            )
            if existing is None:
                db.add(ValidationEvent(event_id=row["event_id"], **fields))
            else:
                for key, value in fields.items():
                    setattr(existing, key, value)
        db.commit()
    finally:
        db.close()


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
    return {
        "service": "Gulf of Thailand Algal Bloom Monitor -- API",
        "docs": "/docs",
        "endpoints": [
            "/risk-map",
            "/risk-map/{site_id}/image",
            "/timeseries",
            "/detect",
            "/satellite-image",
            "/summary",
            "/validation",
        ],
    }
