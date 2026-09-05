"""Tests for `RiskMapProperties.site_type` (backend/src/schemas.py)."""

from __future__ import annotations

from sqlalchemy import delete

from src.db import SessionLocal
from src.db_models import DetectionCache, MonitoredSite

_TEST_SITE_ID = "pytest_site_type_test_site"


def test_risk_map_features_all_carry_monitoring_grid_site_type(client):
    """Every /risk-map feature -- including the real 6-site grid, which
    has no scheduler cache yet in a fresh test DB (the 'no_data_yet'
    branch of risk_map.py's get_risk_map) -- must carry
    site_type == 'monitoring_grid', not omit the field or leave it null."""
    resp = client.get("/risk-map")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["features"]) >= 6  # the real MONITORED_GRID, per grid.py

    for feature in body["features"]:
        assert feature["properties"]["site_type"] == "monitoring_grid"


def test_risk_map_site_type_present_on_cached_ok_reading_too(client):
    """Same field, same value, on the OTHER branch of get_risk_map -- a
    site that DOES have a DetectionCache row (the 'ok'/cached-reading
    path) -- so the two code paths that build RiskMapProperties can't
    silently diverge on this field."""
    db = SessionLocal()
    try:
        site = db.get(MonitoredSite, _TEST_SITE_ID)
        if site is None:
            site = MonitoredSite(site_id=_TEST_SITE_ID, name="pytest site_type test site", lat=13.1, lng=100.6)
            db.add(site)
            db.commit()

        db.add(
            DetectionCache(
                site_id=_TEST_SITE_ID,
                target_date="2024-03-15",
                status="ok",
                detected=False,
                spatial_anomaly_z=None,
                index_used="ndci",
                actual_date="2024-03-14",
                cloud_fraction=0.05,
                stale=False,
            )
        )
        db.commit()

        resp = client.get("/risk-map")
        assert resp.status_code == 200
        feature = next(
            f for f in resp.json()["features"] if f["properties"]["site_id"] == _TEST_SITE_ID
        )
        assert feature["properties"]["site_type"] == "monitoring_grid"
    finally:
        db.execute(delete(DetectionCache).where(DetectionCache.site_id == _TEST_SITE_ID))
        db.execute(delete(MonitoredSite).where(MonitoredSite.site_id == _TEST_SITE_ID))
        db.commit()
        db.close()
