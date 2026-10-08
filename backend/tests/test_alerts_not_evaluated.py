"""/alerts must distinguish 'not evaluated' from 'evaluated, none' (CLAUDE.md §0)."""

from __future__ import annotations

import pytest

from src.db import SessionLocal
from src.db_models import DetectionCache, MonitoredSite
from src.routers import alerts as alerts_module
from src.services.cache_service import clear_cache


def test_alerts_reports_not_evaluated_when_risk_gate_off(client, monkeypatch):
    monkeypatch.setattr(alerts_module, "risk_evaluation_active", lambda: False)
    body = client.get("/alerts").json()
    assert body["evaluation_status"] == "not_evaluated"
    assert body["updated_at"] is None
    assert body["stations"] == []
    assert body["highest_risk_tier"] is None
    # Not 0: a reader that only looks at the count must not read "none active".
    assert body["total_active_alerts"] is None


def test_alerts_reports_active_when_risk_gate_on(client, monkeypatch):
    monkeypatch.setattr(alerts_module, "risk_evaluation_active", lambda: True)
    body = client.get("/alerts").json()
    assert body["evaluation_status"] == "active"


def test_payload_cached_while_active_is_not_served_after_gate_flips_off(client, monkeypatch):
    """The gate is checked before the cache: a payload cached while evaluation
    was on must not survive the gate turning off."""
    clear_cache()
    try:
        monkeypatch.setattr(alerts_module, "risk_evaluation_active", lambda: True)
        # Seed the cache via the real handler path, then overwrite with a
        # distinctive payload so a leak is unmistakable.
        assert client.get("/alerts").json()["evaluation_status"] == "active"
        alerts_module.set_cached(
            alerts_module.CACHE_KEY_ALERTS,
            {
                "updated_at": "2024-01-01T00:00:00+00:00",
                "total_active_alerts": 1,
                "highest_risk_tier": "WARNING",
                "stations": [{
                    "site_id": "x", "name": "x", "risk_tier": "WARNING",
                    "confidence": None, "coordinates": [13.0, 100.0],
                }],
            },
        )
        assert client.get("/alerts").json()["total_active_alerts"] == 1

        monkeypatch.setattr(alerts_module, "risk_evaluation_active", lambda: False)
        body = client.get("/alerts").json()
        assert body["evaluation_status"] == "not_evaluated"
        assert body["total_active_alerts"] is None
        assert body["highest_risk_tier"] is None
        assert body["stations"] == []
        assert body["updated_at"] is None
    finally:
        clear_cache()


@pytest.mark.parametrize("level", ["elevated", "watch", "warning"])
def test_active_gate_station_path_has_null_confidence_and_right_tier(
    client, monkeypatch, level,
):
    monkeypatch.setattr(alerts_module, "risk_evaluation_active", lambda: True)
    site_id = f"pytest_alerts_{level}"
    session = SessionLocal()
    clear_cache()
    try:
        session.add(MonitoredSite(site_id=site_id, name="alerts fixture", lat=13.1234, lng=100.5678))
        session.flush()
        session.add(DetectionCache(
            site_id=site_id, target_date="2024-03-15", status="ok",
            level=level, spatial_anomaly_z=2.345, actual_date="2024-03-14",
        ))
        session.commit()

        body = client.get("/alerts").json()
        assert body["evaluation_status"] == "active"
        mine = [s for s in body["stations"] if s["site_id"] == site_id]
        assert len(mine) == 1
        assert mine[0]["risk_tier"] == level.upper()
        assert mine[0]["confidence"] is None
        assert mine[0]["coordinates"] == [13.1234, 100.5678]
        assert body["total_active_alerts"] == len(body["stations"]) >= 1
        order = {"ELEVATED": 1, "WATCH": 2, "WARNING": 3}
        assert order[body["highest_risk_tier"]] >= order[level.upper()]
    finally:
        session.rollback()
        session.query(DetectionCache).filter(DetectionCache.site_id == site_id).delete()
        session.query(MonitoredSite).filter(MonitoredSite.site_id == site_id).delete()
        session.commit()
        session.close()
        clear_cache()
