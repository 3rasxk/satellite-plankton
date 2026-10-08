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

Satellite imagery (added alongside the numeric refresh): each cycle also
renders and caches a true-color and an NDCI-heatmap PNG per site
(`data-pipeline/src/imagery.py`, via `bridge.get_true_color_image`/
`get_ndci_heatmap`), stored as BLOB columns on the same `DetectionCache`
row (`true_color_png`/`ndci_heatmap_png`). This is a caching decision, not
an on-demand one, specifically because this grid is small (7 sites),
fixed, and already on a periodic refresh cycle -- unlike `/detect` and the
new `/satellite-image` endpoint, which take an arbitrary caller-chosen
lat/lng/date (an effectively unbounded key space with nothing sensible to
pre-render). The decision is grounded in a real, live measurement made
during this build (see the backend-api build report): a warm numeric
`get_sentinel2_bands` call took ~4.2s; adding a true-color render added
~+2-4s more, an NDCI heatmap ~+2-3s more -- each image roughly doubles or
triples the round trip. Serving that live, per-request, from `/risk-map`
(which today reads a plain DB row in milliseconds) would turn a
sub-second endpoint into a multi-site, multi-second one on every poll,
for imagery that does not change between Sentinel-2 revisits (~5 days)
anyway. Paying that cost once per scheduler cycle (default every 6h) for
7 sites (~14 extra image renders, roughly 35-105s added to the cycle,
which already runs in the background) and then serving cached bytes in
milliseconds per request is the correct trade for this bounded set --
mirrors exactly why the numeric fields are cached here at all.

Image rendering is only attempted when the numeric detection for that
site succeeded (`status == 'ok'`) -- if `detect()` itself couldn't get a
usable reading (no_imagery/no_water_pixels), the same
underlying scene problem would make the image render fail the same way
(same-scene guarantee), so a second live GEE round trip that's expected
to fail is skipped rather than attempted and logged as noise. A transient
image-fetch failure (e.g. a network hiccup fetching the thumbnail bytes,
distinct from GEE auth or "no scene available") does not mark the whole
site stale -- the numeric fields are still fresh and real; only the image
columns are left null with `image_status='fetch_error'`, so a client can
tell "no picture this cycle" from "no numeric reading this cycle" instead
of conflating the two.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from . import _detection as bridge
from . import shutdown
from .config import RASTER_SCAN_POLL_INTERVAL_HOURS, SCHEDULER_INTERVAL_MINUTES, today_str
from .db import SessionLocal
from .db_models import DetectionCache, MonitoredSite
from .grid import MONITORED_GRID
from .raster_scan.storage import apply_retention
from .raster_scan.trigger import poll_and_maybe_scan
from .satellite_meta import fetch_satellite_meta
from .services.cache_service import clear_cache

logger = logging.getLogger("backend.scheduler")

RETIRED_MONITORED_SITE_IDS = {"upper_gulf_open_water"}


def _upsert_site(db: Session, site_id: str) -> None:
    if db.get(MonitoredSite, site_id) is None:
        info = next(s for s in MONITORED_GRID if s["site_id"] == site_id)
        db.add(MonitoredSite(**info))


def ensure_monitored_sites() -> None:
    """Sync configured sites and remove explicitly retired grid entries."""
    db = SessionLocal()
    try:
        for site_id in RETIRED_MONITORED_SITE_IDS:
            db.execute(delete(DetectionCache).where(DetectionCache.site_id == site_id))
            db.execute(delete(MonitoredSite).where(MonitoredSite.site_id == site_id))
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


