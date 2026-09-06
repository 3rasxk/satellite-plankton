"""GET /regional-scan -- pure cache read, never calls GEE (spec §7).
Seeds RegionalScanRun/Point/Cluster rows directly via the DB session
(mirrors test_scheduler.py's direct-DB-seeding style) rather than
running a real scan."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.db import SessionLocal
from src.db_models import RegionalScanCluster, RegionalScanPoint, RegionalScanRun
from src.regional_scan.grid import generate_scan_grid
from src import _detection as bridge, config


def test_regional_scan_shows_planned_grid_before_any_run(client, monkeypatch):
    from src import _detection as bridge

    def forbid_live_read(*args, **kwargs):
        raise AssertionError("The map geometry endpoint must not fetch imagery")

    monkeypatch.setattr(bridge, "detect", forbid_live_read)
    resp = client.get("/regional-scan")
    assert resp.status_code == 200
    body = resp.json()
    assert body["run"] is None
    assert body["snapshot_date_used"] is None
    grid = generate_scan_grid(config.REGIONAL_SCAN_GRID_SPACING_KM)
    assert len(body["points"]) == len(grid)
    assert body["grid_spacing_km"] == config.REGIONAL_SCAN_GRID_SPACING_KM
    # The effective ceiling in force, read from the one place that owns it
    # (data-pipeline via src/_detection.py) rather than a literal here --
    # an env override must change the reported value, not fail the suite.
    assert body["max_scene_age_days"] == bridge.default_max_scene_age_days()
    assert [(p["point_id"], p["lat"], p["lng"]) for p in body["points"]] == [
        (p["point_id"], p["lat"], p["lng"]) for p in grid
    ]
    assert all(p["status"] == "no_data_yet" for p in body["points"])
    assert all(
        p["index_values"] is None and p["actual_date"] is None
        and p["spatial_anomaly_z"] is None and p["threshold_tier"] is None
        for p in body["points"]
    )
    with SessionLocal() as db:
        assert db.query(RegionalScanRun).count() == 0
        assert db.query(RegionalScanPoint).count() == 0
    assert body["clusters"] == []
    assert "disclaimer" in body
    assert "caveat" in body


@pytest.mark.parametrize("status", ["running", "error"])
def test_retained_snapshot_keeps_its_target_when_a_later_attempt_starts(client, monkeypatch, status):
    from src.regional_scan import scan as scan_module

    monkeypatch.setattr(scan_module, "generate_scan_grid", lambda _: [
        {"point_id": "1_62", "row_idx": 1, "col_idx": 62, "lat": 6.55, "lng": 102.03},
    ])
    monkeypatch.setattr(scan_module.bridge, "detect", lambda *args: {
        "status": "ok", "index_values": {"ndci": -0.2}, "actual_date": "2026-08-23",
    })
    with SessionLocal() as db:
        saved_run = scan_module.run_scan(db, "2026-09-06", 5.0)
        saved_run.started_at = datetime(2026, 9, 6, 6, 0, tzinfo=timezone.utc)
        attempt = RegionalScanRun(
            started_at=datetime(2026, 9, 7, 6, 0, tzinfo=timezone.utc),
            status=status, grid_spacing_km=5.0, date_used="2026-09-07", total_points=9119,
        )
        db.add(attempt)
        db.commit()
        try:
            body = client.get("/regional-scan").json()
            assert body["run"]["run_id"] == attempt.id
            assert body["run"]["date_used"] == "2026-09-07"
            assert body["snapshot_date_used"] == "2026-09-06"
            assert body["points"][0]["actual_date"] == "2026-08-23"
            assert body["points"][0]["index_values"] == {"ndci": -0.2}
        finally:
            db.query(RegionalScanPoint).filter_by(run_id=saved_run.id).delete()
            db.delete(attempt)
            db.delete(saved_run)
            db.commit()


@pytest.mark.parametrize("status", ["running", "error"])
def test_first_scan_without_a_snapshot_still_shows_the_whole_grid(client, status):
    grid = generate_scan_grid(5.0)
    with SessionLocal() as db:
        run = RegionalScanRun(
            started_at=datetime(2026, 8, 30, 6, 0, tzinfo=timezone.utc),
            status=status, grid_spacing_km=5.0, date_used="2026-08-30",
            total_points=len(grid),
        )
        db.add(run)
        db.commit()
        try:
            body = client.get("/regional-scan").json()
            assert body["run"]["run_id"] == run.id
            assert body["run"]["status"] == status
            assert len(body["points"]) == len(grid)
            assert {(p["lat"], p["lng"]) for p in body["points"]} == {
                (p["lat"], p["lng"]) for p in grid
            }
            assert body["grid_spacing_km"] == 5.0
            assert all(p["status"] == "no_data_yet" for p in body["points"])
            assert all(p["index_values"] is None and p["actual_date"] is None for p in body["points"])
            assert db.query(RegionalScanPoint).count() == 0
        finally:
            db.delete(run)
            db.commit()


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
            status="ok", index_values={"ndci": 0.2}, spatial_anomaly_z=2.5,
            threshold_tier="warning", run_id=run.id,
        ))
        db.add(RegionalScanPoint(
            point_id="0_1", lat=13.05, lng=100.5, row_idx=0, col_idx=1,
            status="ok", index_values={"ndci": 0.19}, spatial_anomaly_z=2.4,
            threshold_tier="warning", run_id=run.id,
        ))
        db.add(RegionalScanCluster(
            run_id=run.id, centroid_lat=13.025, centroid_lng=100.5, cell_count=2,
            mean_spatial_anomaly_z=2.45, max_spatial_anomaly_z=2.5, threshold_tier="warning",
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
            status="ok", index_values={"ndci": 0.2}, spatial_anomaly_z=2.5,
            threshold_tier="warning", run_id=good_run.id,
        ))
        db.add(RegionalScanPoint(
            point_id="9_1", lat=13.05, lng=100.5, row_idx=9, col_idx=1,
            status="ok", index_values={"ndci": 0.19}, spatial_anomaly_z=2.4,
            threshold_tier="warning", run_id=good_run.id,
        ))
        db.add(RegionalScanCluster(
            run_id=good_run.id, centroid_lat=13.025, centroid_lng=100.5, cell_count=2,
            mean_spatial_anomaly_z=2.45, max_spatial_anomaly_z=2.5, threshold_tier="warning",
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
            status="error", grid_spacing_km=10.0, date_used="2026-08-31",
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
        # Label the displayed snapshot's spacing, not the failed attempt's.
        assert body["run"]["grid_spacing_km"] == 10.0
        assert body["grid_spacing_km"] == 5.0

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


def test_regional_scan_serves_per_point_actual_date(client):
    """Each point carries its OWN Sentinel-2 scene date. A single scan
    legitimately mixes scene vintages (each point resolves its own
    latest usable scene on or before the target date), so a run-level
    date cannot stand in for any individual pin's."""
    db = SessionLocal()
    try:
        run = RegionalScanRun(
            started_at=datetime(2026, 9, 1, 6, 0, 0, tzinfo=timezone.utc),
            completed_at=datetime(2026, 9, 1, 6, 5, 0, tzinfo=timezone.utc),
            status="ok", grid_spacing_km=5.0, date_used="2026-09-01",
            newest_scene_date="2026-08-31T10:00:00+00:00", total_points=3,
            count_ok=2, count_no_imagery=1, count_no_water_pixels=0,
            count_no_climatology=0, count_error=0,
        )
        db.add(run)
        db.commit()
        db.refresh(run)

        # Two 'ok' points from scenes SIX DAYS APART inside one scan, plus
        # a no-imagery point that never resolved a scene at all.
        db.add(RegionalScanPoint(
            point_id="7_0", lat=13.0, lng=100.5, row_idx=7, col_idx=0,
            status="ok", index_values={"ndci": 0.2}, spatial_anomaly_z=2.5,
            threshold_tier="warning", actual_date="2026-08-31", run_id=run.id,
        ))
        db.add(RegionalScanPoint(
            point_id="7_1", lat=13.05, lng=100.5, row_idx=7, col_idx=1,
            status="ok", index_values={"ndci": 0.19}, spatial_anomaly_z=2.4,
            threshold_tier="warning", actual_date="2026-08-25", run_id=run.id,
        ))
        db.add(RegionalScanPoint(
            point_id="7_2", lat=13.1, lng=100.5, row_idx=7, col_idx=2,
            status="no_imagery", index_values=None, spatial_anomaly_z=None,
            threshold_tier=None, actual_date=None, run_id=run.id,
        ))
        db.commit()

        resp = client.get("/regional-scan")
        assert resp.status_code == 200
        body = resp.json()

        served = {p["point_id"]: p for p in body["points"]}
        assert served["7_0"]["actual_date"] == "2026-08-31"
        assert served["7_1"]["actual_date"] == "2026-08-25"
        # Never backfilled with the run's target date.
        assert served["7_2"]["actual_date"] is None
        assert served["7_2"]["actual_date"] != body["run"]["date_used"]
    finally:
        db.close()


