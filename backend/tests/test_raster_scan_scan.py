"""Integration test for run_raster_scan() -- real DB (isolated SQLite, via
the `client` fixture), real files under a tmp_path blob root, and the
composite/download bridge monkeypatched so no live GEE call happens
(mirrors backend/tests/test_regional_scan_scan.py's pattern).

`summarize_raster_cells` is deliberately NOT doubled: it is pure numpy, it
is what an expired run is kept as, and it is where the "the acquisition
date is selected, never averaged" rule is applied -- so it runs for real.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import delete, select

from src.db import SessionLocal
from src.db_models import RasterScanRun
from src.raster_scan import scan as scan_module
from src.raster_scan import storage

OLD_MS = 1787628600000  # 2026-08-25T03:30:00Z
NEW_MS = 1788492600000  # 2026-09-04T03:30:00Z

DATE_BAND = scan_module.bridge.RASTER_DATE_BAND


@pytest.fixture()
def blob_root(tmp_path, monkeypatch, client):
    """Point the storage layer at tmp_path so no test ever writes into
    the real backend/data/rasters, and start from an empty run table --
    one session-wide SQLite file backs the whole suite, so a run left
    'running' by one test would otherwise block the next one."""
    monkeypatch.setattr(storage, "RASTER_BLOB_ROOT", tmp_path)
    with SessionLocal() as db:
        db.execute(delete(RasterScanRun))
        db.commit()
    return tmp_path


def fake_composite(timestamps=(OLD_MS, NEW_MS)):
    return {
        "image": object(),
        "region": object(),
        "scene_ids": tuple(f"S2_{ms}" for ms in timestamps),
        "scene_timestamps_ms": tuple(timestamps),
        "target_date": "2026-09-06",
        "window_start": "2026-08-23",
        "window_end": "2026-09-07",
        "max_scene_age_days": 14,
        "band_order": scan_module.bridge.RASTER_BAND_ORDER,
    }


def fake_arrays(dates_ms=(OLD_MS, NEW_MS, NEW_MS, NEW_MS)):
    count = len(dates_ms)
    return {
        "lat": np.linspace(13.0, 13.1, count, dtype=np.float64),
        "lng": np.linspace(100.0, 100.1, count, dtype=np.float64),
        "ndci": np.linspace(0.02, 0.09, count, dtype=np.float32),
        "bda2": np.linspace(1.1, 1.5, count, dtype=np.float32),
        "bda3": np.linspace(0.2, 0.4, count, dtype=np.float32),
        "b2_b3": np.linspace(0.7, 0.9, count, dtype=np.float32),
        DATE_BAND: np.array(dates_ms, dtype=np.int64),
        "scale_m": 200,
        "cell_count": count,
        "grid_shape": (2, 2),
        "scene_timestamps_ms": tuple(sorted(set(dates_ms))),
    }


def install_raster(monkeypatch, arrays=None, composite=None):
    """Wire the bridge to synthetic data and record what it was asked."""
    calls = {"composite": [], "download": []}

    def build(polygon, date, *args, **kwargs):
        calls["composite"].append((polygon, date, args, kwargs))
        return composite or fake_composite()

    def download(built, *args, **kwargs):
        calls["download"].append((built, args, kwargs))
        return arrays if arrays is not None else fake_arrays()

    monkeypatch.setattr(scan_module.bridge, "build_index_composite", build)
    monkeypatch.setattr(scan_module.bridge, "download_composite_arrays", download)
    return calls


# --------------------------------------------------------------------------
# A completed run.
# --------------------------------------------------------------------------


def test_a_completed_run_records_its_blob_and_the_row_matches_the_file(client, blob_root, monkeypatch):
    install_raster(monkeypatch)

    with SessionLocal() as db:
        run = scan_module.run_raster_scan(db, "2026-09-06", scale_m=200)

        assert run.status == "ok"
        assert run.reason is None
        assert run.completed_at is not None
        assert run.cell_count == 4
        assert run.scale_m == 200
        assert run.retention_days == 30

        blob = Path(run.blob_path)
        assert blob == storage.run_blob_path(run.id, blob_root)
        assert blob.exists()
        assert run.blob_bytes == blob.stat().st_size
        assert run.blob_deleted_at is None

        # The cells on disk are the cells that were downloaded.
        stored = storage.read_cells(run.blob_path)
        assert stored[DATE_BAND].tolist() == [OLD_MS, NEW_MS, NEW_MS, NEW_MS]
        assert stored[DATE_BAND].dtype == np.int64


def test_the_scan_asks_for_the_study_polygon_and_names_no_scene_policy(client, blob_root, monkeypatch):
    """Which scenes answer for a date is one system-wide rule in
    data-pipeline, not a per-caller argument the raster scan could set
    differently from the pin path."""
    from src import _study_area

    calls = install_raster(monkeypatch)
    with SessionLocal() as db:
        scan_module.run_raster_scan(db, "2026-09-06")

    (polygon, date, args, kwargs), = calls["composite"]
    assert polygon == _study_area.STUDY_AREA_POLYGON_LATLNG
    assert date == "2026-09-06"
    assert args == () and kwargs == {}
    # The scale is the one thing the scan does choose.
    (_, _, download_kwargs), = calls["download"]
    assert download_kwargs == {"scale_m": 200}


def test_the_summary_survives_the_cells_and_still_names_a_real_acquisition(client, blob_root, monkeypatch):
    install_raster(monkeypatch)

    with SessionLocal() as db:
        run = scan_module.run_raster_scan(db, "2026-09-06")

        assert run.summary["cell_count"] == 4
        # mode over [OLD, NEW, NEW, NEW] -- one of the inputs, never
        # their average.
        assert run.summary["bands"][DATE_BAND] == NEW_MS
        assert run.summary["bands"][DATE_BAND] in (OLD_MS, NEW_MS)
        assert run.summary["reducers"][DATE_BAND] == "mode"
        assert run.summary["reducers"]["ndci"] == "mean"
        # The average of the two would be this, and it is not stored.
        assert run.summary["bands"][DATE_BAND] != (OLD_MS + NEW_MS) // 2


def test_the_scene_span_comes_from_the_cells_not_the_requested_date(client, blob_root, monkeypatch):
    """A raster is a most-recent-wins mosaic, so one scan routinely mixes
    acquisitions. The run states the real span rather than implying its
    target date was the date of the data."""
    install_raster(monkeypatch)

    with SessionLocal() as db:
        run = scan_module.run_raster_scan(db, "2026-09-06")

        assert run.date_used == "2026-09-06"
        assert run.oldest_scene_date == "2026-08-25"
        assert run.newest_scene_date == "2026-09-04"
        assert run.date_used not in (run.oldest_scene_date, run.newest_scene_date)
        assert run.scene_count == 2


def test_a_scene_that_contributed_no_cell_is_not_claimed_as_data(client, blob_root, monkeypatch):
    """A scene can sit in the window and be wholly cloudy over this
    polygon. The span is taken from the cells that survived, so such a
    scene never widens the stated date range."""
    third = 1788838200000  # 2026-09-08T03:30:00Z -- in the window, no surviving cell
    install_raster(
        monkeypatch,
        arrays=fake_arrays((OLD_MS, NEW_MS)),
        composite=fake_composite((OLD_MS, NEW_MS, third)),
    )

    with SessionLocal() as db:
        run = scan_module.run_raster_scan(db, "2026-09-06")

        assert run.scene_count == 3
        assert run.newest_scene_date == "2026-09-04"


# --------------------------------------------------------------------------
# Failure modes.
# --------------------------------------------------------------------------


def test_gee_auth_error_aborts_without_touching_the_previous_run(client, blob_root, monkeypatch):
    install_raster(monkeypatch)
    with SessionLocal() as db:
        good = scan_module.run_raster_scan(db, "2026-09-06")
        good_path = good.blob_path
        good_bytes = good.blob_bytes
    assert Path(good_path).exists()

    def unauthenticated(*_args, **_kwargs):
        raise scan_module.bridge.GEEAuthError("forced for test")

    monkeypatch.setattr(scan_module.bridge, "build_index_composite", unauthenticated)

    with SessionLocal() as db:
        aborted = scan_module.run_raster_scan(db, "2026-09-07")

        assert aborted.status == "error"
        assert "GEEAuthError" in aborted.reason
        assert aborted.blob_path is None
        assert aborted.completed_at is not None

        # The last known-good raster is exactly where it was.
        previous = db.get(RasterScanRun, good.id)
        assert previous.status == "ok"
        assert previous.blob_path == good_path
        assert previous.blob_bytes == good_bytes
        assert Path(good_path).exists()
        assert storage.read_cells(good_path)[DATE_BAND].dtype == np.int64


def test_no_usable_imagery_is_recorded_as_no_data_not_an_error(client, blob_root, monkeypatch):
    def nothing_there(*_args, **_kwargs):
        raise scan_module.bridge.NoCloudFreeImageryError("no scenes in the window")

    monkeypatch.setattr(scan_module.bridge, "build_index_composite", nothing_there)

    with SessionLocal() as db:
        run = scan_module.run_raster_scan(db, "2026-09-06")

        assert run.status == "no_data"
        assert "NoCloudFreeImageryError" in run.reason
        assert run.blob_path is None
        assert run.cell_count is None
        assert run.summary is None
    assert not storage.run_blob_dir(1, blob_root).exists()


def test_an_all_masked_polygon_is_also_no_data(client, blob_root, monkeypatch):
    install_raster(monkeypatch)

    def all_masked(*_args, **_kwargs):
        raise scan_module.bridge.NoWaterPixelsError("every cell masked")

    monkeypatch.setattr(scan_module.bridge, "download_composite_arrays", all_masked)

    with SessionLocal() as db:
        run = scan_module.run_raster_scan(db, "2026-09-06")
        assert run.status == "no_data"
        assert run.blob_path is None


def test_a_fabricated_date_aborts_the_run_and_stores_nothing(client, blob_root, monkeypatch):
    """The date guards live in data-pipeline and raise before anything is
    returned, so a raster with an invented acquisition date never reaches
    disk. The run records why."""
    install_raster(monkeypatch)

    def invented(*_args, **_kwargs):
        raise scan_module.bridge.FabricatedDateError("cell date matches no source acquisition")

    monkeypatch.setattr(scan_module.bridge, "download_composite_arrays", invented)

    with SessionLocal() as db:
        run = scan_module.run_raster_scan(db, "2026-09-06")

        assert run.status == "error"
        assert "FabricatedDateError" in run.reason
        assert run.blob_path is None
        assert run.summary is None
        assert not storage.run_blob_dir(run.id, blob_root).exists()


# --------------------------------------------------------------------------
# One scan at a time.
# --------------------------------------------------------------------------


def test_a_second_scan_refuses_to_start_while_one_is_running(client, blob_root, monkeypatch):
    calls = install_raster(monkeypatch)

    with SessionLocal() as db:
        db.add(RasterScanRun(
            started_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            status="running", date_used="2026-09-06", scale_m=200, retention_days=30,
        ))
        db.commit()
        before = len(db.execute(select(RasterScanRun)).scalars().all())

        with pytest.raises(scan_module.ConcurrentRasterScanError):
            scan_module.run_raster_scan(db, "2026-09-06")

        # Refused before anything was written: no new row, no transfer.
        after = db.execute(select(RasterScanRun)).scalars().all()
        assert len(after) == before
        assert calls["composite"] == []


def test_allow_concurrent_overrides_the_guard(client, blob_root, monkeypatch):
    install_raster(monkeypatch)

    with SessionLocal() as db:
        db.add(RasterScanRun(
            started_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            status="running", date_used="2026-09-06", scale_m=200, retention_days=30,
        ))
        db.commit()

        run = scan_module.run_raster_scan(db, "2026-09-06", allow_concurrent=True)
        assert run.status == "ok"


def test_a_run_stuck_in_running_stops_blocking_new_scans(client, blob_root, monkeypatch):
    """A process killed mid-transfer leaves a row 'running' forever;
    without an expiry it would block every later scan."""
    install_raster(monkeypatch)

    with SessionLocal() as db:
        ghost = RasterScanRun(
            started_at=datetime.now(timezone.utc)
            - timedelta(hours=scan_module.STALE_RUN_HOURS + 1),
            status="running", date_used="2026-09-05", scale_m=200, retention_days=30,
        )
        db.add(ghost)
        db.commit()
        db.refresh(ghost)

        run = scan_module.run_raster_scan(db, "2026-09-06")

        assert run.status == "ok"
        db.refresh(ghost)
        assert ghost.status == "error"
        assert ghost.completed_at is not None


def test_the_stale_window_is_far_longer_than_a_real_run():
    """One raster is one composite plus one transfer -- ~10 s measured at
    the 200 m read. The window only has to outlast that."""
    assert scan_module.STALE_RUN_HOURS >= 1


def test_a_finished_run_never_blocks_the_next_one(client, blob_root, monkeypatch):
    install_raster(monkeypatch)
    with SessionLocal() as db:
        first = scan_module.run_raster_scan(db, "2026-09-06")
        second = scan_module.run_raster_scan(db, "2026-09-07")

        assert first.status == "ok" and second.status == "ok"
        assert first.id != second.id
        assert Path(first.blob_path).exists()
        assert Path(second.blob_path).exists()
        assert first.blob_path != second.blob_path


# --------------------------------------------------------------------------
# The pin path is untouched.
# --------------------------------------------------------------------------


def test_a_raster_scan_writes_no_detection_cache_or_regional_scan_row(client, blob_root, monkeypatch):
    from src.db_models import DetectionCache, RegionalScanPoint, RegionalScanRun

    install_raster(monkeypatch)
    with SessionLocal() as db:
        before = {
            model: len(db.execute(select(model)).scalars().all())
            for model in (DetectionCache, RegionalScanPoint, RegionalScanRun)
        }
        scan_module.run_raster_scan(db, "2026-09-06")
        after = {
            model: len(db.execute(select(model)).scalars().all())
            for model in (DetectionCache, RegionalScanPoint, RegionalScanRun)
        }
        assert before == after


# --------------------------------------------------------------------------
# Failures AFTER the transfer succeeds.
#
# The write and the summary used to sit outside the try/except, so a disk
# error escaped run_raster_scan entirely and left the row 'running' with
# no completed_at -- which _finish exists to make impossible, and which
# the concurrency guard then reads as a live run blocking every later
# scan until the stale window expires.
# --------------------------------------------------------------------------


def test_a_storage_failure_ends_the_run_as_error_not_stuck_running(client, blob_root, monkeypatch):
    install_raster(monkeypatch)

    def full_disk(*_args, **_kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(storage, "write_cells", full_disk)

    with SessionLocal() as db:
        run = scan_module.run_raster_scan(db, "2026-09-06")

        assert run.status == "error", "a disk failure must be recorded, not escape"
        assert run.completed_at is not None, "no exit path may leave a row open-ended"
        assert "No space left on device" in run.reason
        assert run.blob_path is None

        # Nothing left 'running' to block the next scan.
        still_running = db.execute(
            select(RasterScanRun).where(RasterScanRun.status == "running")
        ).scalars().all()
        assert still_running == []


def test_a_failure_while_summarising_is_recorded_the_same_way(client, blob_root, monkeypatch):
    """The summary is computed next to the write and was equally exposed."""
    install_raster(monkeypatch)

    def broken_summary(*_args, **_kwargs):
        raise OSError("summary could not be computed")

    monkeypatch.setattr(scan_module.bridge, "summarize_raster_cells", broken_summary)

    with SessionLocal() as db:
        run = scan_module.run_raster_scan(db, "2026-09-06")
        assert run.status == "error"
        assert run.completed_at is not None
        assert db.execute(
            select(RasterScanRun).where(RasterScanRun.status == "running")
        ).scalars().all() == []


def test_every_stale_running_row_is_expired_not_only_the_newest(client, blob_root, monkeypatch):
    """A ghost sitting behind a newer 'running' row must still be cleaned
    up; a guard that only inspects the newest would strand it forever."""
    install_raster(monkeypatch)
    stale = datetime.now(timezone.utc) - timedelta(hours=scan_module.STALE_RUN_HOURS + 2)

    with SessionLocal() as db:
        db.execute(delete(RasterScanRun))
        db.commit()
        older = RasterScanRun(
            started_at=stale - timedelta(hours=1), status="running",
            date_used="2026-09-05", scale_m=200, retention_days=30,
        )
        newer = RasterScanRun(
            started_at=stale, status="running",
            date_used="2026-09-06", scale_m=200, retention_days=30,
        )
        db.add_all([older, newer])
        db.commit()
        older_id, newer_id = older.id, newer.id

        run = scan_module.run_raster_scan(db, "2026-09-07")
        assert run.status == "ok"

        assert db.get(RasterScanRun, older_id).status == "error", (
            "the older ghost was left 'running' -- only the newest row was expired"
        )
        assert db.get(RasterScanRun, newer_id).status == "error"
        assert db.get(RasterScanRun, older_id).completed_at is not None


# --------------------------------------------------------------------------
# The map overlay drawn from the stored cells (src/raster_scan/render.py).
#
# Rendering happens after the run is committed, on purpose: the cells are
# the result, the overlay is a picture of them, and a failed picture must
# not be able to cost a good raster its row.
# --------------------------------------------------------------------------


def test_a_completed_scan_records_where_its_overlay_was_drawn(client, blob_root, monkeypatch):
    from src.raster_scan import render

    install_raster(monkeypatch)

    with SessionLocal() as db:
        run = scan_module.run_raster_scan(db, "2026-09-06")

        assert run.status == "ok"
        overlay = run.overlay
        assert overlay["status"] == "ok"
        # A PNG with no bounds is not a map layer; both are on the row.
        assert overlay["bounds"]["leaflet_bounds"] == [
            [overlay["bounds"]["south"], overlay["bounds"]["west"]],
            [overlay["bounds"]["north"], overlay["bounds"]["east"]],
        ]
        png = Path(overlay["assets"]["ndci"]["path"])
        assert png.exists() and png.parent == storage.run_blob_dir(run.id, blob_root)
        assert overlay["assets"]["ndci"]["bytes"] == png.stat().st_size
        # Four cells were stored; the rest of the study area is drawn as
        # unmeasured rather than left blank.
        assert overlay["assets"]["ndci"]["valued_pixels"] == 4
        assert overlay["assets"]["ndci"]["no_data_pixels"] > 4
        assert overlay["assets"]["ndci"]["measured_fraction"] < 0.001
        assert render.NO_DATA_MIN_ALPHA > 0


def test_a_failed_render_does_not_cost_the_scan_its_raster(client, blob_root, monkeypatch):
    """The overlay is derived; the cells are not. A render that blows up
    is recorded on the row and leaves the raster, the summary and the
    run's status alone."""
    from src.raster_scan import render

    install_raster(monkeypatch)

    def boom(*_args, **_kwargs):
        raise RuntimeError("no pixels for you")

    monkeypatch.setattr(render, "write_overlay_assets", boom)

    with SessionLocal() as db:
        run = scan_module.run_raster_scan(db, "2026-09-06")

        assert run.status == "ok", "a picture failing must not fail the scan"
        assert run.reason is None
        assert Path(run.blob_path).exists()
        assert run.cell_count == 4
        assert run.summary["cell_count"] == 4
        # Recorded, not swallowed -- and distinguishable from "never
        # rendered" (null) and from an expired run's removed overlay.
        assert run.overlay["status"] == "error"
        assert "no pixels for you" in run.overlay["error"]
