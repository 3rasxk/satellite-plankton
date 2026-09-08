"""SQLAlchemy engine/session setup. Backend-agnostic -- see src/config.py
for the DATABASE_URL / SQLite-fallback story."""

from __future__ import annotations

from sqlalchemy import MetaData, Table, create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from . import config

_connect_args = {"check_same_thread": False} if config.DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(config.DATABASE_URL, connect_args=_connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency -- one session per request."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Nullable columns added to a table that already exists in the wild.
# `create_all` creates missing tables but never alters an existing one, so
# a column added to a model after its table was first created is invisible
# to any database that predates it -- and the next query naming it fails.
#
# Each entry is (table, column, DDL type), all module constants, never
# user input. Only ever nullable additions with no default: an ADD COLUMN
# of that shape is instant and lossless on both SQLite and Postgres, which
# is the whole reason this is acceptable in a project with no migration
# tool. Anything that needs data moved or a column dropped is not this
# list's job and should not be added to it.
_ADDED_NULLABLE_COLUMNS: tuple[tuple[str, str, str], ...] = (
    # RasterScanRun.overlay -- rendered map assets and their bounds; the
    # raster_scan_runs table shipped one commit before the renderer did.
    ("raster_scan_runs", "overlay", "JSON"),
    # RasterScanRun.scene_dates -- the per-acquisition-day breakdown of a
    # run's cells, added with the raster scan banner. Null on every run
    # taken before it existed, which is the honest value: that
    # distribution was never measured for those runs and cannot be
    # recovered from the span they did record.
    ("raster_scan_runs", "scene_dates", "JSON"),
)


def _add_missing_columns(connection) -> list[str]:
    """Apply `_ADDED_NULLABLE_COLUMNS` to tables that already exist.

    A table that does not exist yet is skipped -- `create_all` will build
    it complete from the model, including the column. Returns the
    "table.column" names actually added, for the caller to log; adding
    nothing is the normal case.
    """
    inspector = inspect(connection)
    added: list[str] = []
    for table_name, column_name, ddl_type in _ADDED_NULLABLE_COLUMNS:
        if not inspector.has_table(table_name):
            continue
        existing = {column["name"] for column in inspector.get_columns(table_name)}
        if column_name in existing:
            continue
        connection.execute(
            text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl_type}")
        )
        added.append(f"{table_name}.{column_name}")
    return added


def init_db() -> None:
    """Create active tables and discard retired or invalid cache schemas.

    Legacy spectral-index/MODIS chlor_a scores have incompatible units;
    they cannot be migrated or backfilled into spatial_anomaly_z. Only
    disposable detection caches and regional scan snapshots and their run
    metadata are reset. The retired validation tables are always dropped.
    Repeated startup preserves caches already using the current schema.

    Nullable columns added to a table that already exists are then filled
    in by `_add_missing_columns` -- `create_all` never alters an existing
    table, so without that step a column added to a model after its table
    shipped would be missing from every database that predates it.
    """
    from . import db_models  # noqa: F401  (registers models on Base.metadata)

    with engine.begin() as connection:
        inspector = inspect(connection)
        for table_name in ("validation_cache", "validation_events"):
            if inspector.has_table(table_name):
                Table(table_name, MetaData(), autoload_with=connection).drop(bind=connection)
                inspector = inspect(connection)
        legacy_columns = {
            "detection_cache": "anomaly_z",
            "regional_scan_points": "anomaly_z",
            "regional_scan_clusters": "mean_anomaly_z",
        }
        has_legacy_scores = any(
            inspector.has_table(table)
            and column in {item["name"] for item in inspector.get_columns(table)}
            for table, column in legacy_columns.items()
        )
        if has_legacy_scores:
            # Children first for databases that enforce foreign keys.
            # Run metadata must go too: otherwise a finished legacy run
            # would advertise counts despite having no retained points.
            for model in (
                db_models.RegionalScanCluster,
                db_models.RegionalScanPoint,
                db_models.RegionalScanRun,
                db_models.DetectionCache,
            ):
                model.__table__.drop(bind=connection, checkfirst=True)
        _add_missing_columns(connection)
        Base.metadata.create_all(bind=connection)
