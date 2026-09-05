"""SQLAlchemy engine/session setup. Backend-agnostic -- see src/config.py
for the DATABASE_URL / SQLite-fallback story."""

from __future__ import annotations

from sqlalchemy import MetaData, Table, create_engine, inspect
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


def init_db() -> None:
    """Create active tables and discard retired or invalid cache schemas.

    Legacy spectral-index/MODIS chlor_a scores have incompatible units;
    they cannot be migrated or backfilled into spatial_anomaly_z. Only
    disposable detection caches and regional scan snapshots and their run
    metadata are reset. The retired validation tables are always dropped.
    Repeated startup preserves caches already using the current schema.
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
        Base.metadata.create_all(bind=connection)
