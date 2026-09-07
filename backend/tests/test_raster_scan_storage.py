"""Blob storage and retention for raster scans -- real files on a
tmp_path root, real DB rows (isolated SQLite, via the `client` fixture).

No GEE anywhere: every array here is written by the test, so what is
under examination is only what the storage layer does with it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import delete, select

from src import _detection as bridge
from src.db import SessionLocal
from src.db_models import RasterScanRun
from src.raster_scan import storage

# Real Sentinel-2 acquisition times over the upper Gulf, to the
# millisecond -- the values a stored raster actually has to carry.
OLD_MS = 1787628600000  # 2026-08-25T03:30:00Z
NEW_MS = 1788492600000  # 2026-09-04T03:30:00Z

DATE_BAND = bridge.RASTER_DATE_BAND


@pytest.fixture(autouse=True)
def empty_raster_runs(client):
    """One session-wide SQLite file backs the whole suite, so each test
    starts from an empty raster_scan_runs table -- otherwise a retention
    count would depend on which tests ran before it."""
    with SessionLocal() as db:
        db.execute(delete(RasterScanRun))
        db.commit()
    yield


def cells(dates_ms=(OLD_MS, NEW_MS, NEW_MS)):
    """A small raster in `download_composite_arrays`' returned shape."""
    count = len(dates_ms)
    return {
        "lat": np.linspace(13.0, 13.1, count, dtype=np.float64),
        "lng": np.linspace(100.0, 100.1, count, dtype=np.float64),
        "ndci": np.linspace(0.02, 0.09, count, dtype=np.float32),
        "bda2": np.linspace(1.1, 1.5, count, dtype=np.float32),
        "bda3": np.linspace(0.2, 0.4, count, dtype=np.float32),
        "b2_b3": np.linspace(0.7, 0.9, count, dtype=np.float32),
        DATE_BAND: np.array(dates_ms, dtype=np.int64),
    }


