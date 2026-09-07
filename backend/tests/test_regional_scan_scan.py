"""Integration test for run_scan() -- real DB (isolated SQLite, via the
`client` fixture), monkeypatched bridge.detect() so no live GEE call
happens (mirrors backend/tests/test_scheduler.py's pattern)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from src import regional_scan
from src.db import SessionLocal
from src.db_models import RegionalScanCluster, RegionalScanPoint, RegionalScanRun
from src.regional_scan import scan as scan_module


def _fake_detect_all_ok_indices(lat, lng, date):
    """Real spectral index values with no anomaly statistic."""
    return {
        "status": "ok",
        "index_used": "ndci", "index_values": {"ndci": 0.3}, "reason": None,
    }


def test_scan_reads_every_grid_point_at_the_target_date_and_names_no_scene_policy(client, monkeypatch):
    """The scan asks detect() for a date and nothing else: which scene
    answers for that date is one system-wide rule in data-pipeline, not a
    per-caller argument the scan could set differently."""
    calls = []

    def latest_reading(lat, lng, date, *args, **kwargs):
        calls.append((lat, lng, date, args, kwargs))
        return {
            "status": "ok", "index_used": "ndci", "index_values": {"ndci": -0.2},
            "actual_date": "2026-08-20", "reason": None,
        }

    monkeypatch.setattr(scan_module.bridge, "detect", latest_reading)
    with SessionLocal() as db:
        run = scan_module.run_scan(db, "2026-09-06", grid_spacing_km=20.0)
        assert run.count_ok == run.total_points > 0
        assert len(calls) == run.total_points
        assert all(
            date == "2026-09-06" and args == () and kwargs == {}
            for _, _, date, args, kwargs in calls
        )
        points = db.execute(select(RegionalScanPoint)).scalars().all()
        assert {(p.lat, p.lng) for p in points} == {(lat, lng) for lat, lng, _, _, _ in calls}
        assert all(p.actual_date == "2026-08-20" and p.index_values == {"ndci": -0.2} for p in points)


def test_run_scan_persists_indices_with_no_scores_tiers_or_clusters(client, monkeypatch):
    monkeypatch.setattr(scan_module.bridge, "detect", _fake_detect_all_ok_indices)

    db = SessionLocal()
    try:
        run = scan_module.run_scan(db, "2026-08-15", grid_spacing_km=20.0)

        assert run.status == "ok"
        assert run.total_points > 0
        assert run.count_ok == run.total_points
        assert run.count_error == 0

        points = db.execute(select(RegionalScanPoint)).scalars().all()
        assert len(points) == run.total_points
        assert all(p.status == "ok" for p in points)
        assert all(p.threshold_tier is None for p in points)
        assert all(p.spatial_anomaly_z is None for p in points)
        assert all(p.index_values == {"ndci": 0.3} for p in points)

        clusters = db.execute(
            select(RegionalScanCluster).where(RegionalScanCluster.run_id == run.id)
        ).scalars().all()
        assert clusters == []
    finally:
        db.close()


def _fake_detect_no_imagery(lat, lng, date):
    return {
        "status": "no_imagery",
        "index_used": "ndci", "index_values": None, "reason": "forced for test",
    }


def test_run_scan_no_imagery_points_are_stored_not_dropped(client, monkeypatch):
    monkeypatch.setattr(scan_module.bridge, "detect", _fake_detect_no_imagery)

    db = SessionLocal()
    try:
        run = scan_module.run_scan(db, "2026-08-15", grid_spacing_km=20.0)

        assert run.status == "ok"
        assert run.count_no_imagery == run.total_points
        assert run.count_ok == 0

        points = db.execute(select(RegionalScanPoint)).scalars().all()
        assert len(points) == run.total_points
        assert all(p.status == "no_imagery" for p in points)
        assert all(p.threshold_tier is None for p in points)

        clusters = db.execute(
            select(RegionalScanCluster).where(RegionalScanCluster.run_id == run.id)
        ).scalars().all()
        assert clusters == []
    finally:
        db.close()


def test_run_scan_aborts_on_gee_auth_error_without_touching_prior_points(client, monkeypatch):
    # First, a real successful run leaves known-good points behind.
    monkeypatch.setattr(scan_module.bridge, "detect", _fake_detect_all_ok_indices)
    db = SessionLocal()
    try:
        good_run = scan_module.run_scan(db, "2026-08-15", grid_spacing_km=20.0)
        prior_point_count = db.execute(select(RegionalScanPoint)).scalars().all()
        assert len(prior_point_count) == good_run.total_points

        # Then, a second run's very first detect() call raises
        # GEEAuthError -- must abort without discarding the prior points.
        def _raise(*_a, **_k):
            raise scan_module.bridge.GEEAuthError("forced for test")

        monkeypatch.setattr(scan_module.bridge, "detect", _raise)
        aborted_run = scan_module.run_scan(db, "2026-08-16", grid_spacing_km=20.0)

        assert aborted_run.status == "error"
        assert aborted_run.completed_at is not None

        still_there = db.execute(select(RegionalScanPoint)).scalars().all()
        assert len(still_there) == good_run.total_points
    finally:
        db.close()


def test_run_scan_gee_auth_error_mid_loop_does_not_overwrite_earlier_points_this_run(client, monkeypatch):
    """Stronger version of the existing abort test: GEEAuthError fires on
    the THIRD point, not the first -- points 1-2 must NOT be silently
    overwritten with this aborted run's (untrustworthy) values just
    because they were processed before the failure. The whole run is
    untrustworthy, not just the points after the failure point."""
    monkeypatch.setattr(scan_module.bridge, "detect", _fake_detect_all_ok_indices)

    db = SessionLocal()
    try:
        good_run = scan_module.run_scan(db, "2026-08-15", grid_spacing_km=20.0)
        good_points = {
            p.point_id: (p.status, p.index_values)
            for p in db.execute(select(RegionalScanPoint)).scalars().all()
        }
        assert len(good_points) == good_run.total_points

        call_count = {"n": 0}

        def _raise_on_third_call(lat, lng, date):
            # Change real index values so an accidental partial commit
            # remains detectable after an authentication failure.
            call_count["n"] += 1
            if call_count["n"] >= 3:
                raise scan_module.bridge.GEEAuthError("forced for test -- mid-loop")
            return {
                "status": "ok",
                "index_used": "ndci", "index_values": {"ndci": 0.9}, "reason": None,
            }

        monkeypatch.setattr(scan_module.bridge, "detect", _raise_on_third_call)
        aborted_run = scan_module.run_scan(db, "2026-08-16", grid_spacing_km=20.0)

        assert aborted_run.status == "error"

        after_points = {
            p.point_id: (p.status, p.index_values)
            for p in db.execute(select(RegionalScanPoint)).scalars().all()
        }
        assert after_points == good_points, (
            "points processed before the mid-loop GEEAuthError were overwritten "
            "with this aborted run's data -- the whole run is untrustworthy, not "
            "just the points after the failure point"
        )
    finally:
        db.close()


def _fake_detect_with_scene_date(lat, lng, date):
    """detect() resolving a scene 6 days before the scan's target date --
    the normal case, not an edge case: the scan searches backward for
    each point's latest usable scene, so points in one scan are
    routinely backed by scenes of different vintages."""
    return {
        "status": "ok",
        "index_used": "ndci", "index_values": {"ndci": 0.3}, "reason": None,
        "actual_date": "2026-08-09",
    }


def test_run_scan_persists_per_point_actual_date(client, monkeypatch):
    monkeypatch.setattr(scan_module.bridge, "detect", _fake_detect_with_scene_date)

    db = SessionLocal()
    try:
        run = scan_module.run_scan(db, "2026-08-15", grid_spacing_km=20.0)

        points = db.execute(
            select(RegionalScanPoint).where(RegionalScanPoint.run_id == run.id)
        ).scalars().all()
        assert len(points) == run.total_points
        assert all(p.actual_date == "2026-08-09" for p in points)
        # Stored as the scene's own date, never overwritten with the run's
        # target date.
        assert all(p.actual_date != run.date_used for p in points)
    finally:
        db.close()


def test_run_scan_persists_null_actual_date_when_no_scene_resolved(client, monkeypatch):
    """no_imagery means no scene existed at all for this point -- the
    column must stay null rather than be backfilled with the scan date."""
    monkeypatch.setattr(scan_module.bridge, "detect", _fake_detect_no_imagery)

    db = SessionLocal()
    try:
        run = scan_module.run_scan(db, "2026-08-15", grid_spacing_km=20.0)

        points = db.execute(
            select(RegionalScanPoint).where(RegionalScanPoint.run_id == run.id)
        ).scalars().all()
        assert len(points) == run.total_points
        assert all(p.actual_date is None for p in points)
    finally:
        db.close()


def test_run_scan_per_point_error_leaves_actual_date_null(client, monkeypatch):
    """The per-point error dict scan.py builds itself carries no scene
    date at all -- reading it must not raise, and must persist null."""

    def _raise_non_auth(lat, lng, date):
        raise RuntimeError("forced for test -- per-point failure")

    monkeypatch.setattr(scan_module.bridge, "detect", _raise_non_auth)

    db = SessionLocal()
    try:
        run = scan_module.run_scan(db, "2026-08-15", grid_spacing_km=20.0)

        assert run.count_error == run.total_points
        points = db.execute(
            select(RegionalScanPoint).where(RegionalScanPoint.run_id == run.id)
        ).scalars().all()
        assert all(p.status == "error" for p in points)
        assert all(p.actual_date is None for p in points)
    finally:
        db.close()


# --------------------------------------------------------------------------
# Per-cluster scene-freshness range (spec §12).
#
# Clustering merges cells on grid adjacency alone, so a cluster can hold
# cells backed by Sentinel-2 scenes days apart -- measured spans among
# the 'ok' points of one real scan were 7, 5 and 10 days. run_scan() must
# carry each flagged point's own scene date into cluster_points() and
# persist the resulting range.
# --------------------------------------------------------------------------

_SPAN_SCENE_DATES = ["2026-08-05", "2026-08-15", "2026-08-10"]


def _make_fake_detect_varying_scene_dates():
    """detect() resolving a different scene for successive points, the
    way the per-point latest-usable-scene search behaves.
    Returns (detect_fn, assigned) where `assigned` maps (lat, lng) to the
    scene date handed out, so the test can check the persisted range
    against what was actually returned rather than against a constant."""
    assigned: dict[tuple[float, float], str] = {}

    def _detect(lat, lng, date):
        scene = _SPAN_SCENE_DATES[len(assigned) % len(_SPAN_SCENE_DATES)]
        assigned[(lat, lng)] = scene
        return {
            "status": "ok",
            "index_used": "ndci", "index_values": {"ndci": 0.3}, "reason": None,
            "actual_date": scene,
        }

    return _detect, assigned


def test_run_scan_preserves_mixed_scene_dates_without_creating_clusters(client, monkeypatch):
    fake_detect, assigned = _make_fake_detect_varying_scene_dates()
    monkeypatch.setattr(scan_module.bridge, "detect", fake_detect)

    db = SessionLocal()
    try:
        run = scan_module.run_scan(db, "2026-08-15", grid_spacing_km=20.0)
        assert len(assigned) == run.total_points
        points = db.execute(
            select(RegionalScanPoint).where(RegionalScanPoint.run_id == run.id)
        ).scalars().all()
        assert {p.actual_date for p in points} == set(_SPAN_SCENE_DATES)
        assert all(p.actual_date == assigned[(p.lat, p.lng)] for p in points)
        assert all(p.spatial_anomaly_z is None and p.threshold_tier is None for p in points)
        assert db.execute(select(RegionalScanCluster)).scalars().all() == []
        run_id = run.id
    finally:
        db.close()

    body = client.get("/regional-scan").json()
    assert body["run"]["run_id"] == run_id
    assert body["clusters"] == []
    assert len(body["points"]) == len(assigned)
    assert all(
        point["actual_date"] == assigned[(point["lat"], point["lng"])]
        and point["spatial_anomaly_z"] is None and point["threshold_tier"] is None
        and "anomaly_z" not in point
        for point in body["points"]
    )


def test_scan_keeps_index_reading_without_climatology_through_endpoint(client, monkeypatch):
    """Missing baseline is not an imagery failure: indices stay 'ok' and dated."""
    monkeypatch.setattr(scan_module.bridge, "detect", _fake_detect_with_scene_date)
    db = SessionLocal()
    try:
        run = scan_module.run_scan(db, "2026-08-15", grid_spacing_km=20.0)
        run_id, total_points = run.id, run.total_points
        assert run.count_ok == total_points
        assert run.count_no_climatology == 0
    finally:
        db.close()

    body = client.get("/regional-scan").json()
    assert body["run"]["run_id"] == run_id
    assert len(body["points"]) == total_points
    assert all(
        point["status"] == "ok" and point["index_values"] == {"ndci": 0.3}
        and point["actual_date"] == "2026-08-09"
        and point["spatial_anomaly_z"] is None and point["threshold_tier"] is None
        for point in body["points"]
    )
    assert body["clusters"] == []


# --------------------------------------------------------------------------
# One scan at a time.
#
# Two runs upsert the same RegionalScanPoint rows by point_id, so a
# concurrent pair leaves the table a last-writer-wins mixture of both
# while /regional-scan reports it under one run's metadata, and each
# run's end-of-scan cleanup deletes the other's clusters. The scheduler's
# 20h cooldown already prevented this on its own path; scripts/
# run_regional_scan.py bypasses the cooldown, which is how it happened.
# --------------------------------------------------------------------------


def _running_run(started_at, total_points=501):
    return RegionalScanRun(
        started_at=started_at, completed_at=None, status="running",
        grid_spacing_km=5.0, date_used="2026-09-06", total_points=total_points,
        count_ok=0, count_no_imagery=0, count_no_water_pixels=0,
        count_no_climatology=0, count_error=0,
    )


def _clear_running_rows(db):
    """Tests in this module share one SQLite file, and a row left in
    'running' would block every later run_scan call. Each test below
    starts from a known-clean slate and removes its own fixture row."""
    for row in db.execute(
        select(RegionalScanRun).where(RegionalScanRun.status == "running")
    ).scalars().all():
        db.delete(row)
    db.commit()


def _run_ids(db):
    return {r.id for r in db.execute(select(RegionalScanRun)).scalars().all()}


def test_a_second_scan_refuses_to_start_while_one_is_running(client, monkeypatch):
    """Refused before anything is written: no new run row, no point rows,
    and detect() never called for even one point."""
    calls = []

    def _detect(lat, lng, date):
        calls.append((lat, lng))
        return {"status": "ok", "index_used": "ndci",
                "index_values": {"ndci": 0.3}, "reason": None}

    monkeypatch.setattr(scan_module.bridge, "detect", _detect)
    with SessionLocal() as db:
        _clear_running_rows(db)
        live = _running_run(datetime.now(timezone.utc) - timedelta(minutes=45))
        db.add(live)
        db.commit()
        live_id = live.id
        runs_before = _run_ids(db)
        points_before = len(db.execute(select(RegionalScanPoint)).scalars().all())

        with pytest.raises(scan_module.ConcurrentScanError) as excinfo:
            scan_module.run_scan(db, "2026-09-06", grid_spacing_km=100.0)

        assert str(live_id) in str(excinfo.value)
        assert calls == []
        assert _run_ids(db) == runs_before, "a refused scan must not create a run row"
        assert len(db.execute(select(RegionalScanPoint)).scalars().all()) == points_before
        db.refresh(live)
        assert live.status == "running", "the live run must be left alone"

        _clear_running_rows(db)


def test_a_run_stuck_running_past_the_stale_window_is_expired_and_taken_over(client, monkeypatch):
    """A killed process leaves its row 'running' forever. Without an
    expiry that ghost would block every future scan, so a run older than
    REGIONAL_SCAN_STALE_RUN_HOURS is marked error and the new scan
    proceeds."""
    monkeypatch.setattr(scan_module.bridge, "detect", _fake_detect_all_ok_indices)
    with SessionLocal() as db:
        _clear_running_rows(db)
        stale_age = scan_module.REGIONAL_SCAN_STALE_RUN_HOURS + 1
        ghost = _running_run(datetime.now(timezone.utc) - timedelta(hours=stale_age))
        db.add(ghost)
        db.commit()
        ghost_id = ghost.id

        run = scan_module.run_scan(db, "2026-09-06", grid_spacing_km=100.0)

        assert run.id != ghost_id
        assert run.status == "ok"
        db.refresh(ghost)
        assert ghost.status == "error"
        assert ghost.completed_at is not None, "an expired run must not stay open-ended"


def test_allow_concurrent_bypasses_the_guard(client, monkeypatch):
    """The escape hatch behind scripts/run_regional_scan.py --force, for
    a caller who knows the other run is dead."""
    monkeypatch.setattr(scan_module.bridge, "detect", _fake_detect_all_ok_indices)
    with SessionLocal() as db:
        _clear_running_rows(db)
        db.add(_running_run(datetime.now(timezone.utc)))
        db.commit()

        run = scan_module.run_scan(
            db, "2026-09-06", grid_spacing_km=100.0, allow_concurrent=True,
        )
        assert run.status == "ok"
        assert run.count_ok == run.total_points > 0

        _clear_running_rows(db)
