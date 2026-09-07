"""Legacy dimensionally invalid caches are discarded, never backfilled."""

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session

from src import db
from src.db_models import DetectionCache, MonitoredSite


def test_legacy_caches_reset_without_losing_sites(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    monkeypatch.setattr(db, "engine", engine)
    db.init_db()
    with Session(engine) as session:
        session.add(MonitoredSite(site_id="real_site", name="Real site", lat=13, lng=101))
        session.commit()

    with engine.begin() as connection:
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
            "detection_cache", "regional_scan_points",
            "regional_scan_clusters", "regional_scan_runs",
        ):
            assert connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one() == 0
            assert all(
                column["name"] not in {"anomaly_z", "mean_anomaly_z", "max_anomaly_z"}
                for column in inspector.get_columns(table)
            )
    with Session(engine) as session:
        assert session.get(MonitoredSite, "real_site").name == "Real site"
        session.add(DetectionCache(
            site_id="real_site", target_date="2026-01-05", status="ok",
            spatial_anomaly_z=None, detected=None, level=None,
            index_values={"ndci": 0.2}, actual_date="2026-01-03",
        ))
        session.commit()

    db.init_db()
    with Session(engine) as session:
        cached = session.scalar(select(DetectionCache))
        assert cached.index_values == {"ndci": 0.2}
        assert cached.actual_date == "2026-01-03"
        assert cached.spatial_anomaly_z is None
    engine.dispose()


def test_a_column_added_after_a_table_shipped_reaches_an_existing_database(tmp_path, monkeypatch):
    """`create_all` builds missing tables but never alters an existing one,
    so a column added to a model later is invisible to every database that
    predates it -- and the next query naming it fails. This is the one
    path that fixes that, and no fresh test database ever exercises it.

    RasterScanRun.overlay is the case in hand: raster_scan_runs shipped one
    commit before the renderer that fills the column in.
    """
    engine = create_engine(f"sqlite:///{tmp_path / 'older.db'}")
    monkeypatch.setattr(db, "engine", engine)
    db.init_db()

    # Recreate the pre-overlay table, with a run already recorded in it.
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE raster_scan_runs"))
        connection.execute(text(
            "CREATE TABLE raster_scan_runs (id INTEGER PRIMARY KEY, started_at DATETIME, "
            "status VARCHAR, date_used VARCHAR, scale_m INTEGER, retention_days INTEGER)"
        ))
        connection.execute(text(
            "INSERT INTO raster_scan_runs VALUES (1, '2026-09-06 00:00:00', 'ok', "
            "'2026-09-06', 200, 30)"
        ))

    db.init_db()

    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("raster_scan_runs")}
    assert "overlay" in columns
    with engine.connect() as connection:
        # The addition is not a reset: the row that was already there
        # survives, with the new column simply null.
        rows = connection.execute(text("SELECT id, overlay FROM raster_scan_runs")).all()
        assert rows == [(1, None)]

    # Idempotent -- a second startup adds nothing and changes nothing.
    db.init_db()
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM raster_scan_runs")).scalar_one() == 1
    assert {column["name"] for column in inspect(engine).get_columns("raster_scan_runs")} == columns
    engine.dispose()
