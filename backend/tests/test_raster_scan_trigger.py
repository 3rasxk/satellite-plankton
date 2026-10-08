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
    candidate = "2026-09-08T03:42:10+00:00"
    with SessionLocal() as db:
        db.add(RasterScanRun(
            started_at=_NOW - timedelta(hours=21), completed_at=_NOW - timedelta(hours=20),
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


def _poll_with_prior_run(monkeypatch, status):
    _clear()
    candidate = "2024-03-14T03:00:00Z"
    with SessionLocal() as db:
        db.add(RasterScanRun(
            started_at=_NOW - timedelta(days=2), completed_at=_NOW - timedelta(days=2),
            status=status, date_used="2024-03-14", scale_m=200, retention_days=30,
            trigger_scene_timestamp=candidate,
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
