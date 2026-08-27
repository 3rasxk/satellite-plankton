"""Compatibility-safe additive migrations for existing backend databases."""

from sqlalchemy import JSON, inspect, text


def ensure_watch_overlay_analysis_metadata_column(bind) -> None:
    inspector = inspect(bind)
    if "watch_overlay_cache" not in inspector.get_table_names():
        return
    if "analysis_metadata" in {
        column["name"] for column in inspector.get_columns("watch_overlay_cache")
    }:
        return
    json_type = JSON().compile(dialect=bind.dialect)
    with bind.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE watch_overlay_cache "
                f"ADD COLUMN analysis_metadata {json_type}"
            )
        )
