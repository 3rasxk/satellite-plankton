"""
Forces a real `GEEAuthError` through the running FastAPI app and asserts
a genuine 503 -- not code review. This exact failure mode (GEE auth
failing) was hit for real earlier in this project's build (Phase 1), so
"reviewed by inspection" is not enough here.

`routers/detect.py` makes one GEE-reaching call, `bridge.detect(...)`,
inside its own `try/except GEEAuthError` (router-level guard). It used to
make a second call (`fetch_satellite_meta`, a second Sentinel-2 read just
for `cloud_fraction`), which this file also guarded; detect() now returns
that scene's `cloud_fraction` itself, so the second read and its test are
gone (see tests/test_single_scene_read.py).

For completeness: `routers/timeseries.py` wraps its GEE-calling line in
its own try/except; `routers/risk_map.py`/`routers/summary.py` never call into `bridge` at
all (DB-cache only) -- so `/detect` was the only endpoint with a
GEE-calling line outside a router-level guard.
"""

from __future__ import annotations

from src import _detection as bridge
from src.routers import detect as detect_router


def _valid_detect_result() -> dict:
    return {
        "index_values": {"ndci": 0.01, "2bda": 0.02, "3bda": 0.03, "b2_b3_ratio": 0.9},
        "actual_date": "2024-03-14",
        "index_used": "ndci",
        "status": "ok",
        "reason": None,
    }


def _no_traceback_leaked(resp) -> bool:
    text = resp.text
    return "Traceback (most recent call last)" not in text and "File \"" not in text


def test_detect_router_level_geeautherror_to_503(client, monkeypatch):
    """`bridge.detect()` itself raising GEEAuthError -- caught by
    routers/detect.py's own try/except (router-level guard)."""

    def _raise(*_a, **_k):
        raise bridge.GEEAuthError("forced for test -- router-level path")

    monkeypatch.setattr(detect_router.bridge, "detect", _raise)

    resp = client.get("/detect", params={"lat": 13.2, "lng": 100.9, "date": "2024-03-15"})

    assert resp.status_code == 503
    assert _no_traceback_leaked(resp)
    body = resp.json()
    assert "detail" in body
    assert "not authenticated" in body["detail"]
    # routers/detect.py's own message is distinctively worded --
    # confirms *this* handler (not main.py's) produced the response.
    assert "the pipeline is unusable" in body["detail"]


def test_timeseries_router_level_geeautherror_to_503(client, monkeypatch):
    """routers/timeseries.py's sole GEE-calling line
    (`get_modis_chlorophyll_history`) is already inside its own
    try/except -- confirms that path is router-guarded, not relying on
    the app-level handler."""

    def _raise(*_a, **_k):
        raise bridge.GEEAuthError("forced for test -- timeseries router-level path")

    monkeypatch.setattr(bridge, "get_modis_chlorophyll_history", _raise)

    resp = client.get("/timeseries", params={"lat": 13.2, "lng": 100.9})
    assert resp.status_code == 503
    assert _no_traceback_leaked(resp)
    assert "not authenticated" in resp.json()["detail"]
