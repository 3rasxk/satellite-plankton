"""
On-disk storage and retention for raster scans.

The cells of one whole-polygon raster (~50,000 of them at the 200 m
default, ~196,000 at 100 m, each carrying four index readings, a
coordinate pair and its own acquisition timestamp) do not belong in a
database column: they are read as a block, never queried field by field,
and a single blob column would put tens of megabytes of float arrays
through SQLAlchemy on every touch. So the arrays go to one compressed
`.npz` file per run under `backend/data/rasters/<run_id>/`, and the
`RasterScanRun` row holds the metadata plus the path.

`backend/data/` is gitignored (repo-root `.gitignore` carries
`backend/data/`, the same line that keeps the SQLite stand-in DB out of
the repository) -- verified by
`backend/tests/test_raster_scan_storage.py`, not just assumed here.

Retention: full rasters are kept for `RASTER_RETENTION_DAYS` (default 30).
Past that, the run is *reduced*, not deleted -- its `summary` row (written
when the scan completed) stays, and the blob goes, taking the rendered
overlay PNGs with it: those are drawn from the cells
(`src/raster_scan/render.py`), so once the cells are gone the picture can
never be redrawn or checked against its source. What survives is
a whole-raster reduction computed with data-pipeline's own aggregation
policy, `RASTER_BAND_REDUCERS`: mean for the four index bands, and mode
-- never mean -- for the acquisition date, because the average of two
acquisition timestamps names a pass no satellite flew.

Nothing here writes into the pin path. `DetectionCache` and its
pre-rendered PNGs (the 7-site monitored grid) are untouched by this
module; retention here only ever removes files under this module's own
`backend/data/rasters/` root.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import _detection as bridge
from ..config import RASTER_RETENTION_DAYS, as_aware_utc
from ..db_models import RasterScanRun

logger = logging.getLogger("backend.raster_scan.storage")

_BACKEND_DIR = Path(__file__).resolve().parents[2]

# Sibling of backend/data/app.db, under the same gitignored directory.
RASTER_BLOB_ROOT = _BACKEND_DIR / "data" / "rasters"

# One file per run. Fixed name: the run id is already the directory, so
# the filename carries no information and does not need to.
BLOB_FILENAME = "cells.npz"

# Arrays actually written to disk, in this order. `lat`/`lng` come from
# GEE's own pixelLonLat bands (data-pipeline/src/raster.py), so a stored
# cell's position is the position the server computed it at.
STORED_ARRAYS: tuple[str, ...] = ("lat", "lng", *bridge.RASTER_BAND_ORDER)


def run_blob_dir(run_id: int, root: Path | None = None) -> Path:
    """Directory holding one run's raster. One directory per run so a
    later addition (a second array file, a provenance sidecar) has
    somewhere to go without renaming what is already stored."""
    # int() before it touches a path: nothing exposes run_id to user
    # input today, but a future router taking it as a param would
    # otherwise hand this function a traversal string.
    return (root or RASTER_BLOB_ROOT) / str(int(run_id))


def run_blob_path(run_id: int, root: Path | None = None) -> Path:
    """Full path of one run's raster file."""
    return run_blob_dir(run_id, root) / BLOB_FILENAME


def write_cells(run_id: int, arrays: dict, root: Path | None = None) -> dict:
    """Write one run's cells to disk.

    dtypes are preserved exactly as `np.savez_compressed` stores them,
    which is the whole reason the date band is written as int64 rather
    than being folded into a single float array with the indices: epoch
    milliseconds (~1.79e12) need 13 significant digits and float32 carries
    about 7 (its spacing there is 131,072 ms), so sharing a float32 array
    with the indices would move every stored timestamp by up to ~65 s --
    silently, since the result still looks like a date, and far enough
    that it no longer equals the acquisition it names. `read_cells`
    asserts the dtype on the way back.

    Args:
        run_id: the RasterScanRun this raster belongs to.
        arrays: `download_composite_arrays`' return value. Only the keys
            in `STORED_ARRAYS` are written; its scalar metadata
            (`scale_m`, `cell_count`, ...) lives on the DB row instead of
            being duplicated into the file.
        root: blob root override (tests point this at tmp_path).

    Returns:
        {"path": str, "bytes": int, "cell_count": int}

    Raises:
        ValueError: the date array is not int64 -- refused rather than
            written, because a narrowed timestamp cannot be recovered
            once stored.
    """
    date_band = bridge.RASTER_DATE_BAND
    dates = np.asarray(arrays[date_band])
    if dates.dtype != np.int64:
        raise ValueError(
            f"refusing to store {date_band} as {dates.dtype}: epoch milliseconds "
            "need int64 (or an exact float64), and a narrower type silently shifts "
            "every acquisition date far enough that it stops matching its scene."
        )

    directory = run_blob_dir(run_id, root)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / BLOB_FILENAME
    np.savez_compressed(path, **{name: np.asarray(arrays[name]) for name in STORED_ARRAYS})

    size = path.stat().st_size
    logger.info(
        "raster_scan: run %s wrote %d cells to %s (%.1f MB)",
        run_id, len(dates), path, size / 1e6,
    )
    return {"path": str(path), "bytes": int(size), "cell_count": int(len(dates))}


