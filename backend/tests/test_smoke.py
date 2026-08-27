"""Smoke test: TestClient boots against the isolated SQLite DB (never
backend/data/app.db) with the scheduler stubbed out, and the root route
responds. Proves conftest.py's fixture wiring before the more targeted
tests below rely on it."""

from __future__ import annotations

import inspect


def test_root_ok(client):
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"].startswith("Gulf of Thailand")


def test_detection_bridge_exposes_configured_watch_overlay():
    from src import _detection as bridge

    assert callable(bridge.build_configured_ndci_watch_overlay)
    parameters = inspect.signature(bridge.build_configured_ndci_watch_overlay).parameters
    assert "target_date" in parameters
    assert "monitoring_sites" in parameters
    assert callable(bridge.load_watch_overlay_config)
    assert isinstance(bridge.NoWatchOverlayImageryError, type)
