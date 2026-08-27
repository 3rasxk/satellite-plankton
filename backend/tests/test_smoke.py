"""Smoke test: TestClient boots against the isolated SQLite DB (never
backend/data/app.db) with the scheduler stubbed out, and the root route
responds. Proves conftest.py's fixture wiring before the more targeted
tests below rely on it."""

from __future__ import annotations


def test_root_ok(client):
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"].startswith("Gulf of Thailand")


def test_detection_bridge_exposes_configured_watch_overlay():
    from src import _detection

    assert callable(_detection.build_configured_ndci_watch_overlay)
    assert callable(_detection.load_watch_overlay_config)
    assert isinstance(_detection.NoWatchOverlayImageryError, type)
