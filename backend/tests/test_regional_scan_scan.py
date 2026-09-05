"""Integration test for run_scan() -- real DB (isolated SQLite, via the
`client` fixture), monkeypatched bridge.detect() so no live GEE call
happens (mirrors backend/tests/test_scheduler.py's pattern)."""

from __future__ import annotations

from sqlalchemy import select

from src import regional_scan
from src.db import SessionLocal
from src.db_models import RegionalScanCluster, RegionalScanPoint, RegionalScanRun
from src.regional_scan import scan as scan_module


def _fake_detect_all_ok_high_anomaly(lat, lng, date):
    """Every point 'ok' with anomaly_z=2.5 (>= warning_z=2.0 in
    detection/src/config.yaml) -- forces every point flagged, so
    clustering has real work to do."""
    return {
        "status": "ok", "detected": True, "anomaly_z": 2.5,
        "index_used": "ndci", "index_values": {"ndci": 0.3}, "reason": None,
    }


def test_run_scan_persists_points_and_clusters(client, monkeypatch):
    monkeypatch.setattr(scan_module.bridge, "detect", _fake_detect_all_ok_high_anomaly)

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
        assert all(p.threshold_tier == "warning" for p in points)

        clusters = db.execute(
            select(RegionalScanCluster).where(RegionalScanCluster.run_id == run.id)
        ).scalars().all()
        assert len(clusters) >= 1
        assert sum(c.cell_count for c in clusters) == run.total_points
    finally:
        db.close()


def _fake_detect_no_imagery(lat, lng, date):
    return {
        "status": "no_imagery", "detected": False, "anomaly_z": None,
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
    monkeypatch.setattr(scan_module.bridge, "detect", _fake_detect_all_ok_high_anomaly)
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
    monkeypatch.setattr(scan_module.bridge, "detect", _fake_detect_all_ok_high_anomaly)

    db = SessionLocal()
    try:
        good_run = scan_module.run_scan(db, "2026-08-15", grid_spacing_km=20.0)
        good_points = {
            p.point_id: (p.status, p.anomaly_z)
            for p in db.execute(select(RegionalScanPoint)).scalars().all()
        }
        assert len(good_points) == good_run.total_points

        call_count = {"n": 0}

        def _raise_on_third_call(lat, lng, date):
            # Points 1-2 get a DIFFERENT anomaly_z (9.9, not the prior
            # run's 2.5) so that -- if the bug is present and this
            # aborted run's partial upserts get committed anyway -- the
            # overwrite is actually detectable by comparing values below,
            # rather than silently matching the prior run's data by
            # coincidence.
            call_count["n"] += 1
            if call_count["n"] >= 3:
                raise scan_module.bridge.GEEAuthError("forced for test -- mid-loop")
            return {
                "status": "ok", "detected": True, "anomaly_z": 9.9,
                "index_used": "ndci", "index_values": {"ndci": 0.9}, "reason": None,
            }

        monkeypatch.setattr(scan_module.bridge, "detect", _raise_on_third_call)
        aborted_run = scan_module.run_scan(db, "2026-08-16", grid_spacing_km=20.0)

        assert aborted_run.status == "error"

        after_points = {
            p.point_id: (p.status, p.anomaly_z)
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
    the normal case, not an edge case: get_sentinel2_bands searches +/-10
    days for the nearest cloud-free scene, so points in one scan are
    routinely backed by scenes of different vintages."""
    return {
        "status": "ok", "detected": True, "anomaly_z": 2.5,
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
