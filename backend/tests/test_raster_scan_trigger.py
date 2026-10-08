"""Raster scan polling uses candidate-scene timestamps, not cell dates."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from src.db import SessionLocal
from src.db_models import RasterScanRun
from src.raster_scan import trigger as trigger_module
from src.raster_scan.trigger import should_trigger_scan

_NOW = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)


def test_trigger_requires_a_new_candidate_scene_and_elapsed_cooldown():
    old = "2026-09-07T03:41:12+00:00"
    new = "2026-09-08T03:42:10+00:00"
    assert should_trigger_scan(None, None, None, 20, _NOW) is False
    assert should_trigger_scan(None, None, new, 20, _NOW) is True
    assert should_trigger_scan(_NOW - timedelta(hours=21), old, old, 20, _NOW) is False
    assert should_trigger_scan(_NOW - timedelta(hours=5), old, new, 20, _NOW) is False
    assert should_trigger_scan(_NOW - timedelta(hours=21), old, new, 20, _NOW) is True


def _clear() -> None:
    with SessionLocal() as db:
        db.execute(delete(RasterScanRun))
        db.commit()


def test_poll_runs_raster_and_records_the_full_candidate_timestamp(client, monkeypatch):
    _clear()
    candidate = "2026-09-08T03:42:10+00:00"
    monkeypatch.setattr(
        trigger_module.bridge, "get_newest_scene_timestamp", lambda *_: candidate,
    )
    calls = []
    monkeypatch.setattr(
        trigger_module, "run_raster_scan",
        lambda db, target_date, trigger_scene_timestamp=None: calls.append(
            (target_date, trigger_scene_timestamp)
        ),
    )

    trigger_module.poll_and_maybe_scan()

    assert len(calls) == 1
    assert calls[0][1] == candidate


def test_cloudy_candidate_is_not_retried_after_a_no_data_run(client, monkeypatch):
    _clear()
    # Pin the cooldown so the outcome does not depend on the environment.
    monkeypatch.setattr(trigger_module, "RASTER_SCAN_COOLDOWN_HOURS", 20)
    real_now = datetime.now(timezone.utc)
    candidate = "2026-09-08T03:42:10+00:00"
    with SessionLocal() as db:
        db.add(RasterScanRun(
            started_at=real_now - timedelta(hours=21),
            completed_at=real_now - timedelta(hours=20),
            status="no_data", date_used="2026-09-08", scale_m=200, retention_days=30,
            trigger_scene_timestamp=candidate,
        ))
        db.commit()

    monkeypatch.setattr(
        trigger_module.bridge, "get_newest_scene_timestamp", lambda *_: candidate,
    )
    calls = []
    monkeypatch.setattr(trigger_module, "run_raster_scan", lambda *a, **k: calls.append((a, k)))

    trigger_module.poll_and_maybe_scan()
    assert calls == []


def test_poll_failure_does_not_start_a_scan(client, monkeypatch):
    def fail(*_args):
        raise trigger_module.bridge.GEEAuthError("synthetic auth failure")

    monkeypatch.setattr(trigger_module.bridge, "get_newest_scene_timestamp", fail)
    calls = []
    monkeypatch.setattr(trigger_module, "run_raster_scan", lambda *a, **k: calls.append((a, k)))
    trigger_module.poll_and_maybe_scan()
    assert calls == []


def _poll_with_prior_run(monkeypatch, status, age=timedelta(days=2), source_metadata=None):
    _clear()
    # Pin the cooldown (20 h) and age the prior run from the real clock, so
    # the result depends on neither RASTER_SCAN_COOLDOWN_HOURS nor the date.
    monkeypatch.setattr(trigger_module, "RASTER_SCAN_COOLDOWN_HOURS", 20)
    started = datetime.now(timezone.utc) - age
    candidate = "2024-03-14T03:00:00Z"
    with SessionLocal() as db:
        db.add(RasterScanRun(
            started_at=started,
            completed_at=None if status == "running" else started,
            status=status, date_used="2024-03-14", scale_m=200, retention_days=30,
            trigger_scene_timestamp=candidate, source_metadata=source_metadata,
        ))
        db.commit()
    monkeypatch.setattr(
        trigger_module.bridge, "get_newest_scene_timestamp", lambda *_: candidate,
    )
    calls = []
    monkeypatch.setattr(trigger_module, "run_raster_scan", lambda *a, **k: calls.append((a, k)))
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
    # presumed dead and its scene must be retried (cooldown elapsed here).
    assert len(_poll_with_prior_run(monkeypatch, "running", age=timedelta(days=2))) == 1


def test_live_running_row_still_consumes_its_scene(client, monkeypatch):
    # Younger than STALE_RUN_HOURS the run may be genuinely live.
    assert _poll_with_prior_run(
        monkeypatch, "running", age=timedelta(minutes=10),
    ) == []


def test_shutdown_stopped_bootstrap_does_not_start_the_cooldown(client, monkeypatch):
    # A bootstrap interrupted by shutdown (2 h ago, inside the 20 h cooldown)
    # was cut short by the process, not by the data; the next poll retries.
    calls = _poll_with_prior_run(
        monkeypatch, "error", age=timedelta(hours=2),
        source_metadata={"bootstrap_mode": True, "search_stopped": "shutdown"},
    )
    assert len(calls) == 1


def test_budget_stopped_bootstrap_still_starts_the_cooldown(client, monkeypatch):
    # A budget stop spent its full wall-clock budget; retry spacing applies.
    calls = _poll_with_prior_run(
        monkeypatch, "error", age=timedelta(hours=2),
        source_metadata={"bootstrap_mode": True, "search_stopped": "budget"},
    )
    assert calls == []