def make_run(db, completed_at, blob_path=None, summary=None, status="ok"):
    run = RasterScanRun(
        started_at=completed_at,
        completed_at=completed_at,
        status=status,
        date_used="2026-09-06",
        scale_m=200,
        retention_days=30,
        cell_count=3,
        blob_path=blob_path,
        blob_bytes=None if blob_path is None else Path(blob_path).stat().st_size,
        summary=summary,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


# --------------------------------------------------------------------------
# Where a blob goes, and what the row says about it.
# --------------------------------------------------------------------------


def test_the_blob_lands_under_its_own_run_id(client, tmp_path):
    written = storage.write_cells(42, cells(), root=tmp_path)

    expected = tmp_path / "42" / storage.BLOB_FILENAME
    assert Path(written["path"]) == expected
    assert expected.exists()
    assert storage.run_blob_path(42, tmp_path) == expected
    # The returned metadata is the file, not an estimate of it.
    assert written["bytes"] == expected.stat().st_size
    assert written["cell_count"] == 3


def test_the_metadata_row_matches_the_file_on_disk(client, tmp_path):
    written = storage.write_cells(7, cells(), root=tmp_path)
    with SessionLocal() as db:
        run = make_run(db, datetime.now(timezone.utc), blob_path=written["path"])

        stored = db.get(RasterScanRun, run.id)
        assert stored.blob_path == written["path"]
        assert stored.blob_bytes == Path(written["path"]).stat().st_size
        assert stored.cell_count == written["cell_count"]
        assert stored.blob_deleted_at is None


def test_the_default_blob_root_sits_inside_gitignored_backend_data():
    """Rasters are tens of megabytes of derived data; they must land
    where the SQLite stand-in DB already lives, not somewhere a
    `git add -A` would sweep them up."""
    backend_data = Path(storage._BACKEND_DIR) / "data"
    assert storage.RASTER_BLOB_ROOT.parent == backend_data
    assert storage.RASTER_BLOB_ROOT.name == "rasters"


def test_backend_data_is_gitignored():
    """Verified, not assumed -- the storage module's docstring makes this
    claim, so the claim is checked."""
    gitignore = (Path(storage._BACKEND_DIR).parent / ".gitignore").read_text().splitlines()
    entries = {line.strip() for line in gitignore if line.strip() and not line.startswith("#")}
    assert "backend/data/" in entries


# --------------------------------------------------------------------------
# Round trip: a timestamp comes back as the timestamp that went in.
# --------------------------------------------------------------------------


def test_a_stored_date_reads_back_as_the_exact_source_timestamp(client, tmp_path):
    """ROUND TRIP. Equality to the millisecond, not approximate equality.

    This is the test a float32 narrowing anywhere in the write/read path
    fails: float32's spacing at 1.79e12 is 131,072 ms, so a narrowed
    2026-09-04T03:30:00Z comes back 44,352 ms late -- still a plausible
    date, no longer the acquisition it names.
    """
    source = cells((OLD_MS, NEW_MS, NEW_MS))
    written = storage.write_cells(11, source, root=tmp_path)

    read_back = storage.read_cells(written["path"])

    assert read_back[DATE_BAND].dtype == np.int64
    assert read_back[DATE_BAND].tolist() == [OLD_MS, NEW_MS, NEW_MS]
    assert np.array_equal(read_back[DATE_BAND], source[DATE_BAND])
    # And it is genuinely the hard case: float32 could not have done this.
    assert int(np.float32(NEW_MS)) != NEW_MS
    # The rest of the raster survives too, coordinates included.
    assert np.array_equal(read_back["lat"], source["lat"])
    assert read_back["ndci"].dtype == np.float32


def test_a_narrowed_date_array_is_refused_rather_than_written(client, tmp_path):
    narrowed = cells()
    narrowed[DATE_BAND] = narrowed[DATE_BAND].astype(np.float32)

    with pytest.raises(ValueError, match="float32"):
        storage.write_cells(12, narrowed, root=tmp_path)
    assert not storage.run_blob_dir(12, tmp_path).exists()


def test_reading_an_expired_blob_says_so_instead_of_returning_nothing(client, tmp_path):
    with pytest.raises(FileNotFoundError, match="blob_deleted_at"):
        storage.read_cells(tmp_path / "999" / storage.BLOB_FILENAME)


# --------------------------------------------------------------------------
# Retention: reduce to the summary, keep the row.
# --------------------------------------------------------------------------


def test_retention_deletes_blobs_past_the_cutoff_and_keeps_the_summary(client, tmp_path):
    now = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)
    written = storage.write_cells(101, cells(), root=tmp_path)
    summary = bridge.summarize_raster_cells(cells())

    with SessionLocal() as db:
        run = make_run(db, now - timedelta(days=31), blob_path=written["path"], summary=summary)

        result = storage.apply_retention(db, now=now, retention_days=30, root=tmp_path)

        assert result["expired"] == [run.id]
        assert not Path(written["path"]).exists()
        assert not storage.run_blob_dir(101, tmp_path).exists()

        db.refresh(run)
        # The run is reduced, not deleted: everything except the cells
        # survives, and the row says the blob is gone rather than leaving
        # it to be inferred from a missing file.
        assert run.blob_path is None
        assert run.blob_bytes is None
        assert run.blob_deleted_at is not None
        assert run.status == "ok"
        assert run.cell_count == 3
        assert run.summary == summary
        # And what survives still names the acquisition honestly.
        assert run.summary["bands"][DATE_BAND] == NEW_MS
        assert run.summary["reducers"][DATE_BAND] == "mode"


def test_retention_does_not_touch_anything_inside_the_window(client, tmp_path):
    now = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)
    fresh = storage.write_cells(102, cells(), root=tmp_path)
    # 29 days old under a 30-day policy, and one exactly at the boundary.
    boundary = storage.write_cells(103, cells(), root=tmp_path)

    with SessionLocal() as db:
        young = make_run(db, now - timedelta(days=29), blob_path=fresh["path"], summary={"x": 1})
        edge = make_run(db, now - timedelta(days=30) + timedelta(minutes=1),
                        blob_path=boundary["path"], summary={"x": 1})

        result = storage.apply_retention(db, now=now, retention_days=30, root=tmp_path)

        assert result["expired"] == []
        assert result["kept"] == 2
        assert Path(fresh["path"]).exists()
        assert Path(boundary["path"]).exists()
        db.refresh(young)
        db.refresh(edge)
        assert young.blob_path == fresh["path"] and young.blob_deleted_at is None
        assert edge.blob_path == boundary["path"] and edge.blob_deleted_at is None


