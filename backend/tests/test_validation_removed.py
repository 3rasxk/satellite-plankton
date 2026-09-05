"""The retired bloom-event validation feature leaves no API or database data."""

from sqlalchemy import create_engine, inspect, text

from src import db


def test_validation_api_is_removed(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert "/validation" not in paths


def test_init_db_drops_retired_validation_tables(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'retired-validation.db'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE validation_events (event_id TEXT PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE validation_cache (id INTEGER PRIMARY KEY)"))
        connection.execute(text("INSERT INTO validation_events VALUES ('retired_event')"))
        connection.execute(text("INSERT INTO validation_cache VALUES (1)"))

    monkeypatch.setattr(db, "engine", engine)
    db.init_db()

    tables = set(inspect(engine).get_table_names())
    assert "validation_events" not in tables
    assert "validation_cache" not in tables
    engine.dispose()
