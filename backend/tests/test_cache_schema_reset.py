"""Legacy dimensionally invalid caches are discarded, never backfilled.

Tests use isolated SQLite files, preserving source site/event rows and
proving that a second startup retains newly computed index-only caches.
"""

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session

from src import db
from src.db_models import DetectionCache, MonitoredSite, ValidationCache, ValidationEvent


def test_legacy_caches_reset_without_losing_sites_or_validation_events(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    monkeypatch.setattr(db, "engine", engine)
    db.init_db()
    with Session(engine) as session:
        session.add(MonitoredSite(site_id="real_site", name="Real site", lat=13, lng=101))
        session.add(ValidationEvent(
            event_id="retained_event", location_name="Confirmed site",
            location_precision="exact", species="karenia_sp", event_type="bloom",
            source_type="paper", source_citation="Original citation", confidence="high",
        ))
        session.add(ValidationCache(id=1, payload={
            "events": [{"anomaly_z": -4.5, "flagged": False}],
            "leave_one_out": [{"caught": False}],
        }))
        session.commit()

    with engine.begin() as connection:
        # Simulate the old columns and previously published invalid values.
        connection.execute(text("DROP TABLE detection_cache"))
        connection.execute(text("CREATE TABLE detection_cache (id INTEGER PRIMARY KEY, anomaly_z FLOAT)"))
        connection.execute(text("INSERT INTO detection_cache VALUES (1, -4.5)"))
        connection.execute(text("DROP TABLE regional_scan_points"))
        connection.execute(text("CREATE TABLE regional_scan_points (point_id TEXT, anomaly_z FLOAT)"))
        connection.execute(text("INSERT INTO regional_scan_points VALUES ('0_0', -4.5)"))
        connection.execute(text("DROP TABLE regional_scan_clusters"))
        connection.execute(text("CREATE TABLE regional_scan_clusters (id INTEGER, mean_anomaly_z FLOAT)"))
        connection.execute(text("INSERT INTO regional_scan_clusters VALUES (1, -4.5)"))
        connection.execute(text(
            "INSERT INTO regional_scan_runs (id, started_at, status, grid_spacing_km, date_used, total_points, "
            "count_ok, count_no_imagery, count_no_water_pixels, count_no_climatology, count_error) "
            "VALUES (1, '2026-01-05 00:00:00', 'ok', 2, '2026-01-05', 1, 1, 0, 0, 0, 0)"
        ))

    db.init_db()
    inspector = inspect(engine)
    with engine.connect() as connection:
        for table in (
            "detection_cache", "validation_cache", "regional_scan_points",
            "regional_scan_clusters", "regional_scan_runs",
        ):
            assert connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one() == 0
            assert all(
                column["name"] not in {"anomaly_z", "mean_anomaly_z", "max_anomaly_z"}
                for column in inspector.get_columns(table)
            )
    with Session(engine) as session:
        assert session.get(MonitoredSite, "real_site").name == "Real site"
        assert session.get(ValidationEvent, "retained_event").source_citation == "Original citation"
        session.add(DetectionCache(
            site_id="real_site", target_date="2026-01-05", status="ok",
            spatial_anomaly_z=None, detected=None, level=None,
            index_values={"ndci": 0.2}, actual_date="2026-01-03",
        ))
        session.add(ValidationCache(id=1, payload={
            "events": [{"z_score_status": "not_computed_no_valid_baseline", "flagged": None}],
            "leave_one_out": [{"caught": None}],
        }))
        session.commit()

    db.init_db()
    with Session(engine) as session:
        cached = session.scalar(select(DetectionCache))
        assert cached.index_values == {"ndci": 0.2}
        assert cached.actual_date == "2026-01-03"
        assert cached.spatial_anomaly_z is None
        assert session.get(ValidationCache, 1) is not None
    engine.dispose()


def test_legacy_validation_payload_resets_even_without_legacy_sql_columns(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'validation.db'}")
    monkeypatch.setattr(db, "engine", engine)
    db.init_db()
    with Session(engine) as session:
        session.add(ValidationCache(id=1, payload={
            "events": [{"anomaly_z": -4.5, "flagged": False}],
            "leave_one_out": [{"caught": False}],
        }))
        session.commit()
    db.init_db()
    with Session(engine) as session:
        assert session.get(ValidationCache, 1) is None
    engine.dispose()
