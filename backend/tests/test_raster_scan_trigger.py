"""Raster scan polling: which prior runs consume their trigger scene.

Rewritten for the latest-scene policy (spec 2026-10-09 §7). The poll no
longer asks `get_newest_scene_timestamp` and no longer applies the 20 h
cooldown to a new scene; a date is consumed when scan.py marks its
`scene_assessments` row used (runs ending 'no_data', or 'ok' with kept
cells reaching the date), and retries are spaced by
RASTER_SCAN_MIN_INTERVAL_HOURS. The consumption cases below
are the same ones this file pinned for the cooldown flow (commit 6e8dda5);
prior runs are closed with the real `scan._finish`, so the marking is real.
Full policy coverage: tests/test_latest_scene_trigger.py.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import delete

from src import scheduler as scheduler_module
from src.db import SessionLocal
from src.db_models import RasterScanRun, SceneAssessmentRow
from src.raster_scan import scan as scan_module
from src.raster_scan import trigger as trigger_module
from src.raster_scan.trigger import should_trigger_scan

_NOW = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _poll_never_crashed(caplog):
    """An "it did not scan" assertion must not pass because the poll hit
    its catch-all boundary."""
    caplog.set_level("INFO", logger="backend.raster_scan.trigger")
    yield
    assert not [
        r for r in caplog.get_records("call") if "unexpected failure" in r.getMessage()
    ]


def test_trigger_requires_a_new_candidate_scene_and_elapsed_cooldown():
    # The retained helper; poll_and_maybe_scan no longer calls it.
    old = "2026-09-07T03:41:12+00:00"
    new = "2026-09-08T03:42:10+00:00"
    assert should_trigger_scan(None, None, None, 20, _NOW) is False
    assert should_trigger_scan(None, None, new, 20, _NOW) is True
    assert should_trigger_scan(_NOW - timedelta(hours=21), old, old, 20, _NOW) is False
    assert should_trigger_scan(_NOW - timedelta(hours=5), old, new, 20, _NOW) is False
    assert should_trigger_scan(_NOW - timedelta(hours=21), old, new, 20, _NOW) is True


def _clear() -> None:
    with SessionLocal() as db:
        db.execute(delete(SceneAssessmentRow))
        db.execute(delete(RasterScanRun))
        db.commit()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _passing(date):
    return trigger_module.bridge.SceneAssessment(
        acquisition_date=date, cloud_fraction=0.1, water_pixels=40_000,
        decision="passed", reason=None,
    )


def _wire(monkeypatch, assessments):
    """Scripted assessment, recording scan (returns an 'error' run so no
    sites refresh follows) and a recording sites refresh -- nothing here
    may reach GEE."""
    monkeypatch.setattr(trigger_module, "RASTER_SCAN_MIN_INTERVAL_HOURS", 1)
    monkeypatch.setattr(
        trigger_module.bridge, "assess_new_scenes", lambda *a, **k: list(assessments),
    )
    calls = []

    def scan(db, target_date, trigger_scene_timestamp=None):
        calls.append((target_date, trigger_scene_timestamp))
        return SimpleNamespace(status="error")

    monkeypatch.setattr(trigger_module, "run_raster_scan", scan)
    monkeypatch.setattr(scheduler_module, "refresh_grid", lambda: None)
    return calls


def test_poll_runs_raster_with_the_passing_date_as_trigger_timestamp(client, monkeypatch):
    _clear()
    date = _today()
    calls = _wire(monkeypatch, [_passing(date)])

    trigger_module.poll_and_maybe_scan()

    # Was the full metadata-poll timestamp; now the assessed date's.
    assert calls == [(_today(), f"{date}T00:00:00+00:00")]
    _clear()


def test_cloudy_candidate_is_not_retried_after_a_no_data_run(client, monkeypatch):
    calls = _poll_with_prior_run(monkeypatch, "no_data", age=timedelta(hours=21))
    assert calls == []


def test_poll_failure_does_not_start_a_scan(client, monkeypatch):
    _clear()
    calls = _wire(monkeypatch, [])

    def fail(*_args, **_kwargs):
        raise trigger_module.bridge.GEEAuthError("synthetic auth failure")

    monkeypatch.setattr(trigger_module.bridge, "assess_new_scenes", fail)
    trigger_module.poll_and_maybe_scan()
    assert calls == []


def _poll_with_prior_run(monkeypatch, status, age=timedelta(days=2), source_metadata=None):
    """A prior attempt `age` ago for today's passing date, closed with the
    real scan._finish (so 'ok'/'no_data' mark the date used), then a poll
    that assesses the same date as passing again.

    An older successful raster exists in every case, so this is never a
    first install and the bootstrap fallback never applies; the prior run
    kept cells up to its trigger date, as a real scan of it would."""
    _clear()
    date = _today()
    stamp = f"{date}T00:00:00+00:00"
    started = datetime.now(timezone.utc) - age
    with SessionLocal() as db:
        installed_at = datetime.now(timezone.utc) - timedelta(days=30)
        db.add(RasterScanRun(
            started_at=installed_at, completed_at=installed_at, status="ok",
            date_used=date, scale_m=200, retention_days=30,
        ))
        db.add(SceneAssessmentRow(
            acquisition_date=date, cloud_fraction=0.1, water_pixels=40_000,
            decision="passed", reason=None, assessed_at=started,
        ))
        run = RasterScanRun(
            started_at=started, status="running", date_used=date, scale_m=200,
            retention_days=30, trigger_scene_timestamp=stamp,
            source_metadata=source_metadata, newest_scene_date=date,
        )
        db.add(run)
        db.commit()
        if status != "running":
            scan_module._finish(db, run, status, None if status == "ok" else "synthetic")
    calls = _wire(monkeypatch, [_passing(date)])
    try:
        trigger_module.poll_and_maybe_scan()
    finally:
        _clear()
    return calls


def test_errored_scan_retries_its_own_scene(client, monkeypatch):
    assert len(_poll_with_prior_run(monkeypatch, "error")) == 1


def test_successful_scan_still_consumes_its_scene(client, monkeypatch):
    assert _poll_with_prior_run(monkeypatch, "ok") == []


def test_partial_error_scan_retries_its_scene(client, monkeypatch):
    # Not written by the raster scan today; if it ever is, incomplete data
    # must not consume the scene.
    assert len(_poll_with_prior_run(monkeypatch, "partial_error")) == 1


def test_stale_running_row_does_not_consume_its_scene(client, monkeypatch):
    # A crash leaves status='running' forever; older than STALE_RUN_HOURS it is
    # presumed dead and its scene must be retried (min interval elapsed here).
    assert len(_poll_with_prior_run(monkeypatch, "running", age=timedelta(days=2))) == 1


def test_live_running_row_still_consumes_its_scene(client, monkeypatch):
    # Younger than STALE_RUN_HOURS the run may be genuinely live; the
    # minimum interval (1 h, = STALE_RUN_HOURS) holds the poll back.
    assert _poll_with_prior_run(
        monkeypatch, "running", age=timedelta(minutes=10),
    ) == []


def test_shutdown_stopped_bootstrap_does_not_start_the_cooldown(client, monkeypatch):
    # A bootstrap interrupted by shutdown 10 min ago (inside the 1 h minimum
    # interval) was cut short by the process, not by the data; the next poll
    # retries. (Was 2 h ago against the 20 h cooldown.)
    calls = _poll_with_prior_run(
        monkeypatch, "error", age=timedelta(minutes=10),
        source_metadata={"bootstrap_mode": True, "search_stopped": "shutdown"},
    )
    assert len(calls) == 1


def test_budget_stopped_bootstrap_still_starts_the_cooldown(client, monkeypatch):
    # A budget stop spent its full wall-clock budget; retry spacing (the
    # minimum interval) applies. (Was 2 h ago against the 20 h cooldown; 2 h
    # now exceeds the 1 h minimum interval, so the age is 10 min.)
    calls = _poll_with_prior_run(
        monkeypatch, "error", age=timedelta(minutes=10),
        source_metadata={"bootstrap_mode": True, "search_stopped": "budget"},
    )
    assert calls == []
