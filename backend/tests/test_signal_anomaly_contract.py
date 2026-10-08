"""API and persistence contract for the inactive Sentinel-2 anomaly design."""

from sqlalchemy import create_engine, delete, inspect, text

from src import db
from src.db import SessionLocal
from src.db_models import DetectionCache, MonitoredSite
from src.routers import detect as detect_router
from src.routers import alerts as alerts_router
from src.services.cache_service import clear_cache, set_cached
from src import scientific_status


def _valid_detect_result():
    return {
        "index_values": {"ndci": 0.04, "2bda": 1.08, "3bda": 0.01, "b2_b3_ratio": 0.9},
        "actual_date": "2024-03-14",
        "index_used": "ndci",
        "status": "ok",
        "reason": None,
    }


def test_detect_and_risk_map_keep_unvalidated_signal_and_risk_null(client, monkeypatch):
    monkeypatch.setattr(detect_router.bridge, "detect", lambda *_a, **_k: _valid_detect_result())

    detect = client.get(
        "/detect", params={"lat": 13.2, "lng": 100.9, "date": "2024-03-15"}
    )
    assert detect.status_code == 200
    assert detect.json()["signal_anomaly_level"] is None

    risk_map = client.get("/risk-map")
    assert risk_map.status_code == 200
    for feature in risk_map.json()["features"]:
        assert feature["properties"]["signal_anomaly_level"] is None
        assert feature["properties"]["risk_level"] is None


def test_openapi_never_calls_ndci_colour_ramp_a_risk_ramp(client):
    schema_text = str(client.get("/openapi.json").json()).lower()
    assert "risk-ramp ndci" not in schema_text
    assert "5-stop risk ramp" not in schema_text


def test_legacy_cached_levels_cannot_escape_without_an_active_signal_baseline(
    client, monkeypatch,
):
    monkeypatch.setattr(
        scientific_status.bridge,
        "load_prediction_config",
        lambda: {
            "risk_evaluation": {"active": True},
            "signal_anomaly": {
                "status": "inactive_no_consistent_sentinel2_baseline",
                "minimum_independent_dates": 30,
                "max_observation_age_days": 14,
            },
            "prediction_confidence_label": "not evaluated",
        },
    )
    site_id = "pytest_inactive_scientific_status"
    session = SessionLocal()
    try:
        site = MonitoredSite(site_id=site_id, name="inactive status fixture", lat=13.1, lng=100.6)
        session.add(site)
        session.flush()
        session.add(DetectionCache(
            site_id=site_id,
            target_date="2024-03-15",
            status="ok",
            detected=True,
            spatial_anomaly_z=9.0,
            signal_anomaly_level="high",
            level="warning",
            triggered_rules=["warning"],
            confidence_label="legacy",
            index_used="ndci",
            index_values={"ndci": 0.15},
            actual_date="2024-03-14",
            stale=False,
        ))
        session.commit()
        clear_cache()

        feature = next(
            item for item in client.get("/risk-map").json()["features"]
            if item["properties"]["site_id"] == site_id
        )
        assert feature["properties"]["risk_level"] is None
        assert feature["properties"]["signal_anomaly_level"] is None
        assert feature["properties"]["triggered_rules"] == []

        summary = client.get("/summary").json()
        assert summary["risk_level_counts"]["warning"] == 0
        assert summary["most_recent_detected_signal"] is None

        alerts = client.get("/alerts").json()
        assert alerts["total_active_alerts"] == 0
        assert alerts["highest_risk_tier"] is None
        assert alerts["stations"] == []
    finally:
        session.execute(delete(DetectionCache).where(DetectionCache.site_id == site_id))
        session.execute(delete(MonitoredSite).where(MonitoredSite.site_id == site_id))
        session.commit()
        session.close()
        clear_cache()


def test_cached_alerts_cannot_bypass_the_inactive_scientific_gate(client):
    set_cached(
        alerts_router.CACHE_KEY_ALERTS,
        {
            "updated_at": "2024-01-01T00:00:00+00:00",
            "total_active_alerts": 1,
            "highest_risk_tier": "WARNING",
            "stations": [{
                "site_id": "legacy",
                "name": "legacy cached alert",
                "risk_tier": "WARNING",
                "confidence": 0.99,
                "coordinates": [13.0, 100.0],
                "spatial_anomaly_z": 9.0,
                "actual_date": "2024-01-01",
            }],
        },
    )
    try:
        payload = client.get("/alerts").json()
        assert payload["total_active_alerts"] == 0
        assert payload["highest_risk_tier"] is None
        assert payload["stations"] == []
    finally:
        clear_cache()


def test_risk_cannot_activate_without_a_compatible_signal_baseline(monkeypatch):
    monkeypatch.setattr(
        scientific_status.bridge,
        "load_prediction_config",
        lambda: {
            "risk_evaluation": {"active": True},
            "signal_anomaly": {"status": "inactive_no_consistent_sentinel2_baseline"},
        },
    )
    assert scientific_status.signal_anomaly_active() is False
    assert scientific_status.risk_evaluation_active() is False


def test_malformed_signal_activation_configuration_fails_closed(monkeypatch):
    monkeypatch.setattr(
        scientific_status.bridge,
        "load_prediction_config",
        lambda: {
            "risk_evaluation": {"active": True},
            "signal_anomaly": {
                "status": "active",
                "minimum_independent_dates": "not-a-number",
                "max_observation_age_days": 14,
            },
        },
    )
    assert scientific_status.signal_anomaly_active() is False
    assert scientific_status.risk_evaluation_active() is False


def test_signal_anomaly_column_is_added_without_resetting_existing_cache(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'older.db'}")
    monkeypatch.setattr(db, "engine", engine)
    db.init_db()
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE detection_cache RENAME TO detection_cache_new"))
        connection.execute(text(
            "CREATE TABLE detection_cache (id INTEGER PRIMARY KEY, site_id VARCHAR, "
            "target_date VARCHAR, status VARCHAR)"
        ))
        connection.execute(text(
            "INSERT INTO detection_cache VALUES (1, 'kept-site', '2024-01-01', 'ok')"
        ))

    db.init_db()
    columns = {column["name"] for column in inspect(engine).get_columns("detection_cache")}
    assert "signal_anomaly_level" in columns
    with engine.connect() as connection:
        assert connection.execute(text(
            "SELECT site_id, signal_anomaly_level FROM detection_cache WHERE id = 1"
        )).one() == ("kept-site", None)
    engine.dispose()
