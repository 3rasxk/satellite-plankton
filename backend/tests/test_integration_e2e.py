"""
Phase 5 (integration-docs) end-to-end tests -- backend-level pytest
integration tests, per the same convention the rest of this suite already
uses (real FastAPI TestClient, real isolated SQLite DB via conftest.py,
GEE calls mocked at the `bridge` boundary rather than the whole HTTP
layer faked). A browser-e2e framework was deliberately not introduced for
this (no Vitest/Playwright exists anywhere in this repo yet) -- these
three tests exercise the same real routers/scheduler/DB code path a
browser-driven test would, minus the actual pixels rendering, which was
instead verified by hand with a live browser against a live-running
backend (see root README.md's "Manual end-to-end verification" section).

Two requirements this file is responsible for:

1. `/risk-map` returns valid GeoJSON with `disclaimer` present on the
   collection and every feature -- test_disclaimer.py already checks
   `disclaimer` is present and non-empty; this file adds the GeoJSON
   *structural* checks (FeatureCollection/Feature/Point shape, coordinate
   order and plausible range) that file does not cover.
2. `detect()`'s and `risk_level()`'s fields stay structurally separate
   all the way through satellite (mocked at the bridge boundary, same
   convention as test_gee_auth_503.py/test_scheduler.py) -> detection ->
   scheduler -> DB cache -> `/risk-map`/`/summary`, and satellite ->
   detection -> `/detect` -- this is new: no existing test asserts the
   *non-merger* itself (only that both sets of fields exist).
"""

from __future__ import annotations

from sqlalchemy import delete, select

from src import _detection as bridge
from src import scheduler as scheduler_module
from src.db import SessionLocal
from src.db_models import DetectionCache, MonitoredSite
from src.routers import detect as detect_router
from src.scheduler import refresh_one_site

# Fields that would indicate detect()'s (high-confidence) and
# risk_level()'s (rule-based, indicative) outputs had been merged into a
# single opaque number -- must never appear anywhere in this codebase's
# response schema.
_FORBIDDEN_MERGED_FIELD_NAMES = {
    "score",
    "risk_score",
    "combined_score",
    "combined_confidence",
    "overall_score",
    "bloom_score",
}


# ---------------------------------------------------------------------------
# 1. /risk-map -- valid GeoJSON structure + disclaimer
# ---------------------------------------------------------------------------


def test_risk_map_is_structurally_valid_geojson_with_disclaimer(client):
    resp = client.get("/risk-map")
    assert resp.status_code == 200
    body = resp.json()

    assert body["type"] == "FeatureCollection"
    assert isinstance(body["disclaimer"], str) and len(body["disclaimer"]) > 0
    assert isinstance(body["features"], list) and len(body["features"]) > 0

    # Upper Gulf of Thailand study area (CLAUDE.md §0/§4) -- loose bbox,
    # just enough to catch a swapped lat/lng or a garbage coordinate.
    LAT_RANGE = (9.0, 14.5)
    LNG_RANGE = (99.0, 102.0)

    for feature in body["features"]:
        assert feature["type"] == "Feature"

        geometry = feature["geometry"]
        assert geometry["type"] == "Point"
        coords = geometry["coordinates"]
        assert isinstance(coords, list) and len(coords) == 2
        lng, lat = coords  # GeoJSON order is [lng, lat], not [lat, lng]
        assert LNG_RANGE[0] <= lng <= LNG_RANGE[1], f"lng {lng} outside upper Gulf bbox"
        assert LAT_RANGE[0] <= lat <= LAT_RANGE[1], f"lat {lat} outside upper Gulf bbox"

        props = feature["properties"]
        assert isinstance(props["disclaimer"], str) and len(props["disclaimer"]) > 0
        assert props["risk_level"] in (None, "normal", "elevated", "watch", "warning")
        assert isinstance(props["triggered_rules"], list)


# ---------------------------------------------------------------------------
# 2. detect() vs risk_level() -- structural separation through the full stack
# ---------------------------------------------------------------------------

_TEST_SITE_ID = "pytest_e2e_separation_site"


def _fake_detect_result() -> dict:
    """A real-shape index-only result, with its own scene date."""
    return {
        "index_values": {"ndci": 0.09, "2bda": 1.2, "3bda": 0.18, "b2_b3_ratio": 0.87},
        "actual_date": "2024-03-13",
        "index_used": "ndci",
        "status": "ok",
        "reason": None,
    }


def _fake_risk_level_result() -> dict:
    """A distinctive, easily-traced risk_level() output -- rule-based,
    indicative, per CLAUDE.md's separation. Reuses _fake_detect_result()
    as its nested 'detection' field exactly the way the real
    detection/src/prediction.py.risk_level() does (it calls detect()
    internally and nests the result) -- this test does not re-implement
    that, it mocks the whole risk_level() call."""
    return {
        "level": None,
        "triggered_rules": [],
        "detection": _fake_detect_result(),
        "trend_14d": {"rising": True, "slope": 0.03},
        "sst": {"sst": 29.4, "sst_climatology": {"mean": 28.1, "std": 0.6}},
        "sst_anomaly": 2.17,
        "rainfall": {"recent_rainfall_mm": 41.2},
        "confidence_label": "indicative, rule-based -- not a validated forecast",
    }


