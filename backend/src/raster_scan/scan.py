"""
Raster scan orchestration: run_raster_scan() builds one whole-polygon
Sentinel-2 spectral-index composite (data-pipeline/src/raster.py, reached
through backend/src/_detection.py), downloads it at the configured scale,
writes the cells to disk (src/raster_scan/storage.py), records the run, and
draws its map overlay from the stored cells (src/raster_scan/render.py).

The fixed 7-site grid (src/grid.py), the scheduler's DetectionCache
refresh and /risk-map remain a separate named-station product. This is an area read of
the same Sentinel-2 data, with the same truth boundary (CLAUDE.md §0):
index readings at pixel resolution, no anomaly score, no verdict, and a
200 m cell is one nearest-neighbour sampled 10 m pixel, so a smaller
bloom can fall between sampled pixels and be missed.

Only one raster scan may run at a time. Two concurrent runs would each
fetch and store a full raster, and a full read is
a single multi-megabyte GEE transfer -- so the second call is refused
(ConcurrentRasterScanError) before it writes a row or a byte.

GEEAuthError aborts the run (status='error') without touching any blob or
row a prior successful run wrote -- it means the whole pipeline is
unusable, not that this raster is unavailable, and an aborted run must
never discard the last known-good raster. "No usable imagery" and "every
cell masked" are the opposite case: real, honest answers about the world,
recorded as status='no_data' with the reason, never as an error and never
as an empty raster that reads like a real one.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import _detection as bridge
from .. import _study_area
from ..config import RASTER_RETENTION_DAYS, RASTER_SCAN_SCALE_M, as_aware_utc
from ..db_models import RasterScanRun
from . import render, storage

logger = logging.getLogger("backend.raster_scan.scan")

# How long a run left in status='running' is believed before a new scan
# treats it as dead and proceeds. Not an env var, because it is not a
# policy choice: it is derived from how long the work takes. One raster
# is one composite plus one transfer -- measured live at ~10 s for the
# 200 m read (9.2 MB) and correspondingly longer for the 36.8 MB 100 m
# one -- so an hour is two orders of magnitude past the longest
# legitimate run, and anything still 'running' after it had its process
# killed.
STALE_RUN_HOURS = 1


class ConcurrentRasterScanError(RuntimeError):
    """Another raster scan is already in progress, so this one refused to
    start.

    Not a failure of the running scan and not a data error -- the caller
    should wait for the live run rather than retry. Raised before any row
    is written or any byte transferred, so a refused call leaves both the
    database and the blob directory untouched.
    """


def _refuse_if_a_raster_scan_is_already_running(db: Session, now: datetime) -> None:
    """Guard against concurrent runs; expire a run that is stuck.

    A run still marked 'running' after STALE_RUN_HOURS is presumed dead
    (its process was killed, or the host restarted mid-transfer) and is
    marked 'error' so it stops blocking every future scan. Anything
    younger is treated as genuinely live and this raises.
    """
    # Every 'running' row, not just the newest: with allow_concurrent a
    # ghost can end up behind a newer row, and a query that only ever
    # inspects the newest would leave it 'running' forever, invisible to
    # any future cleanup.
    running = db.execute(
        select(RasterScanRun)
        .where(RasterScanRun.status == "running")
        .order_by(RasterScanRun.started_at.desc())
    ).scalars().all()

    expired = False
    for row in running:
        age_hours = (now - as_aware_utc(row.started_at)).total_seconds() / 3600
        if age_hours < STALE_RUN_HOURS:
            raise ConcurrentRasterScanError(
                f"raster scan {row.id} has been running for {age_hours:.2f}h "
                f"(scale {row.scale_m} m, started {row.started_at}). "
                "Two runs would each pull a full multi-megabyte raster. Wait for it "
                "to finish, or pass allow_concurrent=True if you are certain it is dead."
            )
        logger.warning(
            "raster_scan: run %s still 'running' after %.2fh (> %dh) -- presuming it "
            "died and marking it error so this scan can proceed",
            row.id, age_hours, STALE_RUN_HOURS,
        )
        row.status = "error"
        row.completed_at = now
        expired = True

    if expired:
        db.commit()


def _scene_date(epoch_ms: int) -> str:
    """"YYYY-MM-DD" (UTC) of one acquisition timestamp."""
    return datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


# Exact for int64 epoch milliseconds, which is what the date band is
# stored as (storage.write_cells refuses anything narrower).
MS_PER_DAY = 86_400_000


def _scene_date_shares(dates_ms) -> list[dict]:
    """Per-acquisition-day census of the cells this raster actually kept.

    `oldest_scene_date`/`newest_scene_date` state the *span*; this states
    the distribution inside it, which a span structurally cannot. A
    raster whose cells are 61% from one pass and a raster spread evenly
    over ten days have exactly the same span, and a reader shown only the
    span will read the second one. Measured on the live 2026-09-08 run,
    the picture is the first kind -- so the breakdown is data the viewer
    needs, not a nicety.

    Days, not scenes. Several Sentinel-2 tiles, and both orbits, can land
    on one calendar day, so this list is never longer than `scene_count`
    and the two must never be presented as the same number.

    Grouped by integer UTC day (floor division of the stored epoch
    millisecond, exact in int64) rather than by a formatted string, so
    the census is computed on the timestamps themselves.

    Ordered by cell count descending, then date descending. The dominant
    acquisition is the fact the span hides, so it is stated first.

    Returns:
        [{"date": "YYYY-MM-DD", "cells": int, "share": float}, ...] --
        `share` is a fraction of this run's kept cells, so the shares sum
        to 1.0 up to float rounding. `[]` for an empty raster: a run that
        kept nothing gets no day, never a fabricated one.
    """
    dates = np.asarray(dates_ms)
    if dates.size == 0:
        return []
    days, counts = np.unique(dates.astype(np.int64) // MS_PER_DAY, return_counts=True)
    total = int(dates.size)
    shares = [
        {
            "date": _scene_date(int(day) * MS_PER_DAY),
            "cells": int(count),
            "share": int(count) / total,
        }
        for day, count in zip(days, counts)
    ]
    shares.sort(key=lambda share: (share["cells"], share["date"]), reverse=True)
    return shares


def run_raster_scan(
    db: Session,
    target_date: str,
    scale_m: int | None = None,
    retention_days: int | None = None,
    allow_concurrent: bool = False,
    trigger_scene_timestamp: str | None = None,
) -> RasterScanRun:
    """Run one raster scan over the study polygon and persist its results.

    Args:
        db: an open SQLAlchemy session (caller owns commit/close beyond
            this function's own commits).
        target_date: "YYYY-MM-DD", read as "as of this day" -- the same
            meaning it has everywhere else in this project. Which scenes
            answer for it is the one system-wide rule in data-pipeline
            (SENTINEL2_MAX_SCENE_AGE_DAYS), never a per-caller argument.
        scale_m: read scale in metres (RASTER_SCAN_SCALE_M by default).
        retention_days: recorded on the run so an old row states the
            policy that was in force when it was taken, rather than
            being read back under whatever the setting happens to be
            later.
        allow_concurrent: skip the one-scan-at-a-time guard. Only for a
            caller that knows the other run is dead.
        trigger_scene_timestamp: full acquisition timestamp returned by
            the metadata poll that caused this run. Stored even when the
            candidate yields no retained cells.

    Returns:
        The persisted RasterScanRun row (status='ok', 'no_data' or
        'error').

    Raises:
        ConcurrentRasterScanError: another raster scan is running and
            `allow_concurrent` is False. Nothing is written.
    """
    # Read config at call time, not at import: a module-level default
    # parameter binds once, so a later change to config (a test's
    # monkeypatch, a reload path) would be silently ignored by every
    # caller that omitted the argument.
    scale_m = RASTER_SCAN_SCALE_M if scale_m is None else scale_m
    retention_days = RASTER_RETENTION_DAYS if retention_days is None else retention_days

    now = datetime.now(timezone.utc)
    if not allow_concurrent:
        _refuse_if_a_raster_scan_is_already_running(db, now)

    run = RasterScanRun(
        started_at=datetime.now(timezone.utc),
        status="running",
        date_used=target_date,
        scale_m=scale_m,
        retention_days=retention_days,
        trigger_scene_timestamp=trigger_scene_timestamp,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    # The guard above is a SELECT and this is an INSERT -- two statements,
    # so two callers can both pass the check before either row exists.
    # Re-checking afterwards closes that window: the row is now visible to
    # everyone, so whichever run inserted later sees the earlier one and
    # stands down. Cheap, and it needs no lock or unique index (a partial
    # index on status='running' would also forbid allow_concurrent).
    if not allow_concurrent:
        earlier = db.execute(
            select(RasterScanRun)
            .where(RasterScanRun.status == "running", RasterScanRun.id != run.id)
            .order_by(RasterScanRun.id)
        ).scalars().first()
        if earlier is not None:
            _finish(db, run, "error", f"stood down: raster scan {earlier.id} started first")
            raise ConcurrentRasterScanError(
                f"raster scan {earlier.id} started concurrently and won the race; "
                f"run {run.id} stood down without transferring anything."
            )

    logger.info(
        "raster_scan: run %s started -- target=%s scale_m=%s", run.id, target_date, scale_m
    )

    try:
        composite = bridge.build_index_composite(
            _study_area.STUDY_AREA_POLYGON_LATLNG, target_date
        )
        arrays = bridge.download_composite_arrays(composite, scale_m=scale_m)
        # Inside the try, deliberately: a disk error here (directory
        # full, permission denied, an interrupted write) must end the
        # run as 'error' like any other failure. Outside it, the
        # exception escaped run_raster_scan entirely and left the row
        # stuck in 'running' with no completed_at -- which _finish
        # exists to make impossible, and which the concurrency guard
        # then reads as a live run blocking every later scan until the
        # stale window expires. The generic handler below catches OSError.
        written = storage.write_cells(run.id, arrays)
        summary = bridge.summarize_raster_cells(arrays)
    except bridge.GEEAuthError as exc:
        # Deliberately does NOT touch any prior run's row or blob -- an
        # aborted run must never discard the last known-good raster.
        # db.rollback() discards this run's pending work; because rollback
        # expires session objects, `run` is refreshed before its fields
        # are set.
        db.rollback()
        db.refresh(run)
        return _finish(db, run, "error", f"GEEAuthError: {exc}")
    except (bridge.NoCloudFreeImageryError, bridge.NoWaterPixelsError) as exc:
        # Real answers about the world, not failures: no Sentinel-2 scene
        # covered the polygon in the window, or every cell was cloud or
        # land. Recorded as such, with no blob and no fabricated raster.
        db.rollback()
        db.refresh(run)
        return _finish(db, run, "no_data", f"{type(exc).__name__}: {exc}")
    except Exception as exc:  # noqa: BLE001 -- one run, one failure; recorded, not swallowed
        # Includes FabricatedDateError/DateBandPrecisionError: a raster
        # whose cell dates cannot be trusted is refused upstream and
        # never reaches storage, so there is nothing to clean up here.
        logger.error(
            "raster_scan: run %s failed: %s: %s", run.id, type(exc).__name__, exc
        )
        db.rollback()
        db.refresh(run)
        return _finish(db, run, "error", f"{type(exc).__name__}: {exc}")

    dates = arrays[bridge.RASTER_DATE_BAND]

    run.scene_count = len(composite["scene_timestamps_ms"])
    # From the cells that were actually kept, not from every scene in the
    # window: a scene can be in the window and contribute no surviving
    # pixel at all (wholly cloudy over this polygon), and claiming its
    # date as part of this raster's span would overstate what was read.
    run.oldest_scene_date = _scene_date(int(dates.min()))
    run.newest_scene_date = _scene_date(int(dates.max()))
    # Computed from the same kept cells, and for the same reason: the
    # span alone would let one dominant pass pass for ten days of
    # coverage. See _scene_date_shares.
    run.scene_dates = _scene_date_shares(dates)
    run.cell_count = written["cell_count"]
    run.blob_path = written["path"]
    run.blob_bytes = written["bytes"]
    # Written now, not at expiry -- see RasterScanRun's docstring for why
    # the summary must not depend on the blob still being readable a
    # month later.
    run.summary = summary
    finished = _finish(db, run, "ok", None)
    # After the run is committed, never before: the cells are the result,
    # the overlay is a picture of them. A failed render must not be able
    # to cost a good raster its row.
    _render_overlay(db, finished)
    logger.info(
        "raster_scan: run %s done -- cells=%d scenes=%d span=%s..%s blob=%s (%.1f MB)",
        run.id, run.cell_count, run.scene_count, run.oldest_scene_date,
        run.newest_scene_date, run.blob_path, written["bytes"] / 1e6,
    )
    return finished


def _render_overlay(db: Session, run: RasterScanRun) -> None:
    """Draw the run's map overlay from the cells just stored, and record
    where it went (src/raster_scan/render.py).

    Reads the blob back off disk rather than rendering the arrays still
    in memory: the picture must be of what was actually stored, so a
    write that silently lost or altered a cell shows up here instead of
    being papered over by an overlay drawn from a better copy.

    A render failure is recorded on the row, not raised and not swallowed.
    The scan itself has already succeeded and committed by this point --
    the cells are safe on disk and are the product; the overlay is a
    derived picture of them, and losing it is a smaller thing than losing
    the raster. `overlay = {"status": "error", ...}` keeps that
    distinguishable from a run that was never rendered (null) and from
    one whose overlay retention removed along with the cells (also null,
    but with blob_deleted_at set).
    """
    try:
        render.render_and_store(db, run)
    except Exception as exc:  # noqa: BLE001 -- recorded on the row, see above
        logger.error(
            "raster_scan: run %s stored %s cells but its overlay failed to render: "
            "%s: %s", run.id, run.cell_count, type(exc).__name__, exc
        )
        db.rollback()
        db.refresh(run)
        run.overlay = {
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
            "attempted_at": datetime.now(timezone.utc).isoformat(),
        }
        db.commit()


def _finish(db: Session, run: RasterScanRun, status: str, reason: str | None) -> RasterScanRun:
    """Close out a run row: status, completion time, reason. One place,
    so every exit path stamps `completed_at` and none can leave a row
    stuck in 'running' and blocking the next scan."""
    run.status = status
    run.reason = reason
    run.completed_at = datetime.now(timezone.utc)
    db.commit()
    if status != "ok":
        logger.warning("raster_scan: run %s ended status=%s reason=%s", run.id, status, reason)
    return run
