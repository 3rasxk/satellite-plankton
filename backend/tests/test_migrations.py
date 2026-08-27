from sqlalchemy import create_engine, inspect, text

from src.migrations import ensure_watch_overlay_analysis_metadata_column


def test_additive_watch_overlay_migration_preserves_existing_row():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE watch_overlay_cache "
                "(id INTEGER PRIMARY KEY, status VARCHAR NOT NULL, tile_url TEXT)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO watch_overlay_cache (id, status, tile_url) "
                "VALUES (1, 'ok', 'cached')"
            )
        )

    ensure_watch_overlay_analysis_metadata_column(engine)
    ensure_watch_overlay_analysis_metadata_column(engine)

    assert "analysis_metadata" in {
        column["name"] for column in inspect(engine).get_columns("watch_overlay_cache")
    }
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT status, tile_url, analysis_metadata "
                "FROM watch_overlay_cache WHERE id=1"
            )
        ).one()
    assert tuple(row) == ("ok", "cached", None)
