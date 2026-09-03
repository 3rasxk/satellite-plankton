"""
Event-driven poll + cooldown trigger for the regional scan (spec §5).
`should_trigger_scan` is a pure decision function (unit-testable without
GEE or a DB); `poll_and_maybe_scan` is the impure orchestrator the
scheduler job (backend/src/scheduler.py) calls on its own interval.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from .. import _detection as bridge
from .. import _study_area
from ..config import (
    REGIONAL_SCAN_COOLDOWN_HOURS,
    REGIONAL_SCAN_GRID_SPACING_KM,
    REGIONAL_SCAN_POLL_LOOKBACK_DAYS,
    as_aware_utc,
    today_str,
)
from ..db import SessionLocal
from ..db_models import RegionalScanRun
from .scan import run_scan

logger = logging.getLogger("backend.regional_scan.trigger")


def should_trigger_scan(
    last_run: RegionalScanRun | None,
    newest_scene_date: str | None,
    cooldown_hours: int,
    now: datetime,
) -> bool:
    """Pure decision function -- spec §5's "both (a) and (b)" rule.

    (a) the poll's newest scene timestamp is newer than the last run's
        stored newest_scene_date.
    (b) at least `cooldown_hours` have elapsed since the last run started.

    No prior run -> True the moment a scene exists (nothing to compare
    against, nothing to cool down from). No scene info from the poll ->
    False (nothing to trigger on).
    """
    if newest_scene_date is None:
        return False
    if last_run is None:
        return True
    is_new_scene = (
        last_run.newest_scene_date is None or newest_scene_date > last_run.newest_scene_date
    )
    cooldown_met = (now - as_aware_utc(last_run.started_at)) >= timedelta(hours=cooldown_hours)
    return is_new_scene and cooldown_met


def poll_and_maybe_scan() -> None:
    """The scheduled job body: poll for scene freshness, decide, and run
    a full scan if warranted. Never raises -- a poll/scan failure here
    must not crash the scheduler process (mirrors scheduler.py's own
    top-level guard in refresh_one_site)."""
    db = SessionLocal()
    try:
        last_run = db.execute(
            select(RegionalScanRun).order_by(RegionalScanRun.started_at.desc())
        ).scalars().first()

        since = datetime.now(timezone.utc) - timedelta(days=REGIONAL_SCAN_POLL_LOOKBACK_DAYS)
        try:
            newest_scene_date = bridge.get_newest_scene_timestamp(
                _study_area.STUDY_AREA_POLYGON_LATLNG, since.strftime("%Y-%m-%d")
            )
        except bridge.GEEAuthError as exc:
            logger.error("regional_scan poll: GEEAuthError, skipping this tick: %s", exc)
            return

        now = datetime.now(timezone.utc)
        if not should_trigger_scan(last_run, newest_scene_date, REGIONAL_SCAN_COOLDOWN_HOURS, now):
            logger.info(
                "regional_scan poll: not triggering (newest_scene_date=%s, last_run_id=%s)",
                newest_scene_date, last_run.id if last_run else None,
            )
            return

        logger.info("regional_scan poll: triggering full scan (newest_scene_date=%s)", newest_scene_date)
        run_scan(db, today_str(), REGIONAL_SCAN_GRID_SPACING_KM, newest_scene_date=newest_scene_date)
    except Exception as exc:  # noqa: BLE001 -- top-level scheduler-job guard
        logger.error("regional_scan poll: unexpected failure: %s: %s", type(exc).__name__, exc)
    finally:
        db.close()
