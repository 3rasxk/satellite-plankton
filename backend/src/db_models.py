"""SQLAlchemy ORM models for monitoring sites, regional scans, and raster
scans.

- MonitoredSite     the grid `/risk-map`, `/summary`, and the scheduler
                    operate over (src/grid.py MONITORED_GRID, upserted at
                    startup). Deliberately chosen monitoring points.
- DetectionCache    one row per MonitoredSite, upserted by the scheduler
                    (src/scheduler.py) with the latest risk_level()/
                    detect() result. This is what /risk-map and /summary
                    actually read -- they never hit GEE live in normal
                    operation (CLAUDE.md's "don't hit GEE live on every
                    /risk-map request in production shape").
                    `stale` distinguishes "the last scheduler run for this
                    site failed, this is old data" from "this is the
                    latest real reading" -- a failed refresh must never
                    silently look like a fresh one. Also carries
                    pre-rendered true-color/NDCI-heatmap PNG bytes
                    (`true_color_png`/`ndci_heatmap_png`) refreshed on the
                    same cycle -- see scheduler.py for why this bounded
                    7-site grid is cached rather than rendered on demand.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text
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

    # -- Sentinel-2 index reading; anomaly detection is not computed --
    status: Mapped[str] = mapped_column(String)  # ok|no_imagery|no_water_pixels|no_climatology|error
    detected: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    spatial_anomaly_z: Mapped[float | None] = mapped_column(Float, nullable=True)
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

    # -- pre-rendered satellite imagery (scheduler-cached, see scheduler.py
    # _refresh_images) -- PNG bytes of the same resolved Sentinel-2 scene
    # `actual_date`/`cloud_fraction` above describe (data-pipeline/src/
    # imagery.py's same-scene guarantee). Only this monitored 7-site grid
    # gets images pre-rendered and cached this way; /detect and
    # /satellite-image render on demand instead -- see scheduler.py's
    # docstring / the backend-api build report for the latency reasoning
    # behind that split.
    true_color_png: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    ndci_heatmap_png: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    image_status: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # ok|skipped_detection_not_ok|no_imagery|no_water_pixels|fetch_error|not_attempted
    image_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    stale: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    site: Mapped["MonitoredSite"] = relationship(back_populates="cache")


class RegionalScanRun(Base):
    """One row per full-polygon regional-scan run (history kept -- small
    rows, cheap). See docs/superpowers/specs/2026-08-31-regional-scan-design.md
    §6. `newest_scene_date` is the max Sentinel-2 scene timestamp the
    triggering poll considered -- read back by the next poll as its
    comparison baseline (spec §5)."""

    __tablename__ = "regional_scan_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String)  # running|ok|partial_error|error
    grid_spacing_km: Mapped[float] = mapped_column(Float)
    date_used: Mapped[str] = mapped_column(String)
    newest_scene_date: Mapped[str | None] = mapped_column(String, nullable=True)
    total_points: Mapped[int] = mapped_column(Integer)
    count_ok: Mapped[int] = mapped_column(Integer, default=0)
    count_no_imagery: Mapped[int] = mapped_column(Integer, default=0)
    count_no_water_pixels: Mapped[int] = mapped_column(Integer, default=0)
    count_no_climatology: Mapped[int] = mapped_column(Integer, default=0)
    count_error: Mapped[int] = mapped_column(Integer, default=0)


class RasterScanRun(Base):
    """One row per whole-polygon raster scan (history kept -- small rows).

    Metadata only: the raster itself is far too large for a DB column
    (~50,000 cells x 7 values at the 200 m default, and four times that
    at 100 m), so the cells live in one compressed file on disk and this
    row records where. `blob_path` is that file; it is nulled, and
    `blob_deleted_at` set, once retention has expired the run
    (`src/raster_scan/storage.py`). A row whose `blob_path` is null is
    NOT an incomplete run -- check `status`: an expired 'ok' run still
    has its `summary`, it just no longer has its cells.

    `summary` is written when the run completes, not when retention
    fires. Deliberate: if the summary were only computed at expiry, a
    blob that had since been corrupted or removed by something other than
    retention would take the whole run's findings with it on day 31, and
    the failure would surface a month after the scan it belonged to.

    On dates: `date_used` is the day the run asked about, and it is NOT
    the date of the data. Each cell carries its own acquisition
    timestamp, because the composite is a most-recent-wins mosaic over
    every scene in the window -- one raster routinely mixes several
    acquisitions (the same reason RegionalScanCluster carries a scene-date
    *range* rather than one date). `oldest_scene_date`/`newest_scene_date`
    state that span here; they are the real span of the scenes that
    contributed, never backfilled from `date_used`.
    """

    __tablename__ = "raster_scan_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String)  # running|ok|no_data|error

    date_used: Mapped[str] = mapped_column(String)  # "YYYY-MM-DD" asked about
    scale_m: Mapped[int] = mapped_column(Integer)  # read scale (RASTER_SCAN_SCALE_M)
    retention_days: Mapped[int] = mapped_column(Integer)  # the policy in force for THIS run

    # -- what the composite was built from --
    scene_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    oldest_scene_date: Mapped[str | None] = mapped_column(String, nullable=True)
    newest_scene_date: Mapped[str | None] = mapped_column(String, nullable=True)

    # -- the raster itself --
    cell_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    blob_path: Mapped[str | None] = mapped_column(String, nullable=True)
    blob_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    blob_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Whole-raster reduction kept after the blob goes. Carries the reducer
    # each band was aggregated with, so a reader of an old summary can see
    # that the acquisition date was selected (mode) and not averaged --
    # see data-pipeline/src/raster.py's RASTER_BAND_REDUCERS.
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Where the rendered map overlay for this run lives, and the
    # geographic bounds it must be placed at (src/raster_scan/render.py).
    # Carries the legend with it: an overlay's grey hatch means "inside
    # the study area, nothing usable was read here" and must never be
    # captioned as a low reading, so the meaning of each of the three
    # drawn states travels with the paths rather than being re-guessed by
    # whatever displays them.
    #
    # Null means no overlay: never rendered, or rendered and then removed
    # with the cells by retention (the PNGs are derived from the blob and
    # cannot be redrawn once it is gone). A failed render stores
    # {"status": "error", ...} instead, so a failure is a recorded fact
    # rather than an absence indistinguishable from the other two.
    overlay: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class RegionalScanPoint(Base):
    """Latest-run snapshot, upserted by `point_id` (not appended) --
    same overwrite-latest convention as DetectionCache. No-data points
    are stored with their real status, never omitted (spec §0/§6).
    `point_id` is f"{row_idx}_{col_idx}" -- stable across runs at the
    same grid spacing (backend/src/regional_scan/grid.py)."""

    __tablename__ = "regional_scan_points"

    point_id: Mapped[str] = mapped_column(String, primary_key=True)
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    row_idx: Mapped[int] = mapped_column(Integer)
    col_idx: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String)  # ok|no_imagery|no_water_pixels|no_climatology|error
    index_values: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Reserved for a future valid statistic. Always null in current scans.
    spatial_anomaly_z: Mapped[float | None] = mapped_column(Float, nullable=True)
    threshold_tier: Mapped[str | None] = mapped_column(String, nullable=True)  # elevated|warning|null
    # The real Sentinel-2 scene date backing THIS point's reading, straight
    # from detect() (detection/src/prediction.py). It routinely differs from
    # the run's `date_used`: each point independently resolves the newest
    # usable scene on or before the target date, so one scan's points are
    # normally backed by scenes of several different vintages. Null when no
    # scene was ever resolved for this point (status no_imagery /
    # no_water_pixels / error) -- never backfilled with `date_used`.
    actual_date: Mapped[str | None] = mapped_column(String, nullable=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("regional_scan_runs.id"))


class RegionalScanCluster(Base):
    """Latest-run snapshot -- deleted and reinserted whole each run
    (unlike RegionalScanPoint's stable point_id, cluster membership can
    change entirely between runs). Computed only over real, status='ok'
    member cells by construction -- only already-flagged 'ok' points are
    ever clustered (spec §4)."""

    __tablename__ = "regional_scan_clusters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("regional_scan_runs.id"))
    centroid_lat: Mapped[float] = mapped_column(Float)
    centroid_lng: Mapped[float] = mapped_column(Float)
    cell_count: Mapped[int] = mapped_column(Integer)
    mean_spatial_anomaly_z: Mapped[float] = mapped_column(Float)
    max_spatial_anomaly_z: Mapped[float] = mapped_column(Float)
    threshold_tier: Mapped[str] = mapped_column(String)  # elevated|warning
    member_point_ids: Mapped[list] = mapped_column(JSON)
    # This cluster's scene-freshness range, from its members' own
    # RegionalScanPoint.actual_date values (spec §12). Members are merged
    # by grid adjacency alone, never by date, and a single scan's points
    # are routinely backed by Sentinel-2 scenes several days apart
    # (measured spans of 7, 5 and 10 days), so a cluster genuinely can
    # mix vintages -- these columns state by how much rather than leaving
    # one pin to imply a single date.
    #
    # Note `RegionalScanRun.newest_scene_date` above is a DIFFERENT
    # quantity that happens to share a name: that one is the triggering
    # poll's max scene timestamp for the whole run (a full ISO
    # timestamp). This one is a date-only max over one cluster's members.
    #
    # All three are null together, and only together, when any member has
    # no usable scene date -- never partially filled, never backfilled
    # from the run's `date_used` (see clustering._scene_date_range).
    oldest_scene_date: Mapped[str | None] = mapped_column(String, nullable=True)
    newest_scene_date: Mapped[str | None] = mapped_column(String, nullable=True)
    scene_date_span_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
