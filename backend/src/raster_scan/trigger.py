"""Poll Sentinel-2 metadata and start a whole-polygon raster when fresh."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from .. import _detection as bridge
from .. import _study_area
from .. import shutdown
from ..config import (
    RASTER_SCAN_COOLDOWN_HOURS,
    RASTER_SCAN_POLL_LOOKBACK_DAYS,
    as_aware_utc,
    today_str,
)
from ..db import SessionLocal
from ..db_models import RasterScanRun
from .scan import ConcurrentRasterScanError, run_raster_scan

logger = logging.getLogger("backend.raster_scan.trigger")


def should_trigger_scan(
    last_attempt_started_at: datetime | None,
    last_trigger_scene_timestamp: str | None,
    newest_scene_timestamp: str | None,
    cooldown_hours: int,
    now: datetime,
) -> bool:
    """Require both a new candidate acquisition and an elapsed cooldown."""
    if newest_scene_timestamp is None:
        return False
    if last_attempt_started_at is None:
        return True
    is_new_scene = (
        last_trigger_scene_timestamp is None
        or newest_scene_timestamp > last_trigger_scene_timestamp
    )
    cooldown_met = (
        now - as_aware_utc(last_attempt_started_at)
    ) >= timedelta(hours=cooldown_hours)
    return is_new_scene and cooldown_met


def poll_and_maybe_scan() -> None:
    """Scheduled poll; failures are logged and never crash the scheduler."""
    if shutdown.stop_requested():
        logger.info("raster_scan poll: shutdown requested; not polling")
        return
    with SessionLocal() as db:
        try:
            latest_attempt = db.execute(
                select(RasterScanRun).order_by(RasterScanRun.started_at.desc())
            ).scalars().first()
            latest_triggered = db.execute(
                select(RasterScanRun)
                .where(
                    RasterScanRun.trigger_scene_timestamp.is_not(None),
                    # A failed run must not consume its scene; retry is
                    # still spaced by the cooldown via latest_attempt.
                    RasterScanRun.status != "error",
                )
                .order_by(RasterScanRun.started_at.desc())
            ).scalars().first()

            since = datetime.now(timezone.utc) - timedelta(
                days=RASTER_SCAN_POLL_LOOKBACK_DAYS
            )
            try:
                newest = bridge.get_newest_scene_timestamp(
                    _study_area.STUDY_AREA_POLYGON_LATLNG,
                    since.strftime("%Y-%m-%d"),
                )
            except bridge.GEEAuthError as exc:
                logger.error("raster_scan poll: authentication failed; skipping: %s", exc)
                return

            now = datetime.now(timezone.utc)
            if not should_trigger_scan(
                latest_attempt.started_at if latest_attempt else None,
                latest_triggered.trigger_scene_timestamp if latest_triggered else None,
                newest,
                RASTER_SCAN_COOLDOWN_HOURS,
                now,
            ):
                logger.info(
                    "raster_scan poll: not triggering (candidate=%s, latest_run_id=%s)",
                    newest,
                    latest_attempt.id if latest_attempt else None,
                )
                return

            logger.info("raster_scan poll: triggering for candidate %s", newest)
            try:
                run_raster_scan(
                    db,
                    today_str(),
                    trigger_scene_timestamp=newest,
                )
            except ConcurrentRasterScanError as exc:
                logger.info("raster_scan poll: %s", exc)
        except Exception as exc:  # noqa: BLE001 -- scheduler-job boundary
            logger.error(
                "raster_scan poll: unexpected failure: %s: %s",
                type(exc).__name__,
                exc,
            )
