"""Unit tests for should_trigger_scan() -- pure decision function (spec
§5), no DB, no GEE. poll_and_maybe_scan() (the impure orchestrator) is
exercised separately in test_regional_scan_scan.py-adjacent integration
coverage via Task 6's scheduler test, not here."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.db_models import RegionalScanRun
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
