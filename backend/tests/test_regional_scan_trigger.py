"""Unit tests for should_trigger_scan() -- pure decision function (spec
§5), no DB, no GEE -- plus integration coverage of poll_and_maybe_scan()
(the impure orchestrator), using a real DB (isolated SQLite, via the
`client` fixture) with `bridge.get_newest_scene_timestamp` and
`run_scan` monkeypatched, mirroring test_regional_scan_scan.py's
mocking pattern for `bridge.detect`. test_regional_scan_scheduler_job.py
only proves the scheduler job is registered with the right interval --
it never calls poll_and_maybe_scan()'s body, so the real orchestration
behavior is exercised here instead."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from src.config import REGIONAL_SCAN_GRID_SPACING_KM
from src.db import SessionLocal
from src.db_models import RegionalScanRun
from src.regional_scan import trigger as trigger_module
from src.regional_scan.trigger import should_trigger_scan

_NOW = datetime(2026, 8, 31, 12, 0, 0, tzinfo=timezone.utc)


def test_no_scene_info_never_triggers():
    assert should_trigger_scan(None, None, cooldown_hours=20, now=_NOW) is False


def test_first_ever_run_triggers_when_a_scene_exists():
    assert should_trigger_scan(None, "2026-08-30T10:00:00+00:00", cooldown_hours=20, now=_NOW) is True


def test_same_scene_as_last_run_does_not_trigger():
    last_run = RegionalScanRun(
        started_at=_NOW - timedelta(hours=30), status="ok", grid_spacing_km=5.0,
        date_used="2026-08-30", newest_scene_date="2026-08-30T10:00:00+00:00", total_points=1,
    )
    assert should_trigger_scan(
        last_run, "2026-08-30T10:00:00+00:00", cooldown_hours=20, now=_NOW
    ) is False


def test_newer_scene_but_cooldown_not_elapsed_does_not_trigger():
    last_run = RegionalScanRun(
        started_at=_NOW - timedelta(hours=5), status="ok", grid_spacing_km=5.0,
        date_used="2026-08-30", newest_scene_date="2026-08-30T10:00:00+00:00", total_points=1,
    )
    assert should_trigger_scan(
        last_run, "2026-08-31T09:00:00+00:00", cooldown_hours=20, now=_NOW
    ) is False


def test_newer_scene_and_cooldown_elapsed_triggers():
    last_run = RegionalScanRun(
        started_at=_NOW - timedelta(hours=21), status="ok", grid_spacing_km=5.0,
        date_used="2026-08-30", newest_scene_date="2026-08-30T10:00:00+00:00", total_points=1,
    )
    assert should_trigger_scan(
        last_run, "2026-08-31T09:00:00+00:00", cooldown_hours=20, now=_NOW
    ) is True


def test_cooldown_elapsed_but_no_newer_scene_does_not_trigger():
    last_run = RegionalScanRun(
        started_at=_NOW - timedelta(hours=21), status="ok", grid_spacing_km=5.0,
        date_used="2026-08-30", newest_scene_date="2026-08-30T10:00:00+00:00", total_points=1,
    )
    assert should_trigger_scan(
        last_run, "2026-08-29T10:00:00+00:00", cooldown_hours=20, now=_NOW
    ) is False


# --- poll_and_maybe_scan() integration coverage -----------------------------
#
# Real DB (the `client` fixture's isolated SQLite -- see conftest.py),
# `bridge.get_newest_scene_timestamp` and `run_scan` monkeypatched so no
# live GEE call and no real (slow) scan happens. The backend test DB is
# shared for the whole pytest session (conftest.py creates it once at
# import time, not per-test) and test_regional_scan_scan.py's tests run
# first alphabetically and leave RegionalScanRun rows behind -- so every
# test below explicitly clears the table first rather than assuming it
# starts empty, to stay correct regardless of test execution order.

def _clear_regional_scan_runs() -> None:
    db = SessionLocal()
    try:
        db.execute(delete(RegionalScanRun))
        db.commit()
    finally:
        db.close()


def test_poll_and_maybe_scan_calls_run_scan_when_trigger_conditions_are_met(client, monkeypatch):
    """No prior run + the poll returns a real scene date -> should_trigger_scan
    is True -> run_scan must actually be called (call-tracking stub, not a
    real scan)."""
    _clear_regional_scan_runs()

    monkeypatch.setattr(
        trigger_module.bridge, "get_newest_scene_timestamp",
        lambda polygon, since: "2026-08-30T10:00:00+00:00",
    )
    calls = []
    monkeypatch.setattr(
        trigger_module, "run_scan",
        lambda db, date_used, grid_spacing_km, newest_scene_date=None: calls.append(
            {"date_used": date_used, "grid_spacing_km": grid_spacing_km, "newest_scene_date": newest_scene_date}
        ),
    )

    trigger_module.poll_and_maybe_scan()

    assert len(calls) == 1
    assert calls[0]["newest_scene_date"] == "2026-08-30T10:00:00+00:00"
    assert calls[0]["grid_spacing_km"] == REGIONAL_SCAN_GRID_SPACING_KM


def test_poll_and_maybe_scan_does_not_call_run_scan_when_cooldown_not_elapsed(client, monkeypatch):
    """A prior run started moments ago (cooldown nowhere close to elapsed)
    -> should_trigger_scan is False even though the poll reports a newer
    scene -> run_scan must NOT be called."""
    _clear_regional_scan_runs()

    db = SessionLocal()
    try:
        db.add(RegionalScanRun(
            started_at=datetime.now(timezone.utc), status="ok", grid_spacing_km=5.0,
            date_used="2026-08-30", newest_scene_date="2026-08-30T10:00:00+00:00", total_points=1,
        ))
        db.commit()
    finally:
        db.close()

    monkeypatch.setattr(
        trigger_module.bridge, "get_newest_scene_timestamp",
        lambda polygon, since: "2026-08-31T09:00:00+00:00",
    )
    calls = []
    monkeypatch.setattr(trigger_module, "run_scan", lambda *a, **kw: calls.append((a, kw)))

    trigger_module.poll_and_maybe_scan()

    assert calls == []


def test_poll_and_maybe_scan_swallows_gee_auth_error_without_calling_run_scan(client, monkeypatch):
    """bridge.get_newest_scene_timestamp raising GEEAuthError must not
    propagate out of poll_and_maybe_scan() (it's the scheduled job body --
    a poll failure must not crash the scheduler process) and must not
    reach run_scan()."""

    def _raise(*_a, **_k):
        raise trigger_module.bridge.GEEAuthError("forced for test -- synthetic scene-poll failure")

    monkeypatch.setattr(trigger_module.bridge, "get_newest_scene_timestamp", _raise)
    calls = []
    monkeypatch.setattr(trigger_module, "run_scan", lambda *a, **kw: calls.append((a, kw)))

    trigger_module.poll_and_maybe_scan()  # must not raise

    assert calls == []