def test_a_run_still_in_flight_is_never_expired(client, tmp_path):
    """`completed_at` is null while a scan is running; a null must not be
    read as "infinitely old"."""
    now = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)
    written = storage.write_cells(104, cells(), root=tmp_path)

    with SessionLocal() as db:
        run = RasterScanRun(
            started_at=now - timedelta(days=99), completed_at=None, status="running",
            date_used="2026-09-06", scale_m=200, retention_days=30,
            blob_path=written["path"],
        )
        db.add(run)
        db.commit()

        result = storage.apply_retention(db, now=now, retention_days=30, root=tmp_path)

        assert result["expired"] == []
        assert Path(written["path"]).exists()


def test_a_run_with_no_summary_keeps_its_blob(client, tmp_path):
    """Expiring a run that was never reduced would lose its findings
    entirely, so retention refuses and says which run needs attention."""
    now = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)
    written = storage.write_cells(105, cells(), root=tmp_path)

    with SessionLocal() as db:
        run = make_run(db, now - timedelta(days=60), blob_path=written["path"], summary=None)

        result = storage.apply_retention(db, now=now, retention_days=30, root=tmp_path)

        assert result["expired"] == []
        assert result["skipped_no_summary"] == [run.id]
        assert Path(written["path"]).exists()


def test_retention_is_safe_to_re_run_after_an_interruption(client, tmp_path):
    now = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)
    written = storage.write_cells(106, cells(), root=tmp_path)

    with SessionLocal() as db:
        make_run(db, now - timedelta(days=45), blob_path=written["path"], summary={"x": 1})
        storage.apply_retention(db, now=now, retention_days=30, root=tmp_path)

        # Second pass: the row no longer advertises a blob, so it is not
        # even a candidate, and deleting an already-deleted directory is
        # not an error.
        again = storage.apply_retention(db, now=now, retention_days=30, root=tmp_path)
        assert again["expired"] == []
        assert storage.delete_run_blob(106, tmp_path) is False


def test_retention_only_ever_removes_its_own_runs_blobs(client, tmp_path):
    """A cross-check that the pin path is out of reach: retention deletes
    directories under the raster root by run id and touches nothing
    else."""
    now = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)
    expired = storage.write_cells(107, cells(), root=tmp_path)
    neighbour = tmp_path / "not-a-run"
    neighbour.mkdir()
    (neighbour / "keep.txt").write_text("untouched")

    with SessionLocal() as db:
        make_run(db, now - timedelta(days=90), blob_path=expired["path"], summary={"x": 1})
        storage.apply_retention(db, now=now, retention_days=30, root=tmp_path)

    assert not Path(expired["path"]).exists()
    assert (neighbour / "keep.txt").read_text() == "untouched"


def test_stored_arrays_cover_every_composite_band_plus_coordinates():
    assert storage.STORED_ARRAYS == ("lat", "lng", *bridge.RASTER_BAND_ORDER)
    assert DATE_BAND in storage.STORED_ARRAYS


def test_the_configured_retention_and_scale_defaults_are_the_documented_ones():
    from src import config

    assert config.RASTER_RETENTION_DAYS == 30
    assert config.RASTER_SCAN_SCALE_M == 200


def test_a_stored_run_survives_a_fresh_session(client, tmp_path):
    """The row is real persistence, not session-local state."""
    written = storage.write_cells(108, cells(), root=tmp_path)
    with SessionLocal() as db:
        run_id = make_run(db, datetime.now(timezone.utc), blob_path=written["path"]).id

    with SessionLocal() as db:
        rows = db.execute(
            select(RasterScanRun).where(RasterScanRun.id == run_id)
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].blob_path == written["path"]
