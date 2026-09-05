"""SQLAlchemy engine/session setup. Backend-agnostic -- see src/config.py
for the DATABASE_URL / SQLite-fallback story."""

from __future__ import annotations

from sqlalchemy import create_engine, inspect, select
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
    """Create tables, discarding caches from the invalid anomaly schema.

    Legacy spectral-index/MODIS chlor_a scores have incompatible units;
    they cannot be migrated or backfilled into spatial_anomaly_z. Only
    disposable detection/validation caches and regional scan snapshots
    and their run metadata are reset. Sites and validation events survive.
    Repeated startup preserves caches already using the current schema.
    """
    from . import db_models  # noqa: F401  (registers models on Base.metadata)

    with engine.begin() as connection:
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
                db_models.ValidationCache,
            ):
                model.__table__.drop(bind=connection, checkfirst=True)
        elif inspector.has_table("validation_cache"):
            # JSON payloads have no renamed SQL column to identify their
            # version. A validation-only database can still hold invalid
            # scores or a false miss, so invalidate that cache separately.
            payloads = connection.execute(select(db_models.ValidationCache.payload)).scalars()
            if any(
                any(
                    event.get("z_score_status") != "not_computed_no_valid_baseline"
                    or "anomaly_z" in event
                    or event.get("spatial_anomaly_z") is not None
                    or event.get("flagged") is not None
                    for event in payload.get("events", [])
                )
                or any(row.get("caught") is not None for row in payload.get("leave_one_out", []))
                for payload in payloads
            ):
                db_models.ValidationCache.__table__.drop(bind=connection)
        Base.metadata.create_all(bind=connection)
