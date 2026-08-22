"""
SQLAlchemy ORM models. Four tables:

- MonitoredSite     the grid `/risk-map`, `/summary`, and the scheduler
                    operate over (src/grid.py MONITORED_GRID, upserted at
                    startup). New, deliberately-chosen monitoring points --
                    NOT the validation set.
- DetectionCache    one row per MonitoredSite, upserted by the scheduler
                    (src/scheduler.py) with the latest risk_level()/
                    detect() result. This is what /risk-map and /summary
                    actually read -- they never hit GEE live in normal
                    operation (CLAUDE.md's "don't hit GEE live on every
                    /risk-map request in production shape").
                    `stale` distinguishes "the last scheduler run for this
                    site failed, this is old data" from "this is the
                    latest real reading" -- a failed refresh must never
                    silently look like a fresh one.
- ValidationEvent   mirrors data/validation/events.csv (14 rows), upserted
                    read-only at startup from that file. Not editable via
                    any API route -- events.csv is the single source of
                    truth (CLAUDE.md §5), this table exists so /validation
                    can query event metadata by the same event_id the
                    live thresholds.run() result uses, without re-parsing
                    the CSV on every request.
- ValidationCache   caches thresholds.run()'s output (src/_detection.py
                    threshold_run) -- see src/config.py
                    VALIDATION_CACHE_TTL_HOURS. run() makes a real GEE
                    call (th_001 regional-proxy attempt), so this avoids
                    repeating it on every /validation request.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MonitoredSite(Base):
    __tablename__ = "monitored_sites"

    site_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)

    cache: Mapped["DetectionCache"] = relationship(
        back_populates="site", uselist=False, cascade="all, delete-orphan"
    )


class DetectionCache(Base):
    """Latest cached detect()/risk_level() result for one site -- one row
    per site, upserted in place (not an append-only history table)."""

    __tablename__ = "detection_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    site_id: Mapped[str] = mapped_column(ForeignKey("monitored_sites.site_id"), unique=True)

    target_date: Mapped[str] = mapped_column(String)  # "YYYY-MM-DD" the cache was computed for

    # -- detection (detect(), high confidence) --
    status: Mapped[str] = mapped_column(String)  # ok|no_imagery|no_water_pixels|no_climatology|error
    detected: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    anomaly_z: Mapped[float | None] = mapped_column(Float, nullable=True)
    index_used: Mapped[str | None] = mapped_column(String, nullable=True)
    index_values: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # -- prediction (risk_level(), rule-based, indicative) --
    level: Mapped[str | None] = mapped_column(String, nullable=True)  # normal|elevated|watch|warning
    triggered_rules: Mapped[list | None] = mapped_column(JSON, nullable=True)
    confidence_label: Mapped[str | None] = mapped_column(String, nullable=True)
    sst_anomaly: Mapped[float | None] = mapped_column(Float, nullable=True)
    trend_14d_rising: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    rainfall_mm: Mapped[float | None] = mapped_column(Float, nullable=True)

    # -- satellite metadata (surfaced whenever satellite-backed) --
    cloud_fraction: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_date: Mapped[str | None] = mapped_column(String, nullable=True)

    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    stale: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    site: Mapped["MonitoredSite"] = relationship(back_populates="cache")


class ValidationEvent(Base):
    """Mirrors data/validation/events.csv verbatim -- read-only relative
    to that file, never written to via any API route."""

    __tablename__ = "validation_events"

    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    date: Mapped[str | None] = mapped_column(String, nullable=True)
    date_start: Mapped[str | None] = mapped_column(String, nullable=True)
    date_end: Mapped[str | None] = mapped_column(String, nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    location_name: Mapped[str] = mapped_column(String)
    location_precision: Mapped[str] = mapped_column(String)
    species: Mapped[str] = mapped_column(String)
    cell_count: Mapped[str | None] = mapped_column(String, nullable=True)  # raw string, see thresholds.parse_cell_count
    event_type: Mapped[str] = mapped_column(String)
    source_type: Mapped[str] = mapped_column(String)
    source_citation: Mapped[str] = mapped_column(Text)
    confidence: Mapped[str] = mapped_column(String)


class ValidationCache(Base):
    """Cached thresholds.run() output. Single row (id=1, upserted) --
    this is a point-in-time snapshot of the calibration attempt, not a
    history table."""

    __tablename__ = "validation_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    payload: Mapped[dict] = mapped_column(JSON)
