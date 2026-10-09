"""Latest-scene policy (spec 2026-10-09 §7): the hourly poll assesses each
new Sentinel-2 acquisition date for cloud over the polygon's water, stores
the decision in `scene_assessments`, and starts a raster scan for the
newest PASSING date newer than the newest date already used -- at once,
not after the old 20 h cooldown -- then refreshes the 7 sites.

No GEE: `bridge.assess_new_scenes` is replaced by scripted assessments,
`run_raster_scan` (the name trigger.py imports) by a fake that writes a
real RasterScanRun row and closes it with the real `scan._finish` (which
is what marks the date used), and `scheduler.refresh_grid` by a counter.
The clock is injected (`poll_and_maybe_scan(now=...)`).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, inspect, select

from src import config as config_module
from src import scheduler as scheduler_module
from src import shutdown
from src.db import SessionLocal, engine
from src.db_models import RasterScanRun, SceneAssessmentRow
from src.raster_scan import scan as scan_module
from src.raster_scan import trigger as trigger_module

UTC = timezone.utc
NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
TODAY = "2026-10-09"       # unsettled at NOW (settles 2026-10-10T12:00)
YESTERDAY = "2026-10-08"   # settles exactly at NOW
OLDER = "2026-10-05"       # long settled at NOW


def _assessment(date, decision="passed", cloud=0.1, water=40_000, reason=None):
    if reason is None and decision == "rejected_cloud":
        reason = f"cloud {cloud:.0%} > 50%"
    return trigger_module.bridge.SceneAssessment(
        acquisition_date=date, cloud_fraction=cloud, water_pixels=water,
        decision=decision, reason=reason,
    )


@pytest.fixture()
def world(client, monkeypatch, caplog):
    """Empty run/assessment tables, a scripted assessor, a fake scan and a
    counting sites refresh. `world.assessments` is what the next poll's
    assessment returns; `world.scan_status` how the next scan ends.

    Fails any test during which the poll hit its catch-all boundary, so an
    "assert nothing happened" can never pass because the poll crashed."""
    caplog.set_level("INFO", logger="backend.raster_scan.trigger")

    class World:
        assessments: list = []
        assess_calls: list = []
        scan_calls: list = []
        refresh_calls: list = []
        scan_status = "ok"
        assess_error: Exception | None = None
        refresh_error: Exception | None = None
        clock = NOW

    w = World()
    w.assessments, w.assess_calls, w.scan_calls, w.refresh_calls = [], [], [], []

    def fake_assess(polygon, since_date, **kwargs):
        w.assess_calls.append({"polygon": polygon, "since": since_date, **kwargs})
        if w.assess_error is not None:
            raise w.assess_error
        skip = kwargs.get("skip_dates", frozenset())
        return [a for a in w.assessments if a.acquisition_date not in skip]

    def fake_scan(db, target_date, trigger_scene_timestamp=None):
        w.scan_calls.append((target_date, trigger_scene_timestamp))
        run = RasterScanRun(
            started_at=w.clock, status="running", date_used=target_date,
            scale_m=200, retention_days=30,
            trigger_scene_timestamp=trigger_scene_timestamp,
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        reason = None if w.scan_status == "ok" else f"synthetic {w.scan_status}"
        return scan_module._finish(db, run, w.scan_status, reason)

    def fake_refresh():
        w.refresh_calls.append(1)
        if w.refresh_error is not None:
            raise w.refresh_error

    monkeypatch.setattr(trigger_module.bridge, "assess_new_scenes", fake_assess)
    monkeypatch.setattr(trigger_module, "run_raster_scan", fake_scan)
    monkeypatch.setattr(scheduler_module, "refresh_grid", fake_refresh)
    # Pin the policy so the outcome does not depend on the environment.
    monkeypatch.setattr(trigger_module, "RASTER_SCAN_MIN_INTERVAL_HOURS", 1)
    monkeypatch.setattr(trigger_module, "RASTER_SCAN_POLL_LOOKBACK_DAYS", 10)
    monkeypatch.setattr(trigger_module, "RASTER_SCAN_SCALE_M", 200)

    shutdown.clear_stop()
    _clear()
    yield w
    shutdown.clear_stop()
    _clear()
    crashes = [
        r.getMessage() for r in caplog.get_records("call")
        if "unexpected failure" in r.getMessage()
    ]
    assert crashes == []


def _clear():
    with SessionLocal() as db:
        db.execute(delete(SceneAssessmentRow))
        db.execute(delete(RasterScanRun))
        db.commit()


def _poll(world, *, at=None):
    world.clock = at or world.clock
    trigger_module.poll_and_maybe_scan(now=world.clock)


def _rows() -> dict[str, SceneAssessmentRow]:
    with SessionLocal() as db:
        rows = db.execute(select(SceneAssessmentRow)).scalars().all()
        db.expunge_all()
        return {row.acquisition_date: row for row in rows}


def _add_row(date, decision="passed", *, used_in_run_id=None, assessed_at=NOW, cloud=0.1):
    with SessionLocal() as db:
        db.add(SceneAssessmentRow(
            acquisition_date=date, cloud_fraction=cloud, water_pixels=40_000,
            decision=decision, reason=None, assessed_at=assessed_at,
            used_in_run_id=used_in_run_id,
        ))
        db.commit()


def _add_run(status="ok", *, started_at, trigger=None, source_metadata=None) -> int:
    with SessionLocal() as db:
        run = RasterScanRun(
            started_at=started_at,
            completed_at=None if status == "running" else started_at,
            status=status, date_used=started_at.strftime("%Y-%m-%d"), scale_m=200,
            retention_days=30, trigger_scene_timestamp=trigger,
            source_metadata=source_metadata,
        )
        db.add(run)
        db.commit()
        return run.id


# --------------------------------------------------------------------------
# Brief, step 1
# --------------------------------------------------------------------------


def test_passing_new_scene_scans_although_the_last_attempt_was_2_hours_ago(world):
    # The old flow blocked this for RASTER_SCAN_COOLDOWN_HOURS (20 h).
    _add_run("ok", started_at=NOW - timedelta(hours=2))
    world.assessments = [_assessment(TODAY)]

    _poll(world)

    assert world.scan_calls == [(config_module.today_str(), f"{TODAY}T00:00:00+00:00")]


def test_rejected_newest_scene_starts_nothing_and_is_stored_with_its_fraction(world):
    used_run = _add_run("ok", started_at=NOW - timedelta(days=3))
    _add_row(OLDER, used_in_run_id=used_run, assessed_at=NOW - timedelta(days=3))
    world.assessments = [_assessment(TODAY, "rejected_cloud", cloud=0.83)]

    _poll(world)

    assert world.scan_calls == []
    assert world.refresh_calls == []
    rows = _rows()
    assert rows[TODAY].decision == "rejected_cloud"
    assert rows[TODAY].cloud_fraction == pytest.approx(0.83)
    assert rows[TODAY].reason == "cloud 83% > 50%"
    assert rows[TODAY].used_in_run_id is None
    assert rows[OLDER].used_in_run_id == used_run  # previous used date unchanged


def test_older_passing_scene_newer_than_the_used_one_wins_over_a_rejected_newest(world):
    used_run = _add_run("ok", started_at=NOW - timedelta(days=6))
    _add_row("2026-10-03", used_in_run_id=used_run, assessed_at=NOW - timedelta(days=5))
    world.assessments = [
        _assessment(TODAY, "rejected_cloud", cloud=0.9),
        _assessment(OLDER),
    ]

    _poll(world)

    assert [call[1] for call in world.scan_calls] == [f"{OLDER}T00:00:00+00:00"]
    assert _rows()[OLDER].used_in_run_id is not None
    assert _rows()[TODAY].used_in_run_id is None


def test_min_interval_blocks_a_second_scan_10_minutes_later(world):
    world.assessments = [_assessment(YESTERDAY)]
    _poll(world)
    assert len(world.scan_calls) == 1

    world.assessments = [_assessment(TODAY)]  # a newer passing date appears
    _poll(world, at=NOW + timedelta(minutes=10))
    assert len(world.scan_calls) == 1
    assert _rows()[TODAY].used_in_run_id is None

    _poll(world, at=NOW + timedelta(minutes=61))
    assert [call[1] for call in world.scan_calls][-1] == f"{TODAY}T00:00:00+00:00"
    assert len(world.scan_calls) == 2


def test_errored_scan_leaves_the_date_unused_and_retries_after_the_interval(world):
    world.assessments = [_assessment(TODAY)]
    world.scan_status = "error"
    _poll(world)
    assert len(world.scan_calls) == 1
    assert _rows()[TODAY].used_in_run_id is None
    assert world.refresh_calls == []

    _poll(world, at=NOW + timedelta(minutes=10))  # inside the min interval
    assert len(world.scan_calls) == 1

    world.scan_status = "ok"
    _poll(world, at=NOW + timedelta(minutes=70))
    assert len(world.scan_calls) == 2
    with SessionLocal() as db:
        latest = db.execute(
            select(RasterScanRun).order_by(RasterScanRun.id.desc())
        ).scalars().first()
        assert _rows()[TODAY].used_in_run_id == latest.id


def test_success_marks_the_date_used_and_refreshes_the_sites_once(world):
    world.assessments = [_assessment(TODAY)]
    _poll(world)

    with SessionLocal() as db:
        run = db.execute(select(RasterScanRun)).scalars().one()
        assert run.status == "ok"
        assert _rows()[TODAY].used_in_run_id == run.id
    assert world.refresh_calls == [1]


def test_a_failing_sites_refresh_never_raises_out_of_the_poll(world):
    world.assessments = [_assessment(TODAY)]
    world.refresh_error = RuntimeError("synthetic refresh failure")

    _poll(world)  # must not raise

    assert world.refresh_calls == [1]
    assert _rows()[TODAY].used_in_run_id is not None  # the scan's result stands


def test_settled_dates_are_skipped_on_the_next_poll(world):
    world.assessments = [_assessment(OLDER, "rejected_cloud", cloud=0.7)]
    _poll(world)
    assert world.assess_calls[0]["skip_dates"] == frozenset()

    _poll(world, at=NOW + timedelta(hours=2))
    assert world.assess_calls[1]["skip_dates"] == frozenset({OLDER})


def test_assessment_error_leaves_dates_unassessed_and_starts_nothing(world):
    world.assessments = [_assessment(TODAY)]
    world.assess_error = RuntimeError("synthetic EEException")

    _poll(world)

    assert _rows() == {}
    assert world.scan_calls == []
    assert world.refresh_calls == []


def test_auth_error_during_assessment_starts_nothing(world):
    world.assessments = [_assessment(TODAY)]
    world.assess_error = trigger_module.bridge.GEEAuthError("synthetic auth failure")

    _poll(world)

    assert _rows() == {}
    assert world.scan_calls == []


def test_shutdown_requested_returns_before_assessing(world):
    world.assessments = [_assessment(TODAY)]
    shutdown.request_stop()

    _poll(world)

    assert world.assess_calls == []
    assert world.scan_calls == []
    assert _rows() == {}


def test_used_date_equal_to_newest_passing_means_nothing_to_do(world):
    used_run = _add_run("ok", started_at=NOW - timedelta(days=2))
    _add_row(YESTERDAY, used_in_run_id=used_run, assessed_at=NOW - timedelta(days=1))
    world.assessments = [_assessment(YESTERDAY)]

    _poll(world)

    assert world.scan_calls == []
    assert world.refresh_calls == []


# --------------------------------------------------------------------------
# (a) settling: a date is final only 36 h after its UTC start
# --------------------------------------------------------------------------


def test_unsettled_date_is_reassessed_in_place_and_triggers_once_it_passes(world):
    # Early ingestion: only a cloudy granule of TODAY is in GEE yet.
    world.assessments = [_assessment(TODAY, "rejected_cloud", cloud=0.8)]
    _poll(world)
    assert world.scan_calls == []

    # More granules arrive; TODAY is not settled, so it is re-assessed.
    later = NOW + timedelta(hours=3)
    world.assessments = [_assessment(TODAY, cloud=0.2)]
    _poll(world, at=later)

    assert TODAY not in world.assess_calls[1]["skip_dates"]
    row = _rows()[TODAY]
    assert row.decision == "passed"
    assert row.cloud_fraction == pytest.approx(0.2)
    assert row.reason is None
    assert config_module.as_aware_utc(row.assessed_at) == later
    assert [call[1] for call in world.scan_calls] == [f"{TODAY}T00:00:00+00:00"]


def test_used_unsettled_date_that_still_passes_is_not_scanned_again(world):
    world.assessments = [_assessment(TODAY)]
    _poll(world)
    assert len(world.scan_calls) == 1

    world.assessments = [_assessment(TODAY, cloud=0.05)]
    _poll(world, at=NOW + timedelta(hours=5))

    assert TODAY not in world.assess_calls[1]["skip_dates"]  # re-assessed...
    assert _rows()[TODAY].cloud_fraction == pytest.approx(0.05)
    assert len(world.scan_calls) == 1  # ...but never re-triggered
    assert world.refresh_calls == [1]


def test_settled_means_assessed_at_least_36_hours_after_the_date_began():
    start = datetime(2026, 10, 8, tzinfo=UTC)
    assert trigger_module.is_settled("2026-10-08", start + timedelta(hours=36))
    assert not trigger_module.is_settled(
        "2026-10-08", start + timedelta(hours=36) - timedelta(seconds=1)
    )
    # SQLite hands back naive datetimes; they are UTC.
    assert trigger_module.is_settled("2026-10-08", datetime(2026, 10, 9, 12, 0))


def test_a_date_assessed_too_early_stays_out_of_skip_dates(world):
    _add_row(YESTERDAY, "rejected_cloud", assessed_at=NOW - timedelta(seconds=1))
    _add_row(OLDER, "rejected_cloud", assessed_at=NOW - timedelta(days=2))

    _poll(world)

    assert world.assess_calls[0]["skip_dates"] == frozenset({OLDER})


# --------------------------------------------------------------------------
# (b) same sampling as the raster; window start
# --------------------------------------------------------------------------


def test_assessment_uses_the_raster_scan_scale_and_the_study_polygon(world, monkeypatch):
    monkeypatch.setattr(trigger_module, "RASTER_SCAN_SCALE_M", 100)
    _poll(world)
    call = world.assess_calls[0]
    assert call["scale_m"] == 100
    assert call["polygon"] == trigger_module._study_area.STUDY_AREA_POLYGON_LATLNG


def test_window_starts_at_the_lookback_or_the_newest_used_date_if_later(world):
    _poll(world)
    assert world.assess_calls[-1]["since"] == "2026-09-29"  # NOW - 10 days

    used_run = _add_run("ok", started_at=NOW - timedelta(days=4))
    _add_row(OLDER, used_in_run_id=used_run, assessed_at=NOW - timedelta(days=3))
    _poll(world, at=NOW + timedelta(hours=2))
    assert world.assess_calls[-1]["since"] == OLDER


# --------------------------------------------------------------------------
# (d) consumption rules carried over from the cooldown flow
# --------------------------------------------------------------------------


def test_no_data_scan_consumes_its_date_and_is_not_retried(world):
    world.assessments = [_assessment(TODAY)]
    world.scan_status = "no_data"
    _poll(world)
    assert _rows()[TODAY].used_in_run_id is not None
    assert world.refresh_calls == []  # nothing new to describe

    _poll(world, at=NOW + timedelta(hours=3))
    assert len(world.scan_calls) == 1


def test_rejected_scene_never_consumes_a_trigger(world):
    world.assessments = [_assessment(TODAY, "rejected_no_water", cloud=None, water=12,
                                     reason="12 unmasked water pixels < 1000")]
    _poll(world)
    _poll(world, at=NOW + timedelta(hours=3))
    assert world.scan_calls == []
    assert _rows()[TODAY].used_in_run_id is None


def test_live_running_scan_blocks_and_a_stale_one_does_not(world):
    world.assessments = [_assessment(TODAY)]
    _add_run("running", started_at=NOW - timedelta(minutes=10))
    _poll(world)
    assert world.scan_calls == []

    _clear()
    _add_run("running", started_at=NOW - timedelta(days=2))  # crashed process
    _poll(world)
    assert len(world.scan_calls) == 1


def test_shutdown_stopped_bootstrap_does_not_count_as_an_attempt(world):
    world.assessments = [_assessment(TODAY)]
    _add_run("error", started_at=NOW - timedelta(minutes=10),
             source_metadata={"bootstrap_mode": True, "search_stopped": "shutdown"})
    _poll(world)
    assert len(world.scan_calls) == 1


def test_budget_stopped_bootstrap_still_counts_for_the_min_interval(world):
    world.assessments = [_assessment(TODAY)]
    _add_run("error", started_at=NOW - timedelta(minutes=10),
             source_metadata={"bootstrap_mode": True, "search_stopped": "budget"})
    _poll(world)
    assert world.scan_calls == []


def test_concurrent_scan_refusal_is_logged_not_raised(world, monkeypatch):
    world.assessments = [_assessment(TODAY)]

    def refuse(*_args, **_kwargs):
        raise scan_module.ConcurrentRasterScanError("synthetic: another scan is live")

    monkeypatch.setattr(trigger_module, "run_raster_scan", refuse)
    _poll(world)
    assert _rows()[TODAY].used_in_run_id is None
    assert world.refresh_calls == []


def test_shutdown_between_assessment_and_scan_stores_but_does_not_scan(world, monkeypatch):
    world.assessments = [_assessment(TODAY)]
    real_assess = trigger_module.bridge.assess_new_scenes

    def assess_then_stop(*args, **kwargs):
        result = real_assess(*args, **kwargs)
        shutdown.request_stop()
        return result

    monkeypatch.setattr(trigger_module.bridge, "assess_new_scenes", assess_then_stop)
    _poll(world)

    assert _rows()[TODAY].decision == "passed"
    assert world.scan_calls == []


# --------------------------------------------------------------------------
# (e) sites refresh
# --------------------------------------------------------------------------


def test_sites_refresh_skipped_when_shutdown_is_requested_during_the_scan(world, monkeypatch):
    world.assessments = [_assessment(TODAY)]
    real_scan = trigger_module.run_raster_scan

    def scan_then_stop(*args, **kwargs):
        run = real_scan(*args, **kwargs)
        shutdown.request_stop()
        return run

    monkeypatch.setattr(trigger_module, "run_raster_scan", scan_then_stop)
    _poll(world)

    assert len(world.scan_calls) == 1
    assert world.refresh_calls == []


def test_sites_refresh_not_called_after_an_errored_scan(world):
    world.assessments = [_assessment(TODAY)]
    world.scan_status = "error"
    _poll(world)
    assert world.refresh_calls == []


def test_refresh_sites_after_scan_calls_the_real_scheduler_refresh(monkeypatch):
    calls = []
    monkeypatch.setattr(scheduler_module, "refresh_grid", lambda: calls.append(1))
    shutdown.clear_stop()
    trigger_module.refresh_sites_after_scan()
    assert calls == [1]


# --------------------------------------------------------------------------
# scan.py: the real run_raster_scan marks the date (synthetic imagery)
# --------------------------------------------------------------------------


@pytest.fixture()
def real_scan(world, tmp_path, monkeypatch):
    from src.raster_scan import storage
    from tests.test_raster_scan_scan import fake_arrays, fake_composite

    monkeypatch.setattr(storage, "RASTER_BLOB_ROOT", tmp_path)
    monkeypatch.setattr(scan_module.bridge, "build_index_composite",
                        lambda *a, **k: fake_composite())
    monkeypatch.setattr(scan_module.bridge, "download_composite_arrays",
                        lambda *a, **k: fake_arrays())
    # A prior ok run, so the scan is a normal (non-bootstrap) one.
    _add_run("ok", started_at=datetime.now(UTC) - timedelta(days=3))
    return scan_module.run_raster_scan


def test_real_ok_scan_sets_used_in_run_id_for_its_trigger_date(real_scan):
    _add_row(TODAY)
    with SessionLocal() as db:
        run = real_scan(db, TODAY, trigger_scene_timestamp=f"{TODAY}T00:00:00+00:00")
        assert run.status == "ok"
        run_id = run.id
    assert _rows()[TODAY].used_in_run_id == run_id


def test_real_auth_failed_scan_leaves_its_date_unused(real_scan, monkeypatch):
    _add_row(TODAY)

    def auth_fail(*_args, **_kwargs):
        raise scan_module.bridge.GEEAuthError("synthetic auth failure")

    monkeypatch.setattr(scan_module.bridge, "build_index_composite", auth_fail)
    with SessionLocal() as db:
        run = real_scan(db, TODAY, trigger_scene_timestamp=f"{TODAY}T00:00:00+00:00")
        assert run.status == "error"
    assert _rows()[TODAY].used_in_run_id is None


def test_real_scan_without_a_trigger_or_row_touches_no_assessment(real_scan):
    _add_row(TODAY)
    with SessionLocal() as db:
        assert real_scan(db, TODAY).status == "ok"
        # A trigger date nobody assessed creates no row.
        assert real_scan(
            db, TODAY, allow_concurrent=True,
            trigger_scene_timestamp="2026-10-01T00:00:00+00:00",
        ).status == "ok"
    rows = _rows()
    assert set(rows) == {TODAY}
    assert rows[TODAY].used_in_run_id is None


# --------------------------------------------------------------------------
# Schema and configuration
# --------------------------------------------------------------------------


def test_scene_assessments_table_has_the_spec_columns(client):
    columns = {c["name"]: c for c in inspect(engine).get_columns("scene_assessments")}
    assert set(columns) == {
        "acquisition_date", "cloud_fraction", "water_pixels", "decision",
        "reason", "assessed_at", "used_in_run_id",
    }
    assert columns["cloud_fraction"]["nullable"]
    assert columns["reason"]["nullable"]
    assert columns["used_in_run_id"]["nullable"]
    pk = inspect(engine).get_pk_constraint("scene_assessments")["constrained_columns"]
    assert pk == ["acquisition_date"]


def test_latest_scene_config_defaults():
    assert config_module.RASTER_SCAN_POLL_INTERVAL_HOURS == 1
    assert config_module.RASTER_SCAN_MIN_INTERVAL_HOURS == 1
    # Still readable for existing .env files; no longer gates a new scene.
    assert config_module.RASTER_SCAN_COOLDOWN_HOURS == 20


def test_poll_no_longer_calls_the_old_cooldown_gate(world, monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("should_trigger_scan must not be called")

    monkeypatch.setattr(trigger_module, "should_trigger_scan", forbidden)
    calls = []
    monkeypatch.setattr(trigger_module.bridge, "get_newest_scene_timestamp",
                        lambda *a: calls.append(a))
    world.assessments = [_assessment(TODAY)]
    _poll(world)
    assert len(world.scan_calls) == 1
    assert calls == []
