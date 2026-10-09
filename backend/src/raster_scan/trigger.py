"""Latest-scene policy: assess new Sentinel-2 acquisition dates and start a
whole-polygon raster for the newest one that passes the cloud criterion
(docs/superpowers/specs/2026-10-09-test-baseline-and-latest-scene-design.md
§7).

Data source: Copernicus Sentinel-2 L2A via Google Earth Engine, reached
only through the bridge -- `bridge.assess_new_scenes`
(data-pipeline/src/scene_assess.py: one cloud decision per UTC acquisition
date over the polygon's water) and `run_raster_scan` (scan.py).

Each poll (hourly by default, RASTER_SCAN_POLL_INTERVAL_HOURS):

  1. assesses every acquisition date since the later of the lookback start
     (RASTER_SCAN_POLL_LOOKBACK_DAYS) and the newest date already used,
     skipping dates whose stored assessment is settled, and stores each
     decision in `scene_assessments` (updated in place);
  2. picks the newest `passed` date newer than the newest used date --
     a newer rejected date never hides it, and a rejected date never
     starts anything (the previous raster keeps being served);
  3. starts `run_raster_scan` for it at once -- the old 20 h cooldown
     (RASTER_SCAN_COOLDOWN_HOURS) no longer applies -- unless an attempt
     started less than RASTER_SCAN_MIN_INTERVAL_HOURS ago;
  4. after an 'ok' scan, refreshes the 7 monitored sites once.

scan.py marks the date used when the run ends 'ok' or 'no_data'
(SCENE_CONSUMING_STATUSES); an errored run leaves it unused, so it is
retried after the minimum interval.

Settling. Earth Engine can ingest one date's granules over several hours,
so an early assessment may describe part of the scene. A stored
assessment is final only once `assessed_at >= date 00:00 UTC + 36 h`
(SETTLE_HOURS); until then the date is re-assessed on every poll and its
row rewritten, so a rejected date can become passed as tiles arrive. A
date already used is never scanned again, even if a later assessment of it
changes -- tiles that arrive after its scan reach the raster only through
a later scan's newest-valid-pixel mosaic.

Limitations: a pass means the water was visible, nothing about blooms
(CLAUDE.md §0 truth boundary). A GEE failure during assessment stores
nothing and starts nothing; it is never read as "no newer scene".
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from .. import _detection as bridge
from .. import _study_area
from .. import shutdown
from ..config import (
    RASTER_SCAN_MIN_INTERVAL_HOURS,
    RASTER_SCAN_POLL_LOOKBACK_DAYS,
    RASTER_SCAN_SCALE_M,
    as_aware_utc,
    today_str,
)
from ..db import SessionLocal
from ..db_models import RasterScanRun, SceneAssessmentRow
from .scan import ConcurrentRasterScanError, run_raster_scan

logger = logging.getLogger("backend.raster_scan.trigger")

PASSED = "passed"

# A date's assessment is final once made at least this long after the date
# began (UTC): i.e. from noon of the following day, well after every granule
# of that day has normally been ingested.
SETTLE_HOURS = 36


def should_trigger_scan(
    last_attempt_started_at: datetime | None,
    last_trigger_scene_timestamp: str | None,
    newest_scene_timestamp: str | None,
    cooldown_hours: int,
    now: datetime,
) -> bool:
    """Require both a new candidate acquisition and an elapsed cooldown.

    Superseded by the latest-scene policy and no longer called by
    poll_and_maybe_scan; kept for backwards compatibility.
    """
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


def _starts_cooldown(row: RasterScanRun) -> bool:
    """Whether this run counts as an attempt for the minimum interval.

    A bootstrap stopped by shutdown was cut short by the process, not by
    the data or its budget, so it must not delay the next poll. A
    budget-stopped bootstrap did spend its budget and still counts, as
    does every other attempt, whatever its status.
    """
    metadata = row.source_metadata
    return not (isinstance(metadata, dict) and metadata.get("search_stopped") == "shutdown")


def is_settled(acquisition_date: str, assessed_at: datetime) -> bool:
    """Whether an assessment made at `assessed_at` is final for its date
    (`assessed_at >= acquisition_date 00:00 UTC + SETTLE_HOURS`). A naive
    `assessed_at` (SQLite) is UTC."""
    day_start = datetime.strptime(acquisition_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return as_aware_utc(assessed_at) >= day_start + timedelta(hours=SETTLE_HOURS)


def trigger_timestamp_for(acquisition_date: str) -> str:
    """The `trigger_scene_timestamp` recorded for a scan of this date.
    scan.py reads its "YYYY-MM-DD" prefix to mark the date used."""
    return f"{acquisition_date}T00:00:00+00:00"


def _store(
    db, by_date: dict[str, SceneAssessmentRow], assessments, now: datetime,
) -> None:
    """Insert or rewrite one row per assessed date; `used_in_run_id` is
    never touched here."""
    for assessment in assessments:
        row = by_date.get(assessment.acquisition_date)
        if row is None:
            row = SceneAssessmentRow(acquisition_date=assessment.acquisition_date)
            db.add(row)
            by_date[assessment.acquisition_date] = row
        row.cloud_fraction = assessment.cloud_fraction
        row.water_pixels = assessment.water_pixels
        row.decision = assessment.decision
        row.reason = assessment.reason
        row.assessed_at = now
    db.commit()


def refresh_sites_after_scan() -> None:
    """Refresh the 7 monitored sites once after a scan that used a new
    scene, so sites and raster describe the same acquisition. Never
    raises; skipped when shutdown has been requested."""
    if shutdown.stop_requested():
        logger.info("raster_scan poll: shutdown requested; sites refresh skipped")
        return
    try:
        # Imported here: scheduler imports this module at load time.
        from .. import scheduler

        scheduler.refresh_grid()
    except Exception as exc:  # noqa: BLE001 -- the scan already succeeded
        logger.error(
            "raster_scan poll: sites refresh after scan failed: %s: %s",
            type(exc).__name__,
            exc,
        )


def poll_and_maybe_scan(now: datetime | None = None) -> None:
    """Scheduled poll; failures are logged and never crash the scheduler.

    `now` is injectable for tests; the scheduler calls this with none.
    """
    if shutdown.stop_requested():
        logger.info("raster_scan poll: shutdown requested; not polling")
        return
    now = now or datetime.now(timezone.utc)
    scanned_ok = False
    with SessionLocal() as db:
        try:
            by_date = {
                row.acquisition_date: row
                for row in db.execute(select(SceneAssessmentRow)).scalars()
            }
            used_dates = [d for d, row in by_date.items() if row.used_in_run_id is not None]
            newest_used = max(used_dates) if used_dates else None
            settled = frozenset(
                d for d, row in by_date.items() if is_settled(d, row.assessed_at)
            )
            since = (now - timedelta(days=RASTER_SCAN_POLL_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
            if newest_used is not None and newest_used > since:
                since = newest_used

            try:
                assessments = bridge.assess_new_scenes(
                    _study_area.STUDY_AREA_POLYGON_LATLNG,
                    since,
                    scale_m=RASTER_SCAN_SCALE_M,
                    skip_dates=settled,
                )
            except bridge.GEEAuthError as exc:
                logger.error("raster_scan poll: authentication failed; skipping: %s", exc)
                return
            except Exception as exc:  # noqa: BLE001 -- nothing stored, nothing started
                logger.warning(
                    "raster_scan poll: scene assessment failed; no date assessed, no "
                    "scan started (this is not a finding that no newer scene exists): "
                    "%s: %s",
                    type(exc).__name__,
                    exc,
                )
                return
            _store(db, by_date, assessments, now)
            for assessment in assessments:
                logger.info(
                    "raster_scan poll: %s assessed %s (cloud=%s, water_pixels=%s)%s",
                    assessment.acquisition_date,
                    assessment.decision,
                    assessment.cloud_fraction,
                    assessment.water_pixels,
                    f": {assessment.reason}" if assessment.reason else "",
                )

            if shutdown.stop_requested():
                logger.info("raster_scan poll: shutdown requested; assessed, not scanning")
                return

            candidate = max(
                (
                    d for d, row in by_date.items()
                    if row.decision == PASSED and (newest_used is None or d > newest_used)
                ),
                default=None,
            )
            if candidate is None:
                logger.info(
                    "raster_scan poll: no passing date newer than the newest used "
                    "(%s); previous raster keeps serving",
                    newest_used,
                )
                return

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
            if latest_attempt is not None and (
                now - as_aware_utc(latest_attempt.started_at)
                < timedelta(hours=RASTER_SCAN_MIN_INTERVAL_HOURS)
            ):
                logger.info(
                    "raster_scan poll: %s passed but run %s started less than %s h ago; "
                    "waiting for the minimum interval",
                    candidate,
                    latest_attempt.id,
                    RASTER_SCAN_MIN_INTERVAL_HOURS,
                )
                return

            logger.info("raster_scan poll: triggering for passing date %s", candidate)
            try:
                run = run_raster_scan(
                    db,
                    today_str(),
                    trigger_scene_timestamp=trigger_timestamp_for(candidate),
                )
            except ConcurrentRasterScanError as exc:
                logger.info("raster_scan poll: %s", exc)
                return
            scanned_ok = run.status == "ok"
        except Exception as exc:  # noqa: BLE001 -- scheduler-job boundary
            logger.error(
                "raster_scan poll: unexpected failure: %s: %s",
                type(exc).__name__,
                exc,
            )
            return
    if scanned_ok:
        refresh_sites_after_scan()
