"""
Forces a real `GEEAuthError` through the running FastAPI app and asserts
a genuine 503 -- not code review. This exact failure mode (GEE auth
failing) was hit for real earlier in this project's build (Phase 1), so
"reviewed by inspection" is not enough here.

Two calls in `routers/detect.py` are exercised:

1. Its first call, `bridge.detect(...)` -- always had its own
   `try/except GEEAuthError` (router-level guard).
2. Its second call, `fetch_satellite_meta(...)` (`src/satellite_meta.py`),
   made after the first try/except block closes, to fetch
   `cloud_fraction`/`actual_date` for the response. This test originally
   found that call unguarded -- if `bridge.detect()` succeeded but this
   second call then hit `GEEAuthError`, nothing in `routers/detect.py`
   caught it, and only `main.py`'s app-level
   `@app.exception_handler(bridge.GEEAuthError)` turned it into a 503
   instead of a raw 500 falling through with the wrong (generic) message.
   That gap has since been fixed -- `routers/detect.py` now wraps this
   second call the same way as the first -- and this test was updated to
   assert the fixed behavior (router-level message, not the generic
   app-level one) as a regression guard.

For completeness: `routers/timeseries.py` and `routers/validation.py`
each wrap their sole GEE-calling line in their own try/except already;
`routers/risk_map.py`/`routers/summary.py` never call into `bridge` at
all (DB-cache only) -- so `/detect` was the only endpoint with a
GEE-calling line outside a router-level guard.
"""

from __future__ import annotations

from src import _detection as bridge
from src import satellite_meta as satellite_meta_module
from src.routers import detect as detect_router


def _valid_detect_result() -> dict:
    return {
        "anomaly_z": -1.2,
        "index_values": {"ndci": 0.01, "2bda": 0.02, "3bda": 0.03, "b2_b3_ratio": 0.9},
        "detected": False,
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


def test_detect_second_call_geeautherror_to_503_via_satellite_meta(client, monkeypatch):
    """`bridge.detect()` succeeds; the second call
    (`fetch_satellite_meta` -> `bridge.get_sentinel2_bands`) raises
    GEEAuthError instead. Regression guard for a gap this test suite
    found: that second call used to be unguarded in routers/detect.py,
    so this used to fall through to main.py's generic app-level handler.
    routers/detect.py now wraps it the same way as the first call, so
    this must now produce the same router-level message as the
    router-level test above, not the generic one."""

    monkeypatch.setattr(detect_router.bridge, "detect", lambda *a, **k: _valid_detect_result())

    def _raise(*_a, **_k):
        raise bridge.GEEAuthError("forced for test -- second-call path")

    monkeypatch.setattr(satellite_meta_module.bridge, "get_sentinel2_bands", _raise)

    resp = client.get("/detect", params={"lat": 13.2, "lng": 100.9, "date": "2024-03-15"})

    assert resp.status_code == 503
    assert _no_traceback_leaked(resp)
    body = resp.json()
    assert "detail" in body
    assert "not authenticated" in body["detail"]
    assert "forced for test -- second-call path" in body["detail"]
    # Now router-guarded like the first call -- the specific message
    # should appear, confirming routers/detect.py's own except block
    # (not main.py's generic fallback) produced this response.
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
