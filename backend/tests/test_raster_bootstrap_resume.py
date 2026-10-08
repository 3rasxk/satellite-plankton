"""Bootstrap resume after a budget/shutdown stop. Injected clock, synthetic
imagery, no GEE.

A resumed run continues the 15-day window walk from just before the oldest
window the stopped run searched. Its provenance lists only the windows it
searched itself; it never claims the prior run's coverage.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete

from src import config as config_module
from src.db import SessionLocal
from src.db_models import RasterScanRun
from src.raster_scan import scan as scan_module
from src.raster_scan import storage
from tests.test_raster_scan_bootstrap import _arrays, _composite

_TARGET = "2026-09-06"


def _clear(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "RASTER_BLOB_ROOT", tmp_path)
    monkeypatch.setattr(config_module, "RASTER_BOOTSTRAP_BUDGET_MINUTES", 45)
    with SessionLocal() as db:
        db.execute(delete(RasterScanRun))
        db.commit()


def _stopped_metadata(window_start, window_end="2026-09-07", stopped="budget"):
    return {
        "bootstrap_mode": True,
        "target_date": _TARGET,
        "archive_start_date": scan_module.bridge.SENTINEL2_SR_ARCHIVE_START_DATE,
        "searched_windows": [],
        "search_range": {"window_start": window_start, "window_end": window_end},
        "search_stopped": stopped,
    }


def _add_prior(status="error", metadata=None, hours_ago=25):
    started = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    with SessionLocal() as db:
        row = RasterScanRun(
            started_at=started, completed_at=started + timedelta(minutes=45),
            status=status, date_used=_TARGET, scale_m=200, retention_days=30,
            source_metadata=metadata,
        )
        db.add(row)
        db.commit()
        return row.id


def _cloudy_builder(calls, clock=None, minutes=0):
    def build(_polygon, target_date, max_scene_age_days=None):
        calls.append(target_date)
        if clock is not None:
            clock["now"] += minutes * 60
        raise scan_module.bridge.NoCloudFreeImageryError("cloudy window")

    return build


def test_resumed_run_continues_before_the_prior_oldest_window_and_claims_only_its_own(
    client, tmp_path, monkeypatch,
):
    _clear(tmp_path, monkeypatch)
    prior_id = _add_prior(metadata=_stopped_metadata("2026-08-08"))
    calls = []

    def build(_polygon, target_date, max_scene_age_days=None):
        calls.append(target_date)
        return _composite(target_date, max_scene_age_days, f"scene-{target_date}", 1787196600000)

    monkeypatch.setattr(scan_module.bridge, "build_index_composite", build)
    monkeypatch.setattr(
        scan_module.bridge, "download_composite_arrays", lambda c, scale_m: _arrays()
    )
    with SessionLocal() as db:
        run = scan_module.run_raster_scan(db, _TARGET)

    assert calls == ["2026-08-07"]
    assert run.status == "ok"
    metadata = run.source_metadata
    assert metadata["resumed_from"]["run_id"] == prior_id
    assert metadata["resumed_from"]["walk_starts_at"] == "2026-08-07"
    # Only this run's one window, never the prior run's 2026-08-08..2026-09-07.
    assert metadata["search_range"] == {
        "window_start": "2026-07-24", "window_end": "2026-08-08",
    }
    assert all(w["window_end"] <= "2026-08-08" for w in metadata["searched_windows"])


def test_resumed_run_that_stops_again_is_an_error_with_only_its_own_range(
    client, tmp_path, monkeypatch,
):
    _clear(tmp_path, monkeypatch)
    _add_prior(metadata=_stopped_metadata("2026-08-08"))
    clock = {"now": 0.0}
    monkeypatch.setattr(scan_module, "_monotonic", lambda: clock["now"])
    calls = []
    monkeypatch.setattr(
        scan_module.bridge, "build_index_composite", _cloudy_builder(calls, clock, 20)
    )
    with SessionLocal() as db:
        run = scan_module.run_raster_scan(db, _TARGET)

    assert calls == ["2026-08-07", "2026-07-23", "2026-07-08"]
    assert run.status == "error"
    assert "budget" in run.reason
    metadata = run.source_metadata
    assert metadata["search_stopped"] == "budget"
    assert metadata["search_range"] == {
        "window_start": "2026-06-24", "window_end": "2026-08-08",
    }
    assert len(metadata["searched_windows"]) == 3


def test_resume_chains_from_the_newest_stopped_run(client, tmp_path, monkeypatch):
    _clear(tmp_path, monkeypatch)
    _add_prior(metadata=_stopped_metadata("2026-08-08"), hours_ago=50)
    newer = _add_prior(
        metadata=_stopped_metadata("2026-06-23", window_end="2026-08-08", stopped="shutdown"),
        hours_ago=25,
    )
    calls = []
    clock = {"now": 0.0}
    monkeypatch.setattr(scan_module, "_monotonic", lambda: clock["now"])
    monkeypatch.setattr(
        scan_module.bridge, "build_index_composite", _cloudy_builder(calls, clock, 50)
    )
    with SessionLocal() as db:
        run = scan_module.run_raster_scan(db, _TARGET)

    assert calls == ["2026-06-22"]
    assert run.source_metadata["resumed_from"]["run_id"] == newer
    assert run.status == "error"


def test_resumed_walk_that_reaches_the_archive_start_keeps_no_data_semantics(
    client, tmp_path, monkeypatch,
):
    _clear(tmp_path, monkeypatch)
    prior_id = _add_prior(metadata=_stopped_metadata("2017-04-20"))
    calls = []
    monkeypatch.setattr(scan_module.bridge, "build_index_composite", _cloudy_builder(calls))
    with SessionLocal() as db:
        run = scan_module.run_raster_scan(db, _TARGET)

    assert calls == ["2017-04-19", "2017-04-04"]
    assert run.status == "no_data"
    assert "archive" in run.reason.lower()
    assert f"run {prior_id}" in run.reason
    assert "search_stopped" not in run.source_metadata
    assert run.source_metadata["search_range"] == {
        "window_start": "2017-03-28", "window_end": "2017-04-20",
    }


@pytest.mark.parametrize(
    "status,metadata",
    [
        # A completed search (archive exhausted) is not resumed.
        ("no_data", {**_stopped_metadata("2017-03-28"), "search_stopped": None}),
        # Stopped, but range missing / malformed / not strictly older / pre-archive.
        ("error", {**_stopped_metadata("2026-08-08"), "search_range": None}),
        ("error", _stopped_metadata("not-a-date")),
        ("error", _stopped_metadata("2026-09-07")),
        ("error", _stopped_metadata("2017-03-28")),
        ("error", _stopped_metadata("2010-01-01")),
        # An error that is not a budget/shutdown stop (e.g. auth failure).
        ("error", {**_stopped_metadata("2026-08-08"), "search_stopped": None}),
        ("error", "not-a-dict"),
    ],
)
def test_unusable_prior_state_falls_back_to_today(
    client, tmp_path, monkeypatch, status, metadata,
):
    _clear(tmp_path, monkeypatch)
    _add_prior(status=status, metadata=metadata)
    calls = []

    def build(_polygon, target_date, max_scene_age_days=None):
        calls.append(target_date)
        scan_module.shutdown.request_stop()
        raise scan_module.bridge.NoCloudFreeImageryError("cloudy window")

    monkeypatch.setattr(scan_module.bridge, "build_index_composite", build)
    try:
        with SessionLocal() as db:
            run = scan_module.run_raster_scan(db, _TARGET)
    finally:
        scan_module.shutdown.clear_stop()

    assert calls == [_TARGET]
    assert "resumed_from" not in run.source_metadata


def test_rows_without_search_metadata_do_not_block_a_resume(client, tmp_path, monkeypatch):
    # A stood-down or stale-expired row records no search; it neither resumes
    # nor hides the stopped run behind it.
    _clear(tmp_path, monkeypatch)
    prior_id = _add_prior(metadata=_stopped_metadata("2026-08-08"), hours_ago=30)
    _add_prior(metadata=None, hours_ago=25)
    calls = []

    def build(_polygon, target_date, max_scene_age_days=None):
        calls.append(target_date)
        scan_module.shutdown.request_stop()
        raise scan_module.bridge.NoCloudFreeImageryError("cloudy window")

    monkeypatch.setattr(scan_module.bridge, "build_index_composite", build)
    try:
        with SessionLocal() as db:
            run = scan_module.run_raster_scan(db, _TARGET)
    finally:
        scan_module.shutdown.clear_stop()
    assert calls == ["2026-08-07"]
    assert run.source_metadata["resumed_from"]["run_id"] == prior_id


def test_a_window_walk_that_does_not_move_strictly_older_is_refused(
    client, tmp_path, monkeypatch,
):
    _clear(tmp_path, monkeypatch)
    same = {
        "target_date": _TARGET, "max_scene_age_days": 14,
        "window_start": "2026-08-23", "window_end": "2026-09-07",
    }

    # Capped so a regression fails this test instead of hanging the suite;
    # without the guard every one of these repeats would be searched.
    def forever(_date):
        for _ in range(50):
            yield dict(same)

    monkeypatch.setattr(scan_module.bridge, "iter_bootstrap_windows", forever)
    calls = []
    monkeypatch.setattr(scan_module.bridge, "build_index_composite", _cloudy_builder(calls))
    with SessionLocal() as db:
        run = scan_module.run_raster_scan(db, _TARGET)

    assert calls == [_TARGET]
    assert run.status == "error"
    assert "strictly older" in run.reason
    assert len(run.source_metadata["searched_windows"]) == 1


def test_resumed_run_stopped_before_any_window_passes_its_resume_point_on(
    client, tmp_path, monkeypatch,
):
    # It searched nothing, so it has no search_range; the next run continues
    # from the same point instead of restarting from today.
    _clear(tmp_path, monkeypatch)
    _add_prior(metadata=_stopped_metadata("2026-08-08"), hours_ago=50)
    empty = _add_prior(metadata={
        **_stopped_metadata("2026-08-08", stopped="shutdown"),
        "search_range": None,
        "resumed_from": {
            "run_id": 1, "prior_oldest_window_start": "2026-08-08",
            "walk_starts_at": "2026-08-07",
        },
    }, hours_ago=25)
    calls = []

    def build(_polygon, target_date, max_scene_age_days=None):
        calls.append(target_date)
        scan_module.shutdown.request_stop()
        raise scan_module.bridge.NoCloudFreeImageryError("cloudy window")

    monkeypatch.setattr(scan_module.bridge, "build_index_composite", build)
    try:
        with SessionLocal() as db:
            run = scan_module.run_raster_scan(db, _TARGET)
    finally:
        scan_module.shutdown.clear_stop()
    assert calls == ["2026-08-07"]
    assert run.source_metadata["resumed_from"]["run_id"] == empty
