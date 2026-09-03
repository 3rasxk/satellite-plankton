"""GET /regional-scan -- pure cache read, never calls GEE (spec §7).
Seeds RegionalScanRun/Point/Cluster rows directly via the DB session
(mirrors test_scheduler.py's direct-DB-seeding style) rather than
running a real scan."""

from __future__ import annotations

from datetime import datetime, timezone

from src.db import SessionLocal
from src.db_models import RegionalScanCluster, RegionalScanPoint, RegionalScanRun


def test_regional_scan_empty_state_before_any_run(client):
    resp = client.get("/regional-scan")
    assert resp.status_code == 200
    body = resp.json()
    assert body["run"] is None
    assert body["points"] == []
    assert body["clusters"] == []
    assert "disclaimer" in body
    assert "caveat" in body


def test_regional_scan_returns_latest_run_points_and_clusters(client):
    db = SessionLocal()
    try:
        run = RegionalScanRun(
            started_at=datetime(2026, 8, 31, 6, 0, 0, tzinfo=timezone.utc),
            completed_at=datetime(2026, 8, 31, 6, 5, 0, tzinfo=timezone.utc),
            status="ok", grid_spacing_km=5.0, date_used="2026-08-31",
            newest_scene_date="2026-08-30T10:00:00+00:00", total_points=2,
            count_ok=2, count_no_imagery=0, count_no_water_pixels=0,
            count_no_climatology=0, count_error=0,
        )
        db.add(run)
        db.commit()
        db.refresh(run)

        db.add(RegionalScanPoint(
            point_id="0_0", lat=13.0, lng=100.5, row_idx=0, col_idx=0,
            status="ok", index_values={"ndci": 0.2}, anomaly_z=2.5,
            threshold_tier="warning", run_id=run.id,
        ))
        db.add(RegionalScanPoint(
            point_id="0_1", lat=13.05, lng=100.5, row_idx=0, col_idx=1,
            status="ok", index_values={"ndci": 0.19}, anomaly_z=2.4,
            threshold_tier="warning", run_id=run.id,
        ))
        db.add(RegionalScanCluster(
            run_id=run.id, centroid_lat=13.025, centroid_lng=100.5, cell_count=2,
            mean_anomaly_z=2.45, max_anomaly_z=2.5, threshold_tier="warning",
            member_point_ids=["0_0", "0_1"],
        ))
        db.commit()

        resp = client.get("/regional-scan")
        assert resp.status_code == 200
        body = resp.json()

        assert body["run"]["run_id"] == run.id
        assert body["run"]["status"] == "ok"
        assert body["run"]["total_points"] == 2

        assert len(body["points"]) == 2
        assert {p["point_id"] for p in body["points"]} == {"0_0", "0_1"}

        assert len(body["clusters"]) == 1
        assert body["clusters"][0]["cell_count"] == 2
        assert set(body["clusters"][0]["member_point_ids"]) == {"0_0", "0_1"}
    finally:
        db.close()


def test_root_route_lists_regional_scan_endpoint(client):
    resp = client.get("/")
    assert "/regional-scan" in resp.json()["endpoints"]


def test_regional_scan_serves_last_good_clusters_when_latest_run_aborted(client):
    """Reproduces the abort-path bug: RegionalScanCluster is a whole-table
    latest-snapshot (deleted and reinserted only on a successful run --
    see its docstring in db_models.py), not a per-run history table. On a
    GEEAuthError abort, run_scan() rolls back and returns before ever
    reaching the cluster delete-and-reinsert code (scan.py), so cluster
    rows always belong to whichever run last completed successfully --
    never to an aborted run's id. If GET /regional-scan filters clusters
    by run_id == latest_run.id, an aborted-latest-run state wrongly
    returns clusters: [] even though real, still-current cluster rows
    exist. The fix: query clusters unfiltered, exactly like points."""
    db = SessionLocal()
    try:
        good_run = RegionalScanRun(
            started_at=datetime(2026, 8, 31, 6, 0, 0, tzinfo=timezone.utc),
            completed_at=datetime(2026, 8, 31, 6, 5, 0, tzinfo=timezone.utc),
            status="ok", grid_spacing_km=5.0, date_used="2026-08-31",
            newest_scene_date="2026-08-30T10:00:00+00:00", total_points=2,
            count_ok=2, count_no_imagery=0, count_no_water_pixels=0,
            count_no_climatology=0, count_error=0,
        )
        db.add(good_run)
        db.commit()
        db.refresh(good_run)

        db.add(RegionalScanPoint(
            point_id="9_0", lat=13.0, lng=100.5, row_idx=9, col_idx=0,
            status="ok", index_values={"ndci": 0.2}, anomaly_z=2.5,
            threshold_tier="warning", run_id=good_run.id,
        ))
        db.add(RegionalScanPoint(
            point_id="9_1", lat=13.05, lng=100.5, row_idx=9, col_idx=1,
            status="ok", index_values={"ndci": 0.19}, anomaly_z=2.4,
            threshold_tier="warning", run_id=good_run.id,
        ))
        db.add(RegionalScanCluster(
            run_id=good_run.id, centroid_lat=13.025, centroid_lng=100.5, cell_count=2,
            mean_anomaly_z=2.45, max_anomaly_z=2.5, threshold_tier="warning",
            member_point_ids=["9_0", "9_1"],
        ))
        db.commit()

        # Simulate a later run that aborted with GEEAuthError: a new
        # RegionalScanRun row with status='error' and no completed_at,
        # but -- matching run_scan()'s actual abort-path behavior -- no
        # new points/clusters written for it at all (db.rollback() fires
        # before the loop's per-point writes are committed, and the
        # cluster delete-and-reinsert code is never reached).
        aborted_run = RegionalScanRun(
            started_at=datetime(2026, 8, 31, 12, 0, 0, tzinfo=timezone.utc),
            completed_at=datetime(2026, 8, 31, 12, 0, 5, tzinfo=timezone.utc),
            status="error", grid_spacing_km=5.0, date_used="2026-08-31",
            newest_scene_date="2026-08-30T10:00:00+00:00", total_points=2,
            count_ok=0, count_no_imagery=0, count_no_water_pixels=0,
            count_no_climatology=0, count_error=0,
        )
        db.add(aborted_run)
        db.commit()
        db.refresh(aborted_run)

        resp = client.get("/regional-scan")
        assert resp.status_code == 200
        body = resp.json()

        # The latest run (by started_at) is the aborted one.
        assert body["run"]["run_id"] == aborted_run.id
        assert body["run"]["status"] == "error"

        # Points are correctly unfiltered -- the last-good snapshot's rows
        # are still present (table also carries rows from earlier tests in
        # this file, hence checking for presence, not an exact count).
        assert {"9_0", "9_1"}.issubset({p["point_id"] for p in body["points"]})

        # Clusters must ALSO still show the last-good snapshot (it belongs
        # to good_run.id, not aborted_run.id) -- not be wrongly emptied
        # just because the latest run row happens to be an aborted one.
        assert any(
            c["cell_count"] == 2 and set(c["member_point_ids"]) == {"9_0", "9_1"}
            for c in body["clusters"]
        ), f"expected the good_run cluster among clusters, got {body['clusters']}"
    finally:
        db.close()
