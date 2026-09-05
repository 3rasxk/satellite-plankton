"""Integration test for run_scan() -- real DB (isolated SQLite, via the
`client` fixture), monkeypatched bridge.detect() so no live GEE call
happens (mirrors backend/tests/test_scheduler.py's pattern)."""

from __future__ import annotations

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
    the normal case, not an edge case: get_sentinel2_bands searches +/-10
    days for the nearest cloud-free scene, so points in one scan are
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
    way the +/-10-day nearest-cloud-free-scene search really behaves.
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
