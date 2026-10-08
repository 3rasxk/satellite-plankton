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
from .scan import STALE_RUN_HOURS, ConcurrentRasterScanError, run_raster_scan

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


def _consumes_scene(row: RasterScanRun, now: datetime) -> bool:
    """Whether this run's trigger scene counts as already handled.

    'error' and 'partial_error' did not deliver a complete raster, and a
    'running' row older than STALE_RUN_HOURS belongs to a crashed process
    (scan.py presumes it dead on the next scan), so none of them may block a
    retry of their scene. A younger 'running' row may be live and still
    consumes it. Retry spacing is still enforced by the cooldown, which
    counts every attempt.
    """
    if row.trigger_scene_timestamp is None:
        return False
    if row.status in ("error", "partial_error"):
        return False
    if row.status == "running":
        age = now - as_aware_utc(row.started_at)
        return age < timedelta(hours=STALE_RUN_HOURS)
    return True


def _starts_cooldown(row: RasterScanRun) -> bool:
    """Whether this run counts as an attempt for the retry cooldown.

    A bootstrap stopped by shutdown was cut short by the process, not by
    the data or its budget, so it must not delay the next poll by a full
    cooldown. A budget-stopped bootstrap did spend its budget and still
    counts, as does every other attempt.
    """
    metadata = row.source_metadata
    return not (isinstance(metadata, dict) and metadata.get("search_stopped") == "shutdown")


def poll_and_maybe_scan() -> None:
    """Scheduled poll; failures are logged and never crash the scheduler."""
    if shutdown.stop_requested():
        logger.info("raster_scan poll: shutdown requested; not polling")
        return
    with SessionLocal() as db:
        try:
            latest_attempt = next(
                (
                    row
                    for row in db.execute(
                        select(RasterScanRun).order_by(RasterScanRun.started_at.desc())
                    ).scalars()
                    if _starts_cooldown(row)
                ),
                None,
            )
            now = datetime.now(timezone.utc)
            latest_triggered = next(
                (
                    row
                    for row in db.execute(
                        select(RasterScanRun).order_by(RasterScanRun.started_at.desc())
                    ).scalars()
                    if _consumes_scene(row, now)
                ),
                None,
            )

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
