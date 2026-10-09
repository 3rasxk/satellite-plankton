"""F6: cooperative shutdown. Every job is a local fake; no GEE is touched.

APScheduler cannot interrupt a running job, and lifespan teardown waits
for it (shutdown(wait=True)). These tests pin the cooperative stop flag
that lets a running job end at its next checkpoint instead of finishing
all of its remaining sites or archive windows first.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from threading import Event

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from src import main as main_module
from src import scheduler as scheduler_module
from src import shutdown
from src.db import SessionLocal
from src.db_models import RasterScanRun
from src.raster_scan import scan as scan_module
from src.raster_scan import storage
from src.raster_scan import trigger as trigger_module


def test_refresh_grid_stops_between_sites_when_shutdown_is_requested(client, monkeypatch):
    shutdown.clear_stop()
    visited = []

    def fake_refresh_one_site(_db, site, _target_date, snapshot=None):
        visited.append(site.site_id)
        shutdown.request_stop()

    monkeypatch.setattr(scheduler_module, "refresh_one_site", fake_refresh_one_site)
    try:
        scheduler_module.refresh_grid()
    finally:
        shutdown.clear_stop()

    assert len(visited) == 1, visited


def test_bootstrap_scan_stops_between_windows_and_never_leaves_a_running_row(
    client, tmp_path, monkeypatch,
):
    shutdown.clear_stop()
    monkeypatch.setattr(storage, "RASTER_BLOB_ROOT", tmp_path)
    with SessionLocal() as db:
        db.execute(delete(RasterScanRun))
        db.commit()
    calls = []

    def build(_polygon, target_date, max_scene_age_days=None):
        calls.append(target_date)
        shutdown.request_stop()
        raise scan_module.bridge.NoCloudFreeImageryError("cloudy window")

    monkeypatch.setattr(scan_module.bridge, "build_index_composite", build)
    try:
        with SessionLocal() as db:
            run = scan_module.run_raster_scan(db, "2026-09-06")
            running = db.execute(
                select(RasterScanRun).where(RasterScanRun.status == "running")
            ).scalars().all()
    finally:
        shutdown.clear_stop()

    assert calls == ["2026-09-06"]
    assert run.status == "error"
    assert "interrupted by shutdown" in run.reason
    assert run.completed_at is not None
    assert running == []
    assert run.blob_path is None
    # The one window that was searched survives as provenance.
    assert len(run.source_metadata["searched_windows"]) == 1
    assert run.source_metadata["search_stopped"] == "shutdown"


def test_poll_does_not_start_a_scan_once_shutdown_is_requested(monkeypatch):
    shutdown.request_stop()
    reached = []

    # Recorded, not raised: poll_and_maybe_scan's job boundary swallows
    # exceptions, so an AssertionError raised here would pass silently.
    def forbidden(*_args, **_kwargs):
        reached.append("called")
        return None

    monkeypatch.setattr(trigger_module.bridge, "get_newest_scene_timestamp", forbidden)
    monkeypatch.setattr(trigger_module.bridge, "assess_new_scenes", forbidden)
    monkeypatch.setattr(trigger_module, "run_raster_scan", forbidden)
    try:
        trigger_module.poll_and_maybe_scan()
    finally:
        shutdown.clear_stop()
    assert reached == []


def test_lifespan_clears_the_flag_at_start_and_sets_it_before_waiting(monkeypatch):
    monkeypatch.setattr(main_module, "init_db", lambda: None)
    monkeypatch.setattr(main_module, "ensure_monitored_sites", lambda: None)
    monkeypatch.setattr(main_module, "SCHEDULER_ENABLED", True, raising=False)

    started = Event()
    stop_seen_by_job = Event()

    def cooperative_job() -> None:
        started.set()
        # Stands in for refresh_grid's between-site checkpoint. Bounded:
        # if lifespan ever raised the flag only after shutdown(wait=True),
        # an unbounded loop would hang the suite instead of failing it.
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if shutdown.stop_requested():
                stop_seen_by_job.set()
                return
            time.sleep(0.01)

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        cooperative_job, "date", run_date=datetime.now(timezone.utc), id="cooperative",
    )
    monkeypatch.setattr(main_module, "create_scheduler", lambda: scheduler)
    original_shutdown = scheduler.shutdown
    flag_at_shutdown = []

    def tracked_shutdown(wait=True):
        flag_at_shutdown.append((shutdown.stop_requested(), wait))
        return original_shutdown(wait=wait)

    monkeypatch.setattr(scheduler, "shutdown", tracked_shutdown)

    # A previous lifespan (or --reload) left the flag set.
    shutdown.request_stop()
    try:
        with TestClient(main_module.app):
            assert not shutdown.stop_requested(), "startup did not clear the stop flag"
            assert started.wait(timeout=1)
        assert flag_at_shutdown == [(True, True)]
        assert stop_seen_by_job.is_set(), "the running job never saw the stop flag"
    finally:
        shutdown.clear_stop()


def test_create_scheduler_clears_a_stale_stop_flag():
    shutdown.request_stop()
    try:
        scheduler_module.create_scheduler()
        assert not shutdown.stop_requested()
    finally:
        shutdown.clear_stop()
