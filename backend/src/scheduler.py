"""
APScheduler job that refreshes DetectionCache for every MonitoredSite on
a fixed interval (src/config.py SCHEDULER_INTERVAL_MINUTES), so
/risk-map and /summary read a cache instead of hitting GEE live per
request.

Failure handling (backend-api.md: "a scheduler failure should log
clearly, not silently serve stale data as fresh without marking it"):
a per-site failure (GEEAuthError or anything else) is logged, and if a
prior cache row exists for that site it is marked `stale=True` --
`fetched_at` and every substantive field are left untouched (the row
still says exactly when its data is actually from), so a client reading
`stale=True` + an old `fetched_at` gets an honest picture, never a
row that looks fresh but silently isn't. If no prior row exists yet, a
placeholder row is inserted with status='error', stale=True, so
/risk-map's "no_data_yet" branch isn't hit forever if the very first
scheduled run fails.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import _detection as bridge
from .config import SCHEDULER_INTERVAL_MINUTES, today_str
from .db import SessionLocal
from .db_models import DetectionCache, MonitoredSite
from .grid import MONITORED_GRID
from .satellite_meta import fetch_satellite_meta

logger = logging.getLogger("backend.scheduler")


def _upsert_site(db: Session, site_id: str) -> None:
    if db.get(MonitoredSite, site_id) is None:
        info = next(s for s in MONITORED_GRID if s["site_id"] == site_id)
        db.add(MonitoredSite(**info))


def ensure_monitored_sites() -> None:
    """Upsert MONITORED_GRID into monitored_sites. Called at app startup,
    before the first scheduler run."""
    db = SessionLocal()
    try:
        for info in MONITORED_GRID:
            existing = db.get(MonitoredSite, info["site_id"])
            if existing is None:
                db.add(MonitoredSite(**info))
            else:
                existing.name = info["name"]
                existing.lat = info["lat"]
                existing.lng = info["lng"]
        db.commit()
    finally:
        db.close()


def refresh_one_site(db: Session, site: MonitoredSite, target_date: str) -> None:
    """Refresh (or mark-stale-on-failure) one site's DetectionCache row.
    Never raises -- every exception is caught here, logged, and turned
    into a stale marker so the scheduler loop continues for the
    remaining sites."""
    existing = db.execute(
        select(DetectionCache).where(DetectionCache.site_id == site.site_id)
    ).scalar_one_or_none()

    try:
        prediction = bridge.risk_level(site.lat, site.lng, target_date)
        meta = fetch_satellite_meta(site.lat, site.lng, target_date)
        detection = prediction["detection"]

        fields = dict(
            target_date=target_date,
            status=detection["status"],
            detected=detection["detected"],
            anomaly_z=detection["anomaly_z"],
            index_used=detection["index_used"],
            index_values=detection["index_values"],
            reason=detection["reason"],
            level=prediction["level"],
            triggered_rules=prediction["triggered_rules"],
            confidence_label=prediction["confidence_label"],
            sst_anomaly=prediction["sst_anomaly"],
            trend_14d_rising=prediction["trend_14d"].get("rising"),
            rainfall_mm=(prediction["rainfall"] or {}).get("recent_rainfall_mm"),
            cloud_fraction=meta["cloud_fraction"],
            actual_date=meta["actual_date"],
            fetched_at=datetime.now(timezone.utc),
            stale=False,
            error=None,
        )

        if existing is None:
            db.add(DetectionCache(site_id=site.site_id, **fields))
        else:
            for key, value in fields.items():
                setattr(existing, key, value)
        db.commit()
        logger.info("scheduler: refreshed %s -> status=%s level=%s", site.site_id,
                    detection["status"], prediction["level"])

    except Exception as exc:  # noqa: BLE001 -- deliberately broad: this is the
        # scheduler's top-level per-site guard. GEEAuthError is included
        # here (not re-raised) because a scheduler *job* failing for one
        # site must not crash the whole job/app the way it would if
        # detect()/risk_level() raised it into a request handler --
        # instead we mark the cache stale and move on to the next site.
        # This does NOT catch-and-fabricate a result: no fields describing
        # a satellite reading are touched below, only `stale`/`error`.
        logger.error("scheduler: refresh failed for %s: %s: %s", site.site_id,
                     type(exc).__name__, exc)
        if existing is not None:
            existing.stale = True
            existing.error = f"{type(exc).__name__}: {exc}"
            db.commit()
        else:
            db.add(
                DetectionCache(
                    site_id=site.site_id,
                    target_date=target_date,
                    status="error",
                    stale=True,
                    error=f"{type(exc).__name__}: {exc}",
                    fetched_at=datetime.now(timezone.utc),
                )
            )
            db.commit()


def refresh_grid() -> None:
    """The scheduled job: refresh every monitored site's cache once."""
    target_date = today_str()
    logger.info("scheduler: refresh_grid starting for %s", target_date)
    db = SessionLocal()
    try:
        sites = db.execute(select(MonitoredSite)).scalars().all()
        for site in sites:
            refresh_one_site(db, site, target_date)
    finally:
        db.close()
    logger.info("scheduler: refresh_grid done")


def create_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        refresh_grid,
        "interval",
        minutes=SCHEDULER_INTERVAL_MINUTES,
        next_run_time=datetime.now(timezone.utc),  # fire once immediately at startup too
        id="refresh_grid",
        max_instances=1,
        coalesce=True,
    )
    return scheduler
