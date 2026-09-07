"""`/raster-scan` -- serves the newest overlay that still exists on disk.

No live GEE, no rendering: these exercise what the endpoint does with
rows and files that are already there.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from src import _study_area
from src.db import SessionLocal
from src.db_models import RasterScanRun


def _run(tmp_path, *, run_id_hint: str, started: datetime, overlay_ok: bool = True,
         bounds=None, exists: bool = True) -> RasterScanRun:
    png = tmp_path / f"{run_id_hint}.png"
    if exists:
        png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    overlay = {
        "status": "ok" if overlay_ok else "error",
        "bounds": {"leaflet_bounds": bounds or [[12.5, 99.9], [13.6, 101.0]]},
        "assets": {"ndci": {"path": str(png), "bytes": 72}},
        "legend": {
            "value": {"ramp_hex": ["#0A1929"], "domain": [-0.05, 0.15],
                      "swatches": [{"value": -0.05, "hex": "#0a1929"}]},
            "no_data": {"base_rgba": [176, 176, 176, 205], "stripe_rgba": [92, 92, 92, 235]},
        },
    }
    return RasterScanRun(
        started_at=started, completed_at=started, status="ok", date_used="2026-09-06",
        scale_m=200, retention_days=30, cell_count=1234, scene_count=3,
        oldest_scene_date="2026-08-23", newest_scene_date="2026-09-02",
        overlay=overlay,
    )


def _clear():
    with SessionLocal() as db:
        db.execute(delete(RasterScanRun))
        db.commit()


def test_no_scan_yet_says_so_instead_of_serving_a_blank_overlay(client):
    _clear()
    body = client.get("/raster-scan").json()
    assert body["run_id"] is None
    assert body["bounds"] is None
    assert body["overlay_url"] is None
    assert "No raster overlay" in body["reason"]
    assert client.get("/raster-scan/overlay.png").status_code == 404


def test_the_served_overlay_is_the_newest_one_with_a_file_on_disk(client, tmp_path):
    _clear()
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        old = _run(tmp_path, run_id_hint="old", started=now - timedelta(hours=5))
        # Newer, but its render failed -- it must not hide the older picture.
        broken = _run(tmp_path, run_id_hint="broken", started=now, overlay_ok=False)
        db.add_all([old, broken])
        db.commit()
        old_id, broken_id = old.id, broken.id

    body = client.get("/raster-scan").json()
    assert body["run_id"] == old_id, "a failed newer run hid the last good overlay"
    assert body["stale_run_id"] == broken_id, "the newer attempt was not reported"
    assert client.get("/raster-scan/overlay.png").status_code == 200


def test_a_run_whose_blob_was_expired_is_not_served(client, tmp_path):
    """Retention deletes the PNG but keeps the row. The row must not
    advertise a picture that is gone."""
    _clear()
    with SessionLocal() as db:
        db.add(_run(tmp_path, run_id_hint="expired",
                    started=datetime.now(timezone.utc), exists=False))
        db.commit()
    body = client.get("/raster-scan").json()
    assert body["run_id"] is None
    assert client.get("/raster-scan/overlay.png").status_code == 404


def test_bounds_and_legend_travel_with_the_metadata(client, tmp_path):
    _clear()
    with SessionLocal() as db:
        db.add(_run(tmp_path, run_id_hint="ok", started=datetime.now(timezone.utc)))
        db.commit()
    body = client.get("/raster-scan").json()
    assert body["bounds"] == [[12.5, 99.9], [13.6, 101.0]]
    assert body["legend"]["value"]["swatches"][0]["hex"] == "#0a1929"
    assert body["legend"]["no_data"]["base_rgba"] == [176, 176, 176, 205]
    assert body["scale_m"] == 200
    assert body["oldest_scene_date"] == "2026-08-23"
    assert body["newest_scene_date"] == "2026-09-02"
    assert body["disclaimer"]


def test_the_response_never_carries_a_risk_level_or_anomaly_score(client, tmp_path):
    """Same truth boundary as every other endpoint: readings only."""
    _clear()
    with SessionLocal() as db:
        db.add(_run(tmp_path, run_id_hint="ok2", started=datetime.now(timezone.utc)))
        db.commit()
    body = client.get("/raster-scan").json()
    for forbidden in ("risk_level", "anomaly_z", "spatial_anomaly_z", "threshold_tier"):
        assert forbidden not in body, f"{forbidden} must not appear on a raster response"


def test_overlay_bounds_cover_the_whole_study_polygon(client, tmp_path):
    """A stretched overlay misplaces every pixel and nothing visibly
    fails, so the bounds are checked against the polygon numerically."""
    lats = [p[0] for p in _study_area.STUDY_AREA_POLYGON_LATLNG]
    lngs = [p[1] for p in _study_area.STUDY_AREA_POLYGON_LATLNG]
    expected = [[min(lats), min(lngs)], [max(lats), max(lngs)]]

    _clear()
    with SessionLocal() as db:
        db.add(_run(tmp_path, run_id_hint="poly",
                    started=datetime.now(timezone.utc), bounds=expected))
        db.commit()

    body = client.get("/raster-scan").json()
    (south, west), (north, east) = body["bounds"]
    assert (south, west) == (min(lats), min(lngs))
    assert (north, east) == (max(lats), max(lngs))
    for lat, lng in _study_area.STUDY_AREA_POLYGON_LATLNG:
        assert south <= lat <= north, f"polygon vertex {lat} outside the overlay bounds"
        assert west <= lng <= east, f"polygon vertex {lng} outside the overlay bounds"
