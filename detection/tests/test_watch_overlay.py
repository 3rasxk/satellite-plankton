"""Tests for the config-driven NDCI watch-overlay bridge, without GEE."""

from src import watch_overlay


def test_configured_overlay_passes_every_approved_value(monkeypatch):
    """The configured wrapper must preserve each approved pipeline default."""
    calls = []

    def fake_builder(target_date, **kwargs):
        calls.append((target_date, kwargs))
        return {"status": "ok"}

    monkeypatch.setattr(watch_overlay, "build_ndci_watch_overlay", fake_builder)
    sites = [{"site_id": "a", "name": "A", "lat": 13.0, "lng": 100.7}]
    result = watch_overlay.build_configured_ndci_watch_overlay("2026-08-27", sites)

    assert result == {"status": "ok"}
    assert calls == [("2026-08-27", {
        "threshold_z": 1.5,
        "warning_threshold_z": 2.0,
        "latest_window_days": 30,
        "baseline_years": 5,
        "seasonal_window_days": 15,
        "min_baseline_observations": 5,
        "trend_window_days": 14,
        "min_trend_observations": 2,
        "sst_search_window_days": 5,
        "sst_climatology_window_days": 7,
        "sst_resolution_m": 4638,
        "water_occurrence_pct": 50.0,
        "gulf_seed_points": [[13.0, 100.7], [13.15, 100.82]],
        "output_scale_m": 10,
        "effective_resolution_m": 20,
        "level_colors": {"elevated": "#34C759", "watch": "#FF9F0A", "warning": "#FF3B30"},
        "monitoring_sites": sites,
    })]
