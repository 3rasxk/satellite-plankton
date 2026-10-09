"""Latest-scene policy: assess new Sentinel-2 acquisition dates and start a
whole-polygon raster for the newest one that passes the cloud criterion
(docs/superpowers/specs/2026-10-09-test-baseline-and-latest-scene-design.md
§7).

Data source: Copernicus Sentinel-2 L2A via Google Earth Engine, reached
only through the bridge -- `bridge.assess_new_scenes`
(data-pipeline/src/scene_assess.py: one cloud decision per UTC acquisition
date over the polygon's water) and `run_raster_scan` (scan.py).

Each poll (hourly by default, RASTER_SCAN_POLL_INTERVAL_HOURS):

  1. assesses every acquisition date since `since` = the later of the
     lookback start (RASTER_SCAN_POLL_LOOKBACK_DAYS) and the newest date
     already used, skipping dates in that window whose stored assessment
     is settled, and stores each decision in `scene_assessments` (updated
     in place). Only rows from `since` on are read, plus one MAX query for
     the newest used date;
  2. picks the newest `passed` date newer than the newest used date --
     a newer rejected date never hides it, and a rejected date never
     starts anything (the previous raster keeps being served);
  3. starts `run_raster_scan` for it at once -- the old 20 h cooldown no
     longer applies to it -- unless an attempt started less than
     RASTER_SCAN_MIN_INTERVAL_HOURS ago. The run's trigger_scene_timestamp
     is a date-only marker, "<date>T00:00:00+00:00" (the time is
     synthetic, not an acquisition time);
  4. first-install fallback: if no date qualifies AND no raster scan has
     ever finished 'ok' (scan.has_successful_run, the same test scan.py
     uses to choose bootstrap mode), starts the bootstrap with no trigger
     scene, at most once per RASTER_SCAN_COOLDOWN_HOURS since the latest
     counted attempt. Once any date passes, step 3 takes over;
  5. after an 'ok' scan, refreshes the 7 monitored sites once, so they are
     refreshed after the same new acquisition became available.

scan.py marks the date used when the run ends 'no_data', or 'ok' with kept
cells reaching that date; an errored run leaves it unused, so it is
retried after the minimum interval.

Settling. Earth Engine can ingest one date's granules over several hours,
so an early assessment may describe part of the scene. A stored
assessment is final only once `assessed_at >= date 00:00 UTC + 36 h`
(SETTLE_HOURS); until then the date is re-assessed on every poll and its
row rewritten, so a rejected date can become passed as tiles arrive. A
date already used is never scanned again, even if a later assessment of it
changes -- tiles that arrive after its scan reach the raster only through
a later scan's newest-valid-pixel mosaic. Unsettled dates older than the
newest used date are never re-assessed (they lie before `since`).

Failure honesty: every poll that gets past the shutdown check records its
start, a completed assessment call, or its failure and kind in the single
`scene_poll_status` row (own short transactions, never raising), so a
reader can tell "no newer usable scene" from "the poll could not reach
GEE". A GEE failure during assessment stores no assessment and starts
nothing; it is never read as "no newer scene".

Limitations: a pass means the water was visible, nothing about blooms
(CLAUDE.md §0 truth boundary).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from .. import _detection as bridge
from .. import _study_area
from .. import shutdown
from ..config import (
    RASTER_SCAN_COOLDOWN_HOURS,
    RASTER_SCAN_MIN_INTERVAL_HOURS,
    RASTER_SCAN_POLL_LOOKBACK_DAYS,
    RASTER_SCAN_SCALE_M,
    as_aware_utc,
    today_str,
)
from ..db import SessionLocal
from ..db_models import RasterScanRun, SceneAssessmentRow, ScenePollStatus
from .scan import ConcurrentRasterScanError, has_successful_run, run_raster_scan

logger = logging.getLogger("backend.raster_scan.trigger")

PASSED = "passed"

# A date's assessment is final once made at least this long after the date
# began (UTC): i.e. from noon of the following day, well after every granule
# of that day has normally been ingested.
SETTLE_HOURS = 36

# The single scene_poll_status row.
POLL_STATUS_ID = 1


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
    """Whether this run counts as an attempt for the minimum interval and
    for the first-install bootstrap cooldown.

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
    """The `trigger_scene_timestamp` recorded for a scan of this date: a
    date-only marker whose time part is synthetic. scan.py reads its
    "YYYY-MM-DD" prefix to mark the date used."""
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


def _record_poll_status(**fields) -> None:
    """Set `fields` on the single scene_poll_status row, in its own short
    transaction (never the poll's session). Never raises: a status that
    cannot be written is logged, and the poll carries on."""
    try:
        with SessionLocal() as db:
            row = db.get(ScenePollStatus, POLL_STATUS_ID)
            if row is None:
                row = ScenePollStatus(id=POLL_STATUS_ID)
                db.add(row)
            for key, value in fields.items():
                setattr(row, key, value)
            db.commit()
    except Exception as exc:  # noqa: BLE001 -- status is best-effort
        logger.error(
            "raster_scan poll: could not record poll status: %s: %s",
            type(exc).__name__,
            exc,
        )


