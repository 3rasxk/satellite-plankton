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

Three requirements this file is responsible for (root CLAUDE.md /
.claude/agents/integration-docs.md, GATE 5):

1. `/risk-map` returns valid GeoJSON with `disclaimer` present on the
   collection and every feature -- test_disclaimer.py already checks
   `disclaimer` is present and non-empty; this file adds the GeoJSON
   *structural* checks (FeatureCollection/Feature/Point shape, coordinate
   order and plausible range) that file does not cover.
2. `/validation` never emits a percentage and reports
   `calibration_status: "uncalibrated"` -- already covered by
   test_validation.py (Phase 3); this file does not duplicate that exact
   check, but adds an OpenAPI-schema-level percentage/ratio-field audit
   (a genuinely different angle: the *contract*, not just one response
   instance) so a future field addition can't reintroduce a percentage
   without a test noticing.
3. `detect()`'s and `risk_level()`'s fields stay structurally separate
   all the way through satellite (mocked at the bridge boundary, same
   convention as test_gee_auth_503.py/test_scheduler.py) -> detection ->
   scheduler -> DB cache -> `/risk-map`/`/summary`, and satellite ->
   detection -> `/detect` -- this is new: no existing test asserts the
   *non-merger* itself (only that both sets of fields exist).
"""

from __future__ import annotations

import re

from sqlalchemy import delete, select

from src import _detection as bridge
from src import scheduler as scheduler_module
from src.db import SessionLocal
from src.db_models import DetectionCache, MonitoredSite
from src.routers import detect as detect_router
from src.scheduler import refresh_one_site

_PERCENT_LIKE = re.compile(r"\d+(\.\d+)?\s*%")

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
        assert props["risk_level"] in ("normal", "elevated", "watch", "warning")
        assert isinstance(props["triggered_rules"], list)


# ---------------------------------------------------------------------------
# 2. /validation -- schema-level percentage/ratio-field audit
# ---------------------------------------------------------------------------


def test_openapi_schema_never_declares_a_percentage_or_ratio_field(client):
    """Contract-level check (distinct from test_validation.py's
    response-instance check): walks the generated OpenAPI schema itself
    -- every Pydantic model's declared field names, across the whole API,
    not just one /validation response payload -- so a percentage/ratio
    field added to *any* future schema (not only ValidationResponse) is
    caught before it ships."""
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    schema = resp.json()

    banned_fragments = ("percent", "pct", "accuracy", "success_rate", "hit_rate", "recall")
    schemas = schema.get("components", {}).get("schemas", {})
    assert schemas, "OpenAPI schema unexpectedly has no component schemas"

    offending = []
    for model_name, model_def in schemas.items():
        for field_name in model_def.get("properties", {}):
            lowered = field_name.lower()
            for fragment in banned_fragments:
                if fragment in lowered:
                    offending.append(f"{model_name}.{field_name}")

    assert not offending, f"percentage/ratio-shaped field(s) found in OpenAPI schema: {offending}"


def test_validation_response_is_uncalibrated_and_percentage_free(client, monkeypatch):
    """Live smoke check that the actual /validation payload (not just the
    schema) still holds both properties end to end, using the real
    threshold_run() output SHAPE. The fixture is deliberately all-unmatched
    (0/14) to exercise the empty-set path; that is NOT the current real
    shape, which is 7 matchable and 1 with a real satellite reading
    (th_010) as of 2026-09-05. Kept synthetic so this contract test does
    not move whenever the real data does."""
    from src.routers import validation as validation_router

    def _fake_run() -> dict:
        rows = [
            {
                "event_id": f"th_{i:03d}",
                "date_display": "2020-01-01",
                "location_name": "named place",
                "location_precision": "named_site",
                "species": "noctiluca_scintillans",
                "cell_count": {"raw": None, "lower": None, "upper": None, "representative": None},
                "matchable": False,
                "match_method": "none",
                "match_reason": "No lat/lng in events.csv.",
                "low_weight": False,
                "index_values": None,
                "z_scores": None,
                "flagged": None,
            }
            for i in range(1, 15)
        ]
        return {
            "config": {"indices": {"primary": "ndci"}},
            "rows": rows,
            "n_events": 14,
            "n_matchable": 0,
            "n_with_real_reading": 0,
            "loo_results": [],
        }

    monkeypatch.setattr(validation_router.bridge, "threshold_run", _fake_run)

    resp = client.get("/validation")
    assert resp.status_code == 200
    body = resp.json()

    assert body["calibration_status"] == "uncalibrated"
    assert body["n_events"] == 14

    def _walk(obj):
        if isinstance(obj, dict):
            for v in obj.values():
                yield from _walk(v)
        elif isinstance(obj, list):
            for v in obj:
                yield from _walk(v)
        else:
            yield obj

    for value in _walk(body):
        if isinstance(value, str):
            assert not _PERCENT_LIKE.search(value), f"percentage-shaped value: {value!r}"


# ---------------------------------------------------------------------------
# 3. detect() vs risk_level() -- structural separation through the full stack
# ---------------------------------------------------------------------------

_TEST_SITE_ID = "pytest_e2e_separation_site"


def _fake_detect_result() -> dict:
    """A distinctive, easily-traced detection() output -- high-confidence
    remote sensing, per CLAUDE.md's separation."""
    return {
        "anomaly_z": 2.75,
        "index_values": {"ndci": 0.09, "2bda": 1.2, "3bda": 0.18, "b2_b3_ratio": 0.87},
        "detected": True,
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
        "level": "warning",
        "triggered_rules": ["elevated", "watch", "warning"],
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
    assert body["anomaly_z"] == 2.75
    assert body["detected"] is True
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
    the anomaly_z (detection, high-confidence) and risk_level/
    triggered_rules (prediction, indicative) values survive that whole
    path as independent fields -- never combined into one number, and
    never derived from one another in a way the response would hide."""
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

        # Detection: high-confidence remote sensing, traceable to the mock.
        assert props["anomaly_z"] == 2.75
        assert props["detected"] is True
        assert props["status"] == "ok"
        assert props["index_used"] == "ndci"

        # Prediction: rule-based, indicative, traceable to the mock --
        # a *different* set of fields, never collapsed into the detection
        # ones above.
        assert props["risk_level"] == "warning"
        assert props["triggered_rules"] == ["elevated", "watch", "warning"]
        assert "indicative" in props["confidence_label"]

        # No merged/opaque score field anywhere in the response shape.
        assert _FORBIDDEN_MERGED_FIELD_NAMES.isdisjoint(props.keys())

        # Structural independence: the prediction's categorical level is
        # a string enum, the detection's anomaly_z is a float -- there is
        # no single field that combines them, and risk_level being
        # "warning" does not require or imply any particular anomaly_z
        # value beyond what detect() itself returned (config.yaml's rules
        # are the only thing connecting them, not the response shape).
        assert isinstance(props["risk_level"], str)
        assert isinstance(props["anomaly_z"], float)

        # Also present via /summary (same cache row, different aggregation
        # -- detection-only field surfaced there, never risk_level itself).
        summary_resp = client.get("/summary")
        assert summary_resp.status_code == 200
        summary_body = summary_resp.json()
        most_recent = summary_body["most_recent_detected_signal"]
        assert most_recent is not None
        assert most_recent["site_id"] == _TEST_SITE_ID
        assert most_recent["anomaly_z"] == 2.75
        assert "risk_level" not in most_recent
        assert "triggered_rules" not in most_recent

    finally:
        db.execute(delete(DetectionCache).where(DetectionCache.site_id == _TEST_SITE_ID))
        db.execute(delete(MonitoredSite).where(MonitoredSite.site_id == _TEST_SITE_ID))
        db.commit()
        db.close()
