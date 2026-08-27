"""Contract tests for the cache-only ``GET /watch-overlay`` endpoint."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from src import main as main_module
from src import scheduler as scheduler_module
from src.config import as_aware_utc
from src.db import SessionLocal, init_db
from src.db_models import MonitoredSite, WatchOverlayCache
from src.grid import MONITORED_GRID
from src.schemas import WATCH_OVERLAY_CAVEAT
from src.scheduler import refresh_watch_overlay


def analysis_metadata_payload() -> dict:
    return {
        "version": 2,
        "levels": [
            {
                "code": "elevated",
                "class_code": 1,
                "label_th": "เริ่มผิดปกติ",
                "color": "#34C759",
                "min_z": 1.5,
                "requires_rising_trend": False,
                "requires_sst_above_normal": False,
            },
            {
                "code": "watch",
                "class_code": 2,
                "label_th": "เฝ้าระวัง",
                "color": "#FF9F0A",
                "min_z": 1.5,
                "requires_rising_trend": True,
                "requires_sst_above_normal": False,
            },
            {
                "code": "warning",
                "class_code": 3,
                "label_th": "เตือนภัย",
                "color": "#FF3B30",
                "min_z": 2.0,
                "requires_rising_trend": True,
                "requires_sst_above_normal": True,
            },
        ],
        "trend": {
            "window_days": 14,
            "min_distinct_dates": 2,
            "slope_units": "ndci_per_day",
            "rising_rule": "slope_per_day > 0",
        },
        "sst": {
            "collection_id": "NASA/OCEANDATA/MODIS-Aqua/L3SMI",
            "search_window_days": 5,
            "climatology_window_days": 7,
            "resolution_m": 4638,
            "above_normal_rule": "current_sst > seasonal_sst",
        },
        "masks": {
            "water_mask": "gulf_connected_historical_surface_water",
            "water_occurrence_pct": 50.0,
            "scl_water_class": 6,
            "qa60_cloud_bit": 10,
            "qa60_cirrus_bit": 11,
        },
        "resolutions": {
            "output_grid_m": 10,
            "ndci_m": 20,
            "trend_m": 20,
            "sst_m": 4638,
        },
        "newest_sentinel_scene_date": "2026-08-26",
        "newest_sst_scene_date": "2026-08-25",
        "mosaic_caveat": "Sentinel-2 and SST mosaic pixels may come from different dates.",
        "site_alerts": [
            {
                "site_id": "chaophraya_mouth",
                "name": "Chao Phraya River mouth, Samut Prakan",
                "lat": 13.45,
                "lng": 100.65,
                "level": "elevated",
                "label_th": "เริ่มผิดปกติ",
                "color": "#34C759",
                "ndci_z": 1.7,
                "latest_scene_date": "2026-08-26",
                "trend_slope_per_day": None,
                "trend_observations": 1,
                "trend_rising": False,
                "current_sst": None,
                "seasonal_sst": None,
                "sst_date": None,
                "sst_above_normal": False,
            },
            {
                "site_id": "bangpakong_mouth",
                "name": "Bang Pakong River mouth, Chachoengsao",
                "lat": 13.47,
                "lng": 100.98,
                "level": "warning",
                "label_th": "เตือนภัย",
                "color": "#FF3B30",
                "ndci_z": 2.4,
                "latest_scene_date": "2026-08-26",
                "trend_slope_per_day": 0.01,
                "trend_observations": 3,
                "trend_rising": True,
                "current_sst": 30.2,
                "seasonal_sst": 29.8,
                "sst_date": "2026-08-25",
                "sst_above_normal": True,
            },
        ],
    }


def successful_overlay_payload(target_date: str) -> dict:
    return {
        "status": "ok",
        "tile_url": "https://tiles.example/{z}/{x}/{y}",
        "map_id": "pytest-map-id",
        "generated_at": "2026-08-27T02:00:00+00:00",
        "target_date": target_date,
        "source_window_start": "2026-07-29",
        "source_window_end": target_date,
        "newest_scene_date": "2026-08-26",
        "baseline_periods": [
            {"start": "2025-08-12", "end_exclusive": "2025-09-12"},
            {"start": "2024-08-12", "end_exclusive": "2024-09-12"},
            {"start": "2023-08-12", "end_exclusive": "2023-09-12"},
            {"start": "2022-08-12", "end_exclusive": "2022-09-12"},
            {"start": "2021-08-12", "end_exclusive": "2021-09-12"},
        ],
        "threshold_z": 1.5,
        "baseline_years": 5,
        "seasonal_window_days": 15,
        "min_baseline_observations": 5,
        "water_occurrence_pct": 50.0,
        "water_mask": "gulf_connected_historical_surface_water",
        "output_grid_m": 10,
        "effective_resolution_m": 20,
        "color": "#FF9F0A",
        "caveat": WATCH_OVERLAY_CAVEAT,
        "analysis_metadata": analysis_metadata_payload(),
    }


def persisted_overlay_values(row: WatchOverlayCache) -> dict:
    """Snapshot every database column, normalizing SQLite timestamps."""
    values = {
        column.name: deepcopy(getattr(row, column.name))
        for column in WatchOverlayCache.__table__.columns
    }
    if values["generated_at"] is not None:
        values["generated_at"] = as_aware_utc(values["generated_at"])
    return values


def _clear_watch_overlay_cache() -> None:
    """Remove the singleton so shared SQLite state cannot leak between tests."""
    init_db()
    db = SessionLocal()
    try:
        row = db.get(WatchOverlayCache, 1)
        if row is not None:
            db.delete(row)
            db.commit()
    finally:
        db.close()


@pytest.fixture(autouse=True)
def clean_watch_overlay_cache():
    _clear_watch_overlay_cache()
    yield
    _clear_watch_overlay_cache()


def test_watch_overlay_empty_cache_is_explicit_and_has_no_tile(client):
    """A fresh deployment must report an uninitialized cache, not fake data."""
    response = client.get("/watch-overlay")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "error"
    assert body["tile_url"] is None
    assert body["stale"] is True
    assert "not initialized" in body["error"].lower()
    assert body["disclaimer"]
    assert body["caveat"] == WATCH_OVERLAY_CAVEAT


def test_watch_overlay_returns_cached_run_without_calling_gee(client, monkeypatch):
    """The HTTP path must serve the stored singleton without touching GEE."""
    db = SessionLocal()
    try:
        db.add(
            WatchOverlayCache(
                id=1,
                status="ok",
                tile_url="https://earthengine.example/tiles/{z}/{x}/{y}",
                map_id="scheduler-internal-map-id",
                generated_at=datetime(2026, 8, 27, 9, 30, tzinfo=timezone.utc),
                target_date="2026-08-27",
                source_window_start="2026-08-20",
                source_window_end="2026-08-27",
                newest_scene_date="2026-08-26",
                baseline_periods=[{"start": "2021-08-20", "end": "2025-08-27"}],
                threshold_z=1.5,
                baseline_years=5,
                seasonal_window_days=14,
                min_baseline_observations=3,
                water_occurrence_pct=50.0,
                water_mask="gulf_connected_historical_surface_water",
                output_grid_m=10,
                effective_resolution_m=20,
                color="ff0000",
                analysis_metadata=analysis_metadata_payload(),
                stale=True,
                error="Scheduler refresh failed after this cached run.",
                caveat="Obsolete scheduler-owned caveat text.",
            )
        )
        db.commit()
    finally:
        db.close()

    def forbidden(_target_date, _monitoring_sites):
        raise AssertionError("request path must not call Earth Engine")

    monkeypatch.setattr(main_module.bridge, "build_configured_ndci_watch_overlay", forbidden)
    response = client.get("/watch-overlay")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["tile_url"].startswith("https://")
    assert body["threshold_z"] == 1.5
    assert body["output_grid_m"] == 10
    assert body["effective_resolution_m"] == 20
    assert body["water_mask"] == "gulf_connected_historical_surface_water"
    assert body["generated_at"] == "2026-08-27T09:30:00+00:00"
    assert body["source_window_start"] == "2026-08-20"
    assert body["source_window_end"] == "2026-08-27"
    assert body["baseline_periods"] == [{"start": "2021-08-20", "end": "2025-08-27"}]
    assert body["stale"] is True
    assert body["error"] == "Scheduler refresh failed after this cached run."
    assert body["caveat"] == WATCH_OVERLAY_CAVEAT
    assert body["analysis_metadata"]["version"] == 2
    assert [
        item["level"] for item in body["analysis_metadata"]["site_alerts"]
    ] == ["elevated", "warning"]
    assert all(
        item["level"] != "normal"
        for item in body["analysis_metadata"]["site_alerts"]
    )
    assert "map_id" not in body


def test_watch_overlay_legacy_cached_run_returns_null_analysis_metadata(client):
    db = SessionLocal()
    try:
        db.add(
            WatchOverlayCache(
                id=1,
                status="ok",
                tile_url="https://earthengine.example/tiles/{z}/{x}/{y}",
                map_id="scheduler-internal-map-id",
                stale=False,
                caveat="Obsolete scheduler-owned caveat text.",
            )
        )
        db.commit()
    finally:
        db.close()

    body = client.get("/watch-overlay").json()

    assert body["analysis_metadata"] is None
    assert "map_id" not in body


def test_refresh_watch_overlay_writes_singleton_success(client, monkeypatch):
    monkeypatch.setattr(
        scheduler_module.bridge,
        "build_configured_ndci_watch_overlay",
        lambda target_date, monitoring_sites: successful_overlay_payload(target_date),
    )

    with SessionLocal() as db:
        refresh_watch_overlay(db, "2026-08-27")
        row = db.get(WatchOverlayCache, 1)
        assert row.status == "ok"
        assert row.tile_url.endswith("/{z}/{x}/{y}")
        assert row.map_id == "pytest-map-id"
        assert as_aware_utc(row.generated_at) == datetime(2026, 8, 27, 2, tzinfo=timezone.utc)
        assert row.target_date == "2026-08-27"
        assert row.source_window_start == "2026-07-29"
        assert row.source_window_end == "2026-08-27"
        assert row.newest_scene_date == "2026-08-26"
        assert row.baseline_periods == successful_overlay_payload("2026-08-27")["baseline_periods"]
        assert row.threshold_z == 1.5
        assert row.baseline_years == 5
        assert row.seasonal_window_days == 15
        assert row.min_baseline_observations == 5
        assert row.water_occurrence_pct == 50.0
        assert row.water_mask == "gulf_connected_historical_surface_water"
        assert row.output_grid_m == 10
        assert row.effective_resolution_m == 20
        assert row.color == "#FF9F0A"
        assert row.analysis_metadata == successful_overlay_payload("2026-08-27")["analysis_metadata"]
        assert all(item["level"] != "normal" for item in row.analysis_metadata["site_alerts"])
        assert row.caveat == WATCH_OVERLAY_CAVEAT
        assert row.stale is False
        assert row.error is None


def test_refresh_failure_preserves_every_last_good_field_except_freshness(client, monkeypatch):
    successful = successful_overlay_payload("2026-08-27")
    monkeypatch.setattr(
        scheduler_module.bridge,
        "build_configured_ndci_watch_overlay",
        lambda target_date, monitoring_sites: successful,
    )
    with SessionLocal() as db:
        refresh_watch_overlay(db, "2026-08-27")
        db.expire_all()
        original = persisted_overlay_values(db.get(WatchOverlayCache, 1))

    def fail(_target_date, _monitoring_sites):
        raise scheduler_module.bridge.GEEAuthError("forced auth failure")

    monkeypatch.setattr(scheduler_module.bridge, "build_configured_ndci_watch_overlay", fail)
    with SessionLocal() as db:
        refresh_watch_overlay(db, "2026-08-28")
        refreshed = persisted_overlay_values(db.get(WatchOverlayCache, 1))

    assert {
        field: value
        for field, value in refreshed.items()
        if field not in {"stale", "error"}
    } == {
        field: value
        for field, value in original.items()
        if field not in {"stale", "error"}
    }
    assert refreshed["stale"] is True
    assert "GEEAuthError" in refreshed["error"]


def test_refresh_commit_failure_rolls_back_and_preserves_last_good_row(client, monkeypatch):
    monkeypatch.setattr(
        scheduler_module.bridge,
        "build_configured_ndci_watch_overlay",
        lambda target_date, monitoring_sites: successful_overlay_payload(target_date),
    )
    with SessionLocal() as db:
        refresh_watch_overlay(db, "2026-08-27")
        db.expire_all()
        original = persisted_overlay_values(db.get(WatchOverlayCache, 1))

    invalid = successful_overlay_payload("2026-08-28")
    invalid["status"] = None
    monkeypatch.setattr(
        scheduler_module.bridge,
        "build_configured_ndci_watch_overlay",
        lambda _target_date, _monitoring_sites: invalid,
    )

    with SessionLocal() as db:
        refresh_watch_overlay(db, "2026-08-28")
        refreshed = persisted_overlay_values(db.get(WatchOverlayCache, 1))

    assert {
        field: value
        for field, value in refreshed.items()
        if field not in {"stale", "error"}
    } == {
        field: value
        for field, value in original.items()
        if field not in {"stale", "error"}
    }
    assert refreshed["stale"] is True
    assert "IntegrityError" in refreshed["error"]


def test_malformed_config_records_minimal_error_singleton_without_duplication(client, monkeypatch):
    def malformed_builder(_target_date, _monitoring_sites):
        raise KeyError("ndci_watch_overlay")

    def malformed_config():
        raise KeyError("ndci_watch_overlay")

    monkeypatch.setattr(
        scheduler_module.bridge,
        "build_configured_ndci_watch_overlay",
        malformed_builder,
    )
    monkeypatch.setattr(
        scheduler_module.bridge,
        "load_watch_overlay_config",
        malformed_config,
    )

    with SessionLocal() as db:
        refresh_watch_overlay(db, "2026-08-27")
        refresh_watch_overlay(db, "2026-08-28")
        row = db.get(WatchOverlayCache, 1)
        assert db.scalar(select(func.count()).select_from(WatchOverlayCache)) == 1
        assert row.status == "error"
        assert row.tile_url is None
        assert row.map_id is None
        assert row.generated_at is None
        assert row.target_date == "2026-08-28"
        assert row.threshold_z is None
        assert row.baseline_years is None
        assert row.seasonal_window_days is None
        assert row.min_baseline_observations is None
        assert row.water_occurrence_pct is None
        assert row.water_mask is None
        assert row.output_grid_m is None
        assert row.effective_resolution_m is None
        assert row.color is None
        assert row.analysis_metadata is None
        assert row.stale is True
        assert "KeyError" in row.error
        assert "configuration metadata unavailable" in row.error
        assert row.caveat == WATCH_OVERLAY_CAVEAT


def test_first_no_imagery_refresh_records_configured_no_tile_metadata(client, monkeypatch):
    config = {
        "threshold_z": 1.5,
        "baseline_years": 5,
        "seasonal_window_days": 15,
        "min_baseline_observations": 5,
        "water_occurrence_pct": 50.0,
        "output_scale_m": 10,
        "effective_resolution_m": 20,
        "color": "#FF9F0A",
    }

    def no_imagery(_target_date, _monitoring_sites):
        raise scheduler_module.bridge.NoWatchOverlayImageryError("no configured current imagery")

    monkeypatch.setattr(scheduler_module.bridge, "build_configured_ndci_watch_overlay", no_imagery)
    monkeypatch.setattr(scheduler_module.bridge, "load_watch_overlay_config", lambda: config)

    with SessionLocal() as db:
        refresh_watch_overlay(db, "2026-08-27")
        row = db.get(WatchOverlayCache, 1)
        assert row.status == "no_imagery"
        assert row.tile_url is None
        assert row.map_id is None
        assert row.generated_at is None
        assert row.target_date == "2026-08-27"
        assert row.threshold_z == 1.5
        assert row.baseline_years == 5
        assert row.seasonal_window_days == 15
        assert row.min_baseline_observations == 5
        assert row.water_occurrence_pct == 50.0
        assert row.water_mask == "gulf_connected_historical_surface_water"
        assert row.output_grid_m == 10
        assert row.effective_resolution_m == 20
        assert row.color == "#FF9F0A"
        assert row.caveat == WATCH_OVERLAY_CAVEAT
        assert row.analysis_metadata is None
        assert row.stale is False
        assert "NoWatchOverlayImageryError" in row.error


def test_first_unexpected_refresh_records_single_error_row_and_reuses_no_tile_singleton(client, monkeypatch):
    config = {
        "threshold_z": 1.5,
        "baseline_years": 5,
        "seasonal_window_days": 15,
        "min_baseline_observations": 5,
        "water_occurrence_pct": 50.0,
        "output_scale_m": 10,
        "effective_resolution_m": 20,
        "color": "#FF9F0A",
    }

    def unexpected(_target_date, _monitoring_sites):
        raise RuntimeError("forced unexpected failure")

    monkeypatch.setattr(scheduler_module.bridge, "build_configured_ndci_watch_overlay", unexpected)
    monkeypatch.setattr(scheduler_module.bridge, "load_watch_overlay_config", lambda: config)

    with SessionLocal() as db:
        refresh_watch_overlay(db, "2026-08-27")
        refresh_watch_overlay(db, "2026-08-28")
        row = db.get(WatchOverlayCache, 1)
        assert db.scalar(select(func.count()).select_from(WatchOverlayCache)) == 1
        assert row.status == "error"
        assert row.tile_url is None
        assert row.map_id is None
        assert row.generated_at is None
        assert row.target_date == "2026-08-28"
        assert row.stale is True
        assert "RuntimeError" in row.error
        assert row.analysis_metadata is None


def test_refresh_watch_overlay_passes_supplied_sites_in_their_existing_order(client, monkeypatch):
    """The builder receives exactly one normalized payload in refresh-grid order."""
    supplied_sites = [
        MonitoredSite(site_id="second", name="Second", lat=13.2, lng=100.2),
        MonitoredSite(site_id="first", name="First", lat=13.1, lng=100.1),
    ]
    builder_calls = []
    monkeypatch.setattr(
        scheduler_module.bridge,
        "build_configured_ndci_watch_overlay",
        lambda target_date, monitoring_sites: builder_calls.append(
            (target_date, monitoring_sites)
        ) or successful_overlay_payload(target_date),
    )

    with SessionLocal() as db:
        refresh_watch_overlay(db, "2026-08-27", supplied_sites)

    assert builder_calls == [
        (
            "2026-08-27",
            [
                {"site_id": "second", "name": "Second", "lat": 13.2, "lng": 100.2},
                {"site_id": "first", "name": "First", "lat": 13.1, "lng": 100.1},
            ],
        )
    ]


def test_refresh_watch_overlay_queries_sites_by_site_id_when_not_supplied(client, monkeypatch):
    """Ad-hoc overlay refreshes use a deterministic database ordering."""
    builder_calls = []
    monkeypatch.setattr(
        scheduler_module.bridge,
        "build_configured_ndci_watch_overlay",
        lambda target_date, monitoring_sites: builder_calls.append(
            (target_date, monitoring_sites)
        ) or successful_overlay_payload(target_date),
    )

    with SessionLocal() as db:
        refresh_watch_overlay(db, "2026-08-27")

    assert builder_calls == [
        (
            "2026-08-27",
            sorted(MONITORED_GRID, key=lambda site: site["site_id"]),
        )
    ]
