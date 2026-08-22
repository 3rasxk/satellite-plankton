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
