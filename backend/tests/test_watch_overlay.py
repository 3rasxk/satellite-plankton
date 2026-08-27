"""Contract tests for the cache-only ``GET /watch-overlay`` endpoint."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src import main as main_module
from src.db import SessionLocal, init_db
from src.db_models import WatchOverlayCache
from src.schemas import WATCH_OVERLAY_CAVEAT


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
                stale=True,
                error="Scheduler refresh failed after this cached run.",
                caveat="Obsolete scheduler-owned caveat text.",
            )
        )
        db.commit()
    finally:
        db.close()

    def forbidden(*args, **kwargs):
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
    assert "map_id" not in body