def test_regional_scan_point_schema_documents_actual_date(client):
    """OpenAPI must describe actual_date as this point's own scene date --
    the field is meaningless (and misleading) without that caveat."""
    schema = client.get("/openapi.json").json()
    prop = schema["components"]["schemas"]["RegionalScanPointSchema"]["properties"]
    assert "actual_date" in prop
    assert "description" in prop["actual_date"]


def test_regional_scan_serves_cluster_scene_date_range(client):
    """A cluster is built from grid adjacency alone, never from dates, so
    its cells can come from Sentinel-2 scenes days apart. The endpoint
    must state that range rather than let one pin imply a single date."""
    db = SessionLocal()
    try:
        run = RegionalScanRun(
            started_at=datetime(2026, 9, 2, 6, 0, 0, tzinfo=timezone.utc),
            completed_at=datetime(2026, 9, 2, 6, 5, 0, tzinfo=timezone.utc),
            status="ok", grid_spacing_km=5.0, date_used="2026-09-02",
            newest_scene_date="2026-09-01T10:00:00+00:00", total_points=4,
            count_ok=4, count_no_imagery=0, count_no_water_pixels=0,
            count_no_climatology=0, count_error=0,
        )
        db.add(run)
        db.commit()
        db.refresh(run)

        # A mixed-vintage cluster: 10 days between its two cells, the
        # worst span measured in a real scan (2026-06-15).
        db.add(RegionalScanCluster(
            run_id=run.id, centroid_lat=13.2, centroid_lng=100.6, cell_count=2,
            mean_spatial_anomaly_z=2.45, max_spatial_anomaly_z=2.5, threshold_tier="warning",
            member_point_ids=["30_0", "30_1"],
            oldest_scene_date="2026-08-23", newest_scene_date="2026-09-02",
            scene_date_span_days=10,
        ))
        # A single-vintage cluster: span 0 is a real statement, not "unknown".
        db.add(RegionalScanCluster(
            run_id=run.id, centroid_lat=13.4, centroid_lng=100.8, cell_count=2,
            mean_spatial_anomaly_z=1.7, max_spatial_anomaly_z=1.8, threshold_tier="elevated",
            member_point_ids=["31_0", "31_1"],
            oldest_scene_date="2026-09-01", newest_scene_date="2026-09-01",
            scene_date_span_days=0,
        ))
        # Range unknown: a member had no usable scene date, so all three
        # are null together -- never partially filled.
        db.add(RegionalScanCluster(
            run_id=run.id, centroid_lat=13.6, centroid_lng=100.9, cell_count=2,
            mean_spatial_anomaly_z=1.9, max_spatial_anomaly_z=2.0, threshold_tier="elevated",
            member_point_ids=["32_0", "32_1"],
            oldest_scene_date=None, newest_scene_date=None,
            scene_date_span_days=None,
        ))
        db.commit()

        body = client.get("/regional-scan").json()
        # The table also holds clusters seeded by earlier tests in this
        # file, so look these up by their distinctive members.
        served = {
            tuple(sorted(c["member_point_ids"])): c for c in body["clusters"]
        }

        spanning = served[("30_0", "30_1")]
        assert spanning["oldest_scene_date"] == "2026-08-23"
        assert spanning["newest_scene_date"] == "2026-09-02"
        assert spanning["scene_date_span_days"] == 10
        # Shown in full -- a wide span is labelled, never suppressed.
        assert spanning["cell_count"] == 2

        same_day = served[("31_0", "31_1")]
        assert same_day["scene_date_span_days"] == 0
        assert same_day["oldest_scene_date"] == same_day["newest_scene_date"] == "2026-09-01"

        unknown = served[("32_0", "32_1")]
        assert unknown["oldest_scene_date"] is None
        assert unknown["newest_scene_date"] is None
        assert unknown["scene_date_span_days"] is None
        # Never substituted with the run's requested target date.
        assert unknown["newest_scene_date"] != body["run"]["date_used"]
    finally:
        db.close()


def test_regional_scan_cluster_schema_documents_scene_date_range(client):
    """OpenAPI must describe all three range fields -- a span is
    misleading without the caveat that adjacency, not date, decides
    membership."""
    schema = client.get("/openapi.json").json()
    prop = schema["components"]["schemas"]["RegionalScanClusterSchema"]["properties"]
    for field in ("oldest_scene_date", "newest_scene_date", "scene_date_span_days"):
        assert field in prop, f"{field} missing from RegionalScanClusterSchema"
        assert prop[field].get("description"), f"{field} has no description"
