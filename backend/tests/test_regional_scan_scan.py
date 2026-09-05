"""Integration test for run_scan() -- real DB (isolated SQLite, via the
`client` fixture), monkeypatched bridge.detect() so no live GEE call
happens (mirrors backend/tests/test_scheduler.py's pattern)."""

from __future__ import annotations

from datetime import date

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
            "status": "ok", "detected": True, "anomaly_z": 2.5,
            "index_used": "ndci", "index_values": {"ndci": 0.3}, "reason": None,
            "actual_date": scene,
        }

    return _detect, assigned


def test_run_scan_persists_cluster_scene_date_range(client, monkeypatch):
    fake_detect, assigned = _make_fake_detect_varying_scene_dates()
    monkeypatch.setattr(scan_module.bridge, "detect", fake_detect)

    db = SessionLocal()
    try:
        run = scan_module.run_scan(db, "2026-08-15", grid_spacing_km=20.0)
        assert len(assigned) == run.total_points

        points = db.execute(
            select(RegionalScanPoint).where(RegionalScanPoint.run_id == run.id)
        ).scalars().all()
        date_by_point_id = {p.point_id: p.actual_date for p in points}

        clusters = db.execute(
            select(RegionalScanCluster).where(RegionalScanCluster.run_id == run.id)
        ).scalars().all()
        assert len(clusters) >= 1

        for cluster in clusters:
            member_dates = sorted(date_by_point_id[pid] for pid in cluster.member_point_ids)
            assert cluster.oldest_scene_date == member_dates[0]
            assert cluster.newest_scene_date == member_dates[-1]
            expected_span = (
                date.fromisoformat(member_dates[-1]) - date.fromisoformat(member_dates[0])
            ).days
            assert cluster.scene_date_span_days == expected_span

        # This fixture hands out three different dates spanning 10 days,
        # so at least one cluster must actually report a mixed vintage --
        # otherwise the assertions above would pass vacuously on span 0.
        assert any(c.scene_date_span_days > 0 for c in clusters), (
            "expected at least one mixed-vintage cluster, got spans "
            f"{[c.scene_date_span_days for c in clusters]}"
        )
        # And the cluster is kept whole: every flagged point is still in
        # exactly one cluster, none dropped or split off for being stale.
        assert sum(c.cell_count for c in clusters) == run.total_points
    finally:
        db.close()


def test_run_scan_persists_null_cluster_range_when_a_member_has_no_scene_date(
    client, monkeypatch
):
    """_fake_detect_all_ok_high_anomaly returns no 'actual_date' key at
    all. Every cluster's range must come back null rather than be
    invented from the run's target date."""
    monkeypatch.setattr(scan_module.bridge, "detect", _fake_detect_all_ok_high_anomaly)

    db = SessionLocal()
    try:
        run = scan_module.run_scan(db, "2026-08-15", grid_spacing_km=20.0)

        clusters = db.execute(
            select(RegionalScanCluster).where(RegionalScanCluster.run_id == run.id)
        ).scalars().all()
        assert len(clusters) >= 1
        for cluster in clusters:
            assert cluster.oldest_scene_date is None
            assert cluster.newest_scene_date is None
            assert cluster.scene_date_span_days is None
            # Never backfilled from the run's requested target date.
            assert cluster.newest_scene_date != run.date_used
    finally:
        db.close()


def test_run_scan_serves_cluster_scene_range_through_the_endpoint(client, monkeypatch):
    """End to end: run_scan() -> DB -> GET /regional-scan."""
    fake_detect, _assigned = _make_fake_detect_varying_scene_dates()
    monkeypatch.setattr(scan_module.bridge, "detect", fake_detect)

    db = SessionLocal()
    try:
        run = scan_module.run_scan(db, "2026-08-15", grid_spacing_km=20.0)
        clusters = db.execute(
            select(RegionalScanCluster).where(RegionalScanCluster.run_id == run.id)
        ).scalars().all()
        expected = {
            tuple(sorted(c.member_point_ids)): (
                c.oldest_scene_date, c.newest_scene_date, c.scene_date_span_days,
            )
            for c in clusters
        }
    finally:
        db.close()

    body = client.get("/regional-scan").json()
    served = {
        tuple(sorted(c["member_point_ids"])): (
            c["oldest_scene_date"], c["newest_scene_date"], c["scene_date_span_days"],
        )
        for c in body["clusters"]
    }
    for members, range_fields in expected.items():
        assert served[members] == range_fields


# --------------------------------------------------------------------------
# 'no_climatology' carries a REAL scene date all the way out.
#
# That status is reached only after get_sentinel2_bands already returned
# a scene (the gap is in the MODIS climatology, not the imagery), so
# unlike 'no_imagery' / 'no_water_pixels' it must never be null here.
# Covered at the detect() unit level in
# detection/tests/test_detect_actual_date.py; this is the missing
# integration leg through run_scan() and GET /regional-scan.
# --------------------------------------------------------------------------

_NO_CLIMATOLOGY_SCENE_DATE = "2026-08-09"


def _fake_detect_no_climatology_with_scene_date(lat, lng, date):
    return {
        "status": "no_climatology", "detected": False, "anomaly_z": None,
        "index_used": "ndci", "index_values": {"ndci": 0.28},
        "reason": "no_climatology_data_for_this_location_and_window",
        "actual_date": _NO_CLIMATOLOGY_SCENE_DATE,
    }


def test_no_climatology_keeps_its_real_scene_date_through_scan_and_endpoint(
    client, monkeypatch
):
    monkeypatch.setattr(
        scan_module.bridge, "detect", _fake_detect_no_climatology_with_scene_date
    )

    db = SessionLocal()
    try:
        run = scan_module.run_scan(db, "2026-08-15", grid_spacing_km=20.0)
        run_id, total_points = run.id, run.total_points

        assert run.count_no_climatology == run.total_points
        assert run.count_ok == 0

        points = db.execute(
            select(RegionalScanPoint).where(RegionalScanPoint.run_id == run.id)
        ).scalars().all()
        assert len(points) == run.total_points
        assert all(p.status == "no_climatology" for p in points)
        # No anomaly baseline, so no tier and no clustering -- but the
        # imagery behind index_values is real and dated.
        assert all(p.threshold_tier is None for p in points)
        assert all(p.index_values == {"ndci": 0.28} for p in points)
        assert all(p.actual_date == _NO_CLIMATOLOGY_SCENE_DATE for p in points)
        assert all(p.actual_date != run.date_used for p in points)
    finally:
        db.close()

    body = client.get("/regional-scan").json()
    assert body["run"]["run_id"] == run_id
    assert body["run"]["count_no_climatology"] == total_points
    no_climatology_points = [p for p in body["points"] if p["status"] == "no_climatology"]
    assert len(no_climatology_points) == total_points
    assert all(
        p["actual_date"] == _NO_CLIMATOLOGY_SCENE_DATE for p in no_climatology_points
    ), (
        "no_climatology happens after imagery succeeded, so it must carry a "
        "real scene date out of the API -- not null"
    )