def _record_poll_error(kind: str, exc: BaseException, now: datetime) -> None:
    _record_poll_status(
        last_error=f"{type(exc).__name__}: {exc}",
        last_error_at=now,
        last_error_kind=kind,
    )


def _latest_counted_attempt(db) -> RasterScanRun | None:
    """Newest raster scan attempt of any status that `_starts_cooldown`."""
    return next(
        (
            row
            for row in db.execute(
                select(RasterScanRun).order_by(RasterScanRun.started_at.desc())
            ).scalars()
            if _starts_cooldown(row)
        ),
        None,
    )


def _started_within(row: RasterScanRun | None, hours: int, now: datetime) -> bool:
    return row is not None and now - as_aware_utc(row.started_at) < timedelta(hours=hours)


def refresh_sites_after_scan() -> None:
    """Refresh the 7 monitored sites once after a successful scan started
    by the poll, so they are refreshed after the same new acquisition
    became available (each site still resolves its own newest usable
    scene). Never raises; skipped when shutdown has been requested."""
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
    _record_poll_status(last_poll_started_at=now)
    scanned_ok = False
    with SessionLocal() as db:
        try:
            newest_used = db.scalar(
                select(func.max(SceneAssessmentRow.acquisition_date)).where(
                    SceneAssessmentRow.used_in_run_id.is_not(None)
                )
            )
            since = (now - timedelta(days=RASTER_SCAN_POLL_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
            if newest_used is not None and newest_used > since:
                since = newest_used
            by_date = {
                row.acquisition_date: row
                for row in db.execute(
                    select(SceneAssessmentRow).where(SceneAssessmentRow.acquisition_date >= since)
                ).scalars()
            }
            settled = frozenset(
                d for d, row in by_date.items() if is_settled(d, row.assessed_at)
            )

            try:
                assessments = bridge.assess_new_scenes(
                    _study_area.STUDY_AREA_POLYGON_LATLNG,
                    since,
                    scale_m=RASTER_SCAN_SCALE_M,
                    skip_dates=settled,
                )
            except bridge.GEEAuthError as exc:
                logger.error("raster_scan poll: authentication failed; skipping: %s", exc)
                _record_poll_error("gee_auth", exc, now)
                return
            except bridge.GEEConfigError as exc:
                logger.error(
                    "raster_scan poll: scene assessment configuration is invalid; no "
                    "date assessed and no scan started until it is fixed: %s",
                    exc,
                )
                _record_poll_error("gee_config", exc, now)
                return
            except Exception as exc:  # noqa: BLE001 -- nothing stored, nothing started
                logger.warning(
                    "raster_scan poll: scene assessment failed; no date assessed, no "
                    "scan started (this is not a finding that no newer scene exists): "
                    "%s: %s",
                    type(exc).__name__,
                    exc,
                )
                _record_poll_error("assessment_failed", exc, now)
                return
            _record_poll_status(last_poll_ok_at=now)
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
            latest_attempt = _latest_counted_attempt(db)
            if candidate is not None:
                if _started_within(latest_attempt, RASTER_SCAN_MIN_INTERVAL_HOURS, now):
                    logger.info(
                        "raster_scan poll: %s passed but run %s started less than %s h "
                        "ago; waiting for the minimum interval",
                        candidate,
                        latest_attempt.id,
                        RASTER_SCAN_MIN_INTERVAL_HOURS,
                    )
                    return
                trigger = trigger_timestamp_for(candidate)
                logger.info("raster_scan poll: triggering for passing date %s", candidate)
            elif has_successful_run(db):
                logger.info(
                    "raster_scan poll: no passing date newer than the newest used "
                    "(%s); previous raster keeps serving",
                    newest_used,
                )
                return
            else:
                if _started_within(latest_attempt, RASTER_SCAN_COOLDOWN_HOURS, now):
                    logger.info(
                        "raster_scan poll: no raster yet and no passing date; run %s "
                        "started less than %s h ago, so the bootstrap waits",
                        latest_attempt.id,
                        RASTER_SCAN_COOLDOWN_HOURS,
                    )
                    return
                trigger = None
                logger.info(
                    "raster_scan poll: no raster yet and no passing date since %s; "
                    "starting the first-install bootstrap",
                    since,
                )

            try:
                run = run_raster_scan(db, today_str(), trigger_scene_timestamp=trigger)
            except ConcurrentRasterScanError as exc:
                logger.info("raster_scan poll: %s", exc)
                return
            scanned_ok = run.status == "ok"
        except Exception as exc:  # noqa: BLE001 -- scheduler-job boundary
            # Release any write this session holds before the status row
            # is written from another connection.
            db.rollback()
            logger.error(
                "raster_scan poll: unexpected failure: %s: %s",
                type(exc).__name__,
                exc,
            )
            _record_poll_error("unexpected", exc, now)
            return
    if scanned_ok:
        refresh_sites_after_scan()
