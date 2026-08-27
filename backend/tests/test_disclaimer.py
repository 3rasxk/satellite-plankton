"""Every response model in src/schemas.py inherits DisclaimerMixin, so
`disclaimer` must be present and non-empty on every endpoint's response
body -- not left to convention. Checked here against real (DB-cache-only,
no GEE) responses for the endpoints that don't need any mocking, plus a
mocked-detection response for /detect."""

from __future__ import annotations

from src.routers import detect as detect_router
from src.schemas import DISCLAIMER_TEXT


def _valid_detect_result() -> dict:
    return {
        "anomaly_z": 0.3,
        "index_values": {"ndci": 0.01, "2bda": 0.02, "3bda": 0.03, "b2_b3_ratio": 0.9},
        "detected": False,
        "index_used": "ndci",
        "status": "ok",
        "reason": None,
    }


def test_detect_response_has_disclaimer(client, monkeypatch):
    monkeypatch.setattr(detect_router.bridge, "detect", lambda *a, **k: _valid_detect_result())
    monkeypatch.setattr(
        detect_router,
        "fetch_satellite_meta",
        lambda *a, **k: {"cloud_fraction": 0.1, "actual_date": "2024-03-14"},
    )

    resp = client.get("/detect", params={"lat": 13.2, "lng": 100.9, "date": "2024-03-15"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["disclaimer"] == DISCLAIMER_TEXT
    assert isinstance(body["disclaimer"], str) and len(body["disclaimer"]) > 0


def test_risk_map_response_and_every_feature_has_disclaimer(client):
    resp = client.get("/risk-map")
    assert resp.status_code == 200
    body = resp.json()
    assert body["disclaimer"] == DISCLAIMER_TEXT
    assert len(body["features"]) > 0  # MONITORED_GRID is seeded at startup
    for feature in body["features"]:
        props = feature["properties"]
        assert props["disclaimer"] == DISCLAIMER_TEXT
        assert len(props["disclaimer"]) > 0


def test_summary_response_has_disclaimer(client):
    resp = client.get("/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["disclaimer"] == DISCLAIMER_TEXT
    assert len(body["disclaimer"]) > 0


def test_watch_overlay_response_has_disclaimer(client):
    """The empty scheduler-cache state is still a complete public response."""
    resp = client.get("/watch-overlay")
    assert resp.status_code == 200
    body = resp.json()
    assert body["disclaimer"] == DISCLAIMER_TEXT
    assert len(body["disclaimer"]) > 0
