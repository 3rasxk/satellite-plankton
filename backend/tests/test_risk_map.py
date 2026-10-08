"""Tests for GET /risk-map (backend/src/routers/risk_map.py).

Covers what test_risk_map_site_type.py and test_satellite_image.py do not:
the no-cache placeholder branch, and the scientific-status gates that null
out risk/anomaly fields while the baseline is disabled. Cache rows are
written directly -- no GEE call is made.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import delete

from src.db import SessionLocal
from src.db_models import DetectionCache, MonitoredSite
from src.routers import risk_map as risk_map_module

_SITE_ID = "pytest_risk_map_site"


@pytest.fixture()
def cached_site():
    """A site with a fully-populated DetectionCache row; cleaned up after."""
    db = SessionLocal()
    try:
        db.add(MonitoredSite(site_id=_SITE_ID, name="pytest risk map site", lat=13.2, lng=100.4))
        db.commit()
        db.add(
            DetectionCache(
                site_id=_SITE_ID,
                target_date="2024-03-15",
                status="ok",
                detected=True,
                spatial_anomaly_z=2.5,
                signal_anomaly_level="high",
                index_used="ndci",
                index_values={"ndci": 0.12},
                level="warning",
                triggered_rules=["rule_a"],
                confidence_label="indicative",
                cloud_fraction=0.1,
                actual_date="2024-03-14",
                fetched_at=datetime(2024, 3, 15, 6, 0, tzinfo=timezone.utc),
                stale=False,
            )
        )
        db.commit()
        yield
    finally:
        db.execute(delete(DetectionCache).where(DetectionCache.site_id == _SITE_ID))
        db.execute(delete(MonitoredSite).where(MonitoredSite.site_id == _SITE_ID))
        db.commit()
        db.close()


def _feature(client, site_id=_SITE_ID):
    resp = client.get("/risk-map")
    assert resp.status_code == 200
    return next(f for f in resp.json()["features"] if f["properties"]["site_id"] == site_id)


def _set_gates(monkeypatch, *, risk: bool, signal: bool):
    monkeypatch.setattr(risk_map_module, "risk_evaluation_active", lambda: risk)
    monkeypatch.setattr(risk_map_module, "signal_anomaly_active", lambda: signal)


def test_uncached_site_reports_no_data_yet(client):
    """Fresh DB, scheduler never ran: every feature is an honest placeholder."""
    resp = client.get("/risk-map")
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "FeatureCollection"
    assert body["features"]

    for f in body["features"]:
        p = f["properties"]
        if p["status"] != "no_data_yet":
            continue  # another test's cached row; not this branch
        assert p["risk_level"] is None
        assert p["detected"] is None
        assert p["stale"] is True
        assert p["confidence_label"] == "no cached reading yet"
        assert f["geometry"]["type"] == "Point"


def test_geometry_is_lng_lat_order(client, cached_site):
    f = _feature(client)
    assert f["geometry"] == {"type": "Point", "coordinates": [100.4, 13.2]}


def test_gates_off_hide_risk_and_anomaly_fields(client, cached_site, monkeypatch):
    """Cache holds level/detected/z, but the baseline is disabled: none leak out."""
    _set_gates(monkeypatch, risk=False, signal=False)
    p = _feature(client)["properties"]

    assert p["risk_level"] is None
    assert p["triggered_rules"] == []
    assert p["detected"] is None
    assert p["spatial_anomaly_z"] is None
    assert p["signal_anomaly_level"] is None
    # raw readings and provenance still pass through
    assert p["index_used"] == "ndci"
    assert p["index_values"] == {"ndci": 0.12}
    assert p["actual_date"] == "2024-03-14"
    assert p["cloud_fraction"] == 0.1
    assert p["status"] == "ok"


def test_gates_on_expose_risk_and_anomaly_fields(client, cached_site, monkeypatch):
    _set_gates(monkeypatch, risk=True, signal=True)
    p = _feature(client)["properties"]

    assert p["risk_level"] == "warning"
    assert p["triggered_rules"] == ["rule_a"]
    assert p["detected"] is True
    assert p["spatial_anomaly_z"] == 2.5
    assert p["signal_anomaly_level"] == "high"


def test_gates_are_independent(client, cached_site, monkeypatch):
    """Signal gate on, risk gate off: only anomaly fields appear."""
    _set_gates(monkeypatch, risk=False, signal=True)
    p = _feature(client)["properties"]

    assert p["risk_level"] is None
    assert p["detected"] is None
    assert p["spatial_anomaly_z"] == 2.5
    assert p["signal_anomaly_level"] == "high"


def test_fetched_at_is_aware_utc_iso(client, cached_site):
    p = _feature(client)["properties"]
    parsed = datetime.fromisoformat(p["fetched_at"])
    assert parsed.tzinfo is not None
    assert parsed.utcoffset().total_seconds() == 0
    assert parsed.replace(tzinfo=None) == datetime(2024, 3, 15, 6, 0)


def test_image_urls_null_without_png_bytes(client, cached_site):
    p = _feature(client)["properties"]
    assert p["true_color_image_url"] is None
    assert p["ndci_heatmap_image_url"] is None