def _refresh_images(lat: float, lng: float, target_date: str, detection_status: str) -> dict:
    """Render + fetch true_color/ndci_heatmap PNG bytes for one site, for
    caching alongside the numeric DetectionCache row (see module
    docstring "Satellite imagery" for the caching-vs-on-demand reasoning).

    GEEAuthError is deliberately NOT caught here -- it propagates to
    refresh_one_site's own broad except, which marks the *whole site*
    stale (numeric fields included). That is correct: GEEAuthError means
    the GEE session itself is unusable, not "no image for this scene",
    so it must not be swallowed into a per-image status as if it were a
    normal data gap.
    """
    if detection_status != "ok":
        # Same-scene guarantee (data-pipeline/src/imagery.py): if detect()
        # itself couldn't get a usable numeric reading for this date, a
        # second live GEE call for the image would hit the same
        # underlying scene problem. Skip rather than retry-and-fail.
        return dict(
            true_color_png=None,
            ndci_heatmap_png=None,
            image_status="skipped_detection_not_ok",
            image_error=None,
        )

    try:
        true_color = bridge.get_true_color_image(lat, lng, target_date)
        ndci = bridge.get_ndci_heatmap(lat, lng, target_date)
        return dict(
            true_color_png=true_color["image_bytes"],
            ndci_heatmap_png=ndci["image_bytes"],
            image_status="ok",
            image_error=None,
        )
    except bridge.GEEAuthError:
        raise
    except bridge.NoCloudFreeImageryError as exc:
        return dict(
            true_color_png=None,
            ndci_heatmap_png=None,
            image_status="no_imagery",
            image_error=str(exc),
        )
    except bridge.NoWaterPixelsError as exc:
        return dict(
            true_color_png=None,
            ndci_heatmap_png=None,
            image_status="no_water_pixels",
            image_error=str(exc),
        )
    except Exception as exc:  # noqa: BLE001 -- transient thumbnail-fetch
        # failure (network/upstream, e.g. urllib.error.URLError). The
        # numeric reading already succeeded and must not be discarded
        # over an image-only problem -- see module docstring.
        logger.warning(
            "scheduler: image render failed for %.4f,%.4f on %s: %s: %s",
            lat, lng, target_date, type(exc).__name__, exc,
        )
        return dict(
            true_color_png=None,
            ndci_heatmap_png=None,
            image_status="fetch_error",
            image_error=f"{type(exc).__name__}: {exc}",
        )


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
        image_fields = _refresh_images(site.lat, site.lng, target_date, detection["status"])

        fields = dict(
            target_date=target_date,
            status=detection["status"],
            detected=None,
            spatial_anomaly_z=None,
            signal_anomaly_level=prediction.get("signal_anomaly_level"),
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
            actual_date=detection.get("actual_date"),
            fetched_at=datetime.now(timezone.utc),
            stale=False,
            error=None,
            **image_fields,
        )

        if existing is None:
            db.add(DetectionCache(site_id=site.site_id, **fields))
        else:
            for key, value in fields.items():
                setattr(existing, key, value)
        db.commit()
        clear_cache()
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
            # Cooperative stop (src/shutdown.py): lifespan teardown waits
            # for this job, so check between sites rather than finishing
            # every remaining site's GEE round trips first. Sites not
            # reached keep their previous cache row untouched.
            if shutdown.stop_requested():
                logger.info("scheduler: refresh_grid stopping early -- shutdown requested")
                return
            refresh_one_site(db, site, target_date)
    finally:
        db.close()
    logger.info("scheduler: refresh_grid done")


def expire_raster_scans() -> None:
    """Apply blob retention while preserving every run row and summary."""
    with SessionLocal() as db:
        try:
            result = apply_retention(db)
            logger.info("raster retention: expired=%s kept=%s", result["expired"], result["kept"])
        except Exception as exc:  # noqa: BLE001 -- scheduler-job boundary
            logger.error("raster retention failed: %s: %s", type(exc).__name__, exc)


def create_scheduler() -> BackgroundScheduler:
    # A previous lifespan (or a test) may have left the stop flag set.
    shutdown.clear_stop()
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
    scheduler.add_job(
        poll_and_maybe_scan,
        "interval",
        hours=RASTER_SCAN_POLL_INTERVAL_HOURS,
        id="poll_raster_scan",
        max_instances=1,
        coalesce=True,
        # Deliberately no next_run_time override -- must NOT fire at
        # process startup (spec §8): a job that can run for hours firing
        # on every --reload dev restart would be unworkable. max_instances=1
        # also doubles as overlap protection for the scan phase inside
        # poll_and_maybe_scan.
    )
    scheduler.add_job(
        expire_raster_scans,
        "interval",
        days=1,
        id="expire_raster_scans",
        max_instances=1,
        coalesce=True,
        # No startup execution: retention is maintenance, never a boot gate.
    )
    return scheduler