def read_cells(path: str | Path) -> dict:
    """Read a stored raster back as numpy arrays.

    Raises:
        FileNotFoundError: the blob is gone -- expired by retention, or
            removed by something else. Either way the caller is told,
            never handed an empty raster that looks like a real one.
        ValueError: the stored date band is not int64 (see `write_cells`).
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"raster blob {path} does not exist. An expired run keeps its summary "
            "row but not its cells -- check RasterScanRun.blob_deleted_at."
        )
    with np.load(path) as data:
        arrays = {name: data[name] for name in data.files}

    date_band = bridge.RASTER_DATE_BAND
    if arrays[date_band].dtype != np.int64:
        raise ValueError(
            f"stored {date_band} has dtype {arrays[date_band].dtype}, not int64 -- "
            "the acquisition dates in this blob cannot be trusted."
        )
    return arrays


def delete_blob_file(path: str | Path) -> bool:
    """Remove one recorded blob file, and its run directory if that
    leaves it empty. Returns whether the file existed.

    Deliberately unlinks a single file rather than removing a tree: the
    path comes from a database row, and a wrong or corrupted row should
    cost at most that one file, never a directory of them.

    Idempotent -- deleting an already-deleted blob is not an error, so a
    retention pass that is interrupted and re-run does the right thing.
    """
    blob = Path(path)
    existed = blob.exists()
    if existed:
        blob.unlink()
    parent = blob.parent
    if parent.exists() and not any(parent.iterdir()):
        parent.rmdir()
    return existed


def delete_overlay_assets(run: RasterScanRun) -> list[str]:
    """Remove the rendered PNGs and sidecar one run recorded, if any.

    The overlay is drawn from the cells (`src/raster_scan/render.py`), so
    it cannot outlive them: once the blob is gone the image can never be
    redrawn or checked against its source, and an unredrawable picture of
    a raster nobody can re-read is exactly the kind of orphan this
    project's retention exists to avoid. Keeping it would also leave
    files in the run directory forever, since `delete_blob_file` only
    removes the directory when it is empty.

    Reads `run.overlay["files"]` -- a flat list render.py maintains for
    this one purpose, so retention never has to know the structure of the
    rest of that metadata. Returns the paths removed.
    """
    overlay = run.overlay or {}
    removed = [path for path in overlay.get("files", []) if delete_blob_file(path)]
    return removed


def delete_run_blob(run_id: int, root: Path | None = None) -> bool:
    """Remove one run's blob by id -- for a caller holding the run id
    rather than the stored path (manual cleanup, tests). Retention itself
    deletes the path recorded on the row, which is authoritative if the
    two ever disagree (a moved RASTER_BLOB_ROOT, say)."""
    return delete_blob_file(run_blob_path(run_id, root))


def apply_retention(
    db: Session,
    now: datetime | None = None,
    retention_days: int | None = None,
    root: Path | None = None,
) -> dict:
    """Reduce every run older than the cutoff to its summary.

    "Older than" is measured on `completed_at` -- when the raster was
    actually taken -- not on when the row was created or last touched.

    A reduced run keeps: its row, all its metadata, and its `summary`
    (written at scan time, see `run_raster_scan`). It loses the cells and
    the overlay drawn from them. `blob_path` and `overlay` are nulled and
    `blob_deleted_at` set, so "expired" is a stated fact on the row rather
    than something inferred from a missing file.

    A run whose summary is missing is NOT expired: it is left alone and
    logged. Deleting the last copy of a raster that was never reduced
    would lose the run's findings entirely, and a run in that state is a
    bug to fix, not data to discard.

    Args:
        db: open session; this function commits its own work.
        now: comparison instant (defaults to real UTC now).
        retention_days: window override; defaults to RASTER_RETENTION_DAYS.
        root: blob root override (tests point this at tmp_path).

    Returns:
        {"expired": [run_id, ...], "kept": int, "skipped_no_summary": [run_id, ...]}
    """
    now = now or datetime.now(timezone.utc)
    # Resolved here, not as a default parameter: a module-level default
    # binds once at import and would ignore any later config change.
    retention_days = RASTER_RETENTION_DAYS if retention_days is None else retention_days
    cutoff = now - timedelta(days=retention_days)

    candidates = db.execute(
        select(RasterScanRun).where(RasterScanRun.blob_path.is_not(None))
    ).scalars().all()

    expired: list[int] = []
    skipped: list[int] = []
    kept = 0
    for run in candidates:
        completed = as_aware_utc(run.completed_at)
        if completed is None or completed >= cutoff:
            # Still inside the window, or still running -- untouched.
            kept += 1
            continue
        if not run.summary:
            skipped.append(run.id)
            logger.warning(
                "raster_scan: run %s is past retention but has no summary -- keeping "
                "its blob rather than losing the run entirely",
                run.id,
            )
            continue

        # The path the row records, not one reconstructed from the run id
        # and the current root: if RASTER_BLOB_ROOT has moved since the
        # scan, reconstructing would delete nothing while still nulling
        # the row, leaking the old file with no record it ever existed.
        # The rendered overlay goes with the cells it was drawn from --
        # see delete_overlay_assets. Removed before the blob so an
        # interrupted pass never leaves a row advertising PNGs whose
        # source raster is already gone.
        delete_overlay_assets(run)
        run.overlay = None
        delete_blob_file(run.blob_path)
        run.blob_path = None
        run.blob_bytes = None
        run.blob_deleted_at = now
        expired.append(run.id)

    if expired:
        db.commit()
        logger.info(
            "raster_scan: retention reduced %d run(s) to summary (older than %s): %s",
            len(expired), cutoff.isoformat(), expired,
        )
    return {"expired": expired, "kept": kept, "skipped_no_summary": skipped}