def test_detect_response_never_carries_prediction_fields(client, monkeypatch):
    """satellite (mocked) -> detection (mocked bridge.detect) -> /detect.
    The response must carry only detect()'s own fields -- never
    risk_level/triggered_rules/level/confidence_label, which would mean
    the two outputs got merged somewhere in the response-building path."""
    monkeypatch.setattr(detect_router.bridge, "detect", lambda *a, **k: _fake_detect_result())
    monkeypatch.setattr(
        detect_router,
        "fetch_satellite_meta",
        lambda *a, **k: {"cloud_fraction": 0.08, "actual_date": "2024-03-14"},
    )

    resp = client.get("/detect", params={"lat": 13.2, "lng": 100.9, "date": "2024-03-15"})
    assert resp.status_code == 200
    body = resp.json()

    # Detection fields present, and traceable straight back to the mock --
    # not recomputed or altered on the way through.
    assert "anomaly_z" not in body
    assert body["spatial_anomaly_z"] is None
    assert body["detected"] is None
    assert body["index_values"] == _fake_detect_result()["index_values"]
    assert body["actual_date"] == "2024-03-13"
    assert body["elevated_z_threshold"] is None
    assert body["warning_z_threshold"] is None
    assert body["threshold_source"] is None
    assert body["status"] == "ok"

    # Prediction-layer fields must never leak into /detect's response --
    # this endpoint wraps detect() only (routers/detect.py's own
    # docstring: "Never merged with risk_level()'s rule-based prediction
    # layer").
    for forbidden_key in ("risk_level", "triggered_rules", "level", "confidence_label"):
        assert forbidden_key not in body, f"/detect leaked a prediction-layer field: {forbidden_key!r}"

    assert _FORBIDDEN_MERGED_FIELD_NAMES.isdisjoint(body.keys())


def test_risk_map_keeps_detection_and_prediction_as_separate_fields_through_scheduler(client, monkeypatch):
    """satellite (mocked) -> detection+prediction (mocked bridge.risk_level)
    -> scheduler.refresh_one_site -> DetectionCache row -> /risk-map.

    This is the closest this test suite gets to a full-stack path without
    a live GEE call: it exercises the real scheduler function and the
    real DB round-trip, not just a router calling a mock directly. Proves
    real indices and their own date survive the full path while the
    unavailable anomaly score, detection outcome and risk remain null."""
    db = SessionLocal()
    try:
        site = db.get(MonitoredSite, _TEST_SITE_ID)
        if site is None:
            site = MonitoredSite(site_id=_TEST_SITE_ID, name="pytest e2e separation site", lat=13.1, lng=100.6)
            db.add(site)
            db.commit()
            db.refresh(site)

        monkeypatch.setattr(scheduler_module.bridge, "risk_level", lambda *a, **k: _fake_risk_level_result())
        monkeypatch.setattr(
            scheduler_module,
            "fetch_satellite_meta",
            lambda *a, **k: {"cloud_fraction": 0.08, "actual_date": "2024-03-14"},
        )
        monkeypatch.setattr(scheduler_module, "_refresh_images", lambda *a, **k: {})

        refresh_one_site(db, site, "2024-03-15")
        db.commit()

        resp = client.get("/risk-map")
        assert resp.status_code == 200
        body = resp.json()

        # `next()` needs a default here. Without one it raises StopIteration
        # when the seeded site is missing, and pytest's rewriting of the
        # generator's comparison then reports the LAST site_id it happened to
        # test against -- e.g. "assert 'siracha' == 'pytest_e2e_separation_site'",
        # which reads as a real grid site behaving wrongly when the actual
        # fault is that this test's own site never reached /risk-map at all.
        # That misdirection cost real debugging time; fail with the truth
        # instead. (The intermittent cause -- the seeded row not being visible
        # to the request's session -- is a separate, still-open issue.)
        feature = next(
            (f for f in body["features"] if f["properties"]["site_id"] == _TEST_SITE_ID),
            None,
        )
        assert feature is not None, (
            f"/risk-map did not include the seeded site {_TEST_SITE_ID!r}. "
            f"Returned site_ids: {[f['properties']['site_id'] for f in body['features']]}"
        )
        props = feature["properties"]

        assert "anomaly_z" not in props
        assert props["spatial_anomaly_z"] is None
        assert props["detected"] is None
        assert props["index_values"] == _fake_detect_result()["index_values"]
        assert props["actual_date"] == "2024-03-13"
        assert props["status"] == "ok"
        assert props["index_used"] == "ndci"

        # Prediction: rule-based, indicative, traceable to the mock --
        # a *different* set of fields, never collapsed into the detection
        # ones above.
        assert props["risk_level"] is None
        assert props["triggered_rules"] == []
        assert "indicative" in props["confidence_label"]

        # No merged/opaque score field anywhere in the response shape.
        assert _FORBIDDEN_MERGED_FIELD_NAMES.isdisjoint(props.keys())

        # Also present via /summary (same cache row, different aggregation
        # -- detection-only field surfaced there, never risk_level itself).
        summary_resp = client.get("/summary")
        assert summary_resp.status_code == 200
        summary_body = summary_resp.json()
        most_recent = summary_body["most_recent_detected_signal"]
        assert most_recent is None
        assert summary_body["risk_level_counts"]["not_evaluated"] >= 1

    finally:
        db.execute(delete(DetectionCache).where(DetectionCache.site_id == _TEST_SITE_ID))
        db.execute(delete(MonitoredSite).where(MonitoredSite.site_id == _TEST_SITE_ID))
        db.commit()
        db.close()
