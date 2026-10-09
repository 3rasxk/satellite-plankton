"""Per-site TEST-baseline signal anomaly through the scheduler, /risk-map,
/summary and /detect.

Offline: the baseline artefact is synthetic, written under pytest's
``tmp_path`` with ``baseline_store.BASELINE_ROOT`` pointed there, and its
manifest is built by the real ``detection/src/baseline.py`` through the
bridge (as ``test_baseline_gate.py`` does). Detection is mocked at the typed
boundary (``bridge.risk_level`` for the scheduler, ``bridge.detect`` for
/detect); nothing here reaches GEE or reads ``backend/data/baselines``.

What is pinned:
  * mode off: no anomaly is stored or shown, ``baseline`` is null, and the
    pre-existing fields keep their values;
  * test mode: the scheduler stores exactly what ``assess_site`` returns,
    tagged with the baseline version, and a reason whenever it cannot assess;
  * a cached level is shown only when its row's ``baseline_version`` is the
    version of the baseline in force for that same response;
  * ``spatial_anomaly_z`` stays null whatever an old row holds, and the risk
    fields never open from a TEST baseline;
  * one baseline resolution per request and per grid refresh.
"""

from __future__ import annotations

import json
from datetime import date
from functools import lru_cache

import pytest
from sqlalchemy import create_engine, delete, inspect, select, text

from src import _detection as bridge
from src import baseline_store, config, db, scientific_status
from src import scheduler as scheduler_module
from src.db import SessionLocal
from src.db_models import DetectionCache, MonitoredSite
from src.routers import detect as detect_router
from src.schemas import DISCLAIMER_TEXT, DISCLAIMER_TEXT_TEST_BASELINE, BaselineInfo
from src.services.cache_service import clear_cache

logic = bridge.baseline_logic

# Sites in the artefact. "moved" is recorded at different coordinates from
# where its MonitoredSite now is; "absent" is a site the artefact lacks.
_SITE_A = {"site_id": "pytest_anomaly_a", "name": "pytest anomaly A", "lat": 13.111, "lng": 100.711}
_SITE_MOVED = {"site_id": "pytest_anomaly_moved", "name": "pytest anomaly moved", "lat": 13.122, "lng": 100.722}
_SITE_ABSENT = {"site_id": "pytest_anomaly_absent", "name": "pytest anomaly absent", "lat": 13.133, "lng": 100.733}
_MOVED_RECORDED_AT = {"lat": 13.5, "lng": 100.5}
_SITES = (_SITE_A, _SITE_MOVED, _SITE_ABSENT)

_TARGET = "2026-03-15"
_ACTUAL = "2026-03-12"
_HIGH_NDCI = 0.30  # history spans 0.020 .. 0.044
_BUILT_ON = date(2026, 1, 15)

_STATUS_KEYS = {
    "mode", "valid", "kind", "version", "built_at", "history_start", "history_end",
    "season_rule", "min_independent_dates", "median_independent_dates",
    "min_season_dates_by_location", "preprocessing_signature", "base_rates",
}
_ASSESS_KEYS = {"level", "robust_z", "median_ndci", "mad", "independent_date_count", "reason"}

# Every /risk-map feature property that existed before this task.
_PRE_EXISTING_PROPERTY_KEYS = {
    "disclaimer", "site_id", "name", "site_type", "risk_level", "triggered_rules",
    "confidence_label", "status", "detected", "spatial_anomaly_z", "signal_anomaly_level",
    "index_used", "index_values", "cloud_fraction", "actual_date", "true_color_image_url",
    "ndci_heatmap_image_url", "fetched_at", "stale", "error",
}


# --------------------------------------------------------------------------
# Synthetic artefact
# --------------------------------------------------------------------------


def _history(site_id: str) -> list[dict]:
    """Two clear-sky dates a month, 2014..2025; NDCI 0.020 .. 0.044."""
    offset = sum(map(ord, site_id))
    return [
        {
            "acquisition_date": f"{year}-{month:02d}-{day:02d}",
            "ndci": 0.02 + 0.002 * ((year * 12 + month + day + offset) % 13),
        }
        for year in range(2014, 2026)
        for month in range(1, 13)
        for day in (5, 20)
    ]


def _signature() -> str:
    return logic.preprocessing_signature(bridge.preprocessing_params())


@lru_cache(maxsize=None)
def _self_check_total(signature: str) -> str:
    total = {"assessed": 0, "watch": 0, "high": 0, "no_assessment": 0, "reasons": {}}
    for site in (_SITE_A, _SITE_MOVED):
        part = logic.self_check(
            _history(site["site_id"]), location_id=site["site_id"], preprocessing_signature=signature,
        )["total"]
        for key in ("assessed", "watch", "high", "no_assessment"):
            total[key] += part[key]
        for reason, n in part["reasons"].items():
            total["reasons"][reason] = total["reasons"].get(reason, 0) + n
    return json.dumps(total)


def _artefact(without_coordinates: tuple[str, ...] = ()) -> tuple[dict, dict[str, list[dict]]]:
    signature = _signature()
    recorded_at = {_SITE_A["site_id"]: _SITE_A, _SITE_MOVED["site_id"]: _MOVED_RECORDED_AT}
    rows = {site_id: _history(site_id) for site_id in recorded_at}
    locations = {
        site_id: {
            "n_dates": len(site_rows),
            # 12 years x 3 months x 2 dates in every seasonal window.
            "min_season_dates": 72,
            "first": site_rows[0]["acquisition_date"],
            "last": site_rows[-1]["acquisition_date"],
            "lat": recorded_at[site_id]["lat"],
            "lng": recorded_at[site_id]["lng"],
        }
        for site_id, site_rows in rows.items()
    }
    for site_id in without_coordinates:
        del locations[site_id]["lat"], locations[site_id]["lng"]
    manifest = logic.build_manifest(
        baseline_version=logic.version_for(_BUILT_ON, signature),
        built_at="2026-01-15T03:00:00+00:00",
        history_start="2014-01-05",
        history_end="2025-12-20",
        preprocessing_signature=signature,
        preprocessing_params=bridge.preprocessing_params(),
        locations=locations,
        self_check={"by_season": {}, "total": json.loads(_self_check_total(signature))},
        builder_git_sha=None,
    )
    return manifest, rows


def _expected(site_id: str, ndci: float, actual_date: str = _ACTUAL) -> dict:
    """What detection's own assess_site says -- the values must pass through unchanged."""
    return logic.assess_site(
        _history(site_id),
        location_id=site_id,
        current_ndci=ndci,
        actual_date=actual_date,
        target_date=_TARGET,
        preprocessing_signature=_signature(),
    )


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    root = tmp_path / "baselines"
    monkeypatch.setattr(baseline_store, "BASELINE_ROOT", root)
    monkeypatch.setattr(baseline_store, "_artifact_cache", None)
    monkeypatch.setattr(scientific_status, "_last_baseline_warning", None)
    monkeypatch.setattr(config, "BASELINE_MODE", "off")
    return root


@pytest.fixture()
def manifest(_isolated) -> dict:
    """A valid artefact on disk (mode still off unless a test sets it)."""
    built, rows = _artefact()
    baseline_store.write_artifact(_isolated, built, rows)
    return built


@pytest.fixture()
def test_mode(monkeypatch):
    monkeypatch.setattr(config, "BASELINE_MODE", "test")


@pytest.fixture()
def session(client):
    """The three test sites in the shared test DB; their rows removed afterwards."""
    ids = [site["site_id"] for site in _SITES]
    s = SessionLocal()
    try:
        for site in _SITES:
            if s.get(MonitoredSite, site["site_id"]) is None:
                s.add(MonitoredSite(**site))
        s.commit()
        yield s
    finally:
        s.rollback()
        s.execute(delete(DetectionCache).where(DetectionCache.site_id.in_(ids)))
        s.execute(delete(MonitoredSite).where(MonitoredSite.site_id.in_(ids)))
        s.commit()
        s.close()
        clear_cache()


def _prediction(status: str = "ok", ndci: float | None = _HIGH_NDCI, actual_date: str | None = _ACTUAL) -> dict:
    ok = status == "ok"
    return {
        "level": None,
        "signal_anomaly_level": None,
        "triggered_rules": [],
        "confidence_label": "indicative, rule-based -- not a validated forecast",
        "sst_anomaly": None,
        "trend_14d": {"rising": None},
        "rainfall": None,
        "detection": {
            "status": status,
            "index_used": "ndci",
            "index_values": {"ndci": ndci, "2bda": 1.0, "3bda": 0.1, "b2_b3_ratio": 0.9} if ok else None,
            "reason": None if ok else "no cloud-free scene in the search window",
            "cloud_fraction": 0.05 if ok else None,
            "actual_date": actual_date if ok else None,
        },
    }


def _refresh(s, monkeypatch, site: dict, prediction: dict) -> DetectionCache:
    monkeypatch.setattr(scheduler_module.bridge, "risk_level", lambda *_a, **_k: prediction)
    monkeypatch.setattr(scheduler_module, "_refresh_images", lambda *_a, **_k: {})
    scheduler_module.refresh_one_site(s, s.get(MonitoredSite, site["site_id"]), _TARGET)
    s.expire_all()
    return s.execute(
        select(DetectionCache).where(DetectionCache.site_id == site["site_id"])
    ).scalar_one()


def _seed(s, site: dict, **fields) -> None:
    base = dict(
        target_date=_TARGET, status="ok", detected=None, spatial_anomaly_z=None,
        index_used="ndci", index_values={"ndci": _HIGH_NDCI}, level=None, triggered_rules=[],
        confidence_label="indicative", actual_date=_ACTUAL, stale=False,
    )
    base.update(fields)
    s.add(DetectionCache(site_id=site["site_id"], **base))
    s.commit()
    clear_cache()


def _risk_map(client) -> dict:
    response = client.get("/risk-map")
    assert response.status_code == 200
    return response.json()


def _props(body: dict, site: dict) -> dict:
    feature = next(
        (f for f in body["features"] if f["properties"]["site_id"] == site["site_id"]), None,
    )
    assert feature is not None, f"{site['site_id']} missing from /risk-map"
    return feature["properties"]


def _stored(row: DetectionCache) -> tuple:
    return (row.signal_anomaly_level, row.signal_robust_z, row.signal_anomaly_reason, row.baseline_version)


# --------------------------------------------------------------------------
# (a) Mode off: nothing stored, nothing shown, existing fields unchanged
# --------------------------------------------------------------------------


def test_mode_off_stores_and_shows_no_anomaly_even_with_a_valid_artefact(client, session, manifest, monkeypatch):
    row = _refresh(session, monkeypatch, _SITE_A, _prediction(ndci=_HIGH_NDCI))
    assert _stored(row) == (None, None, None, None)

    body = _risk_map(client)
    assert body["baseline"] is None
    props = _props(body, _SITE_A)
    assert set(props) == _PRE_EXISTING_PROPERTY_KEYS | {"signal_robust_z", "signal_anomaly_reason"}
    assert props["signal_anomaly_level"] is None
    assert props["signal_robust_z"] is None
    assert props["signal_anomaly_reason"] is None
    # The pre-existing fields carry exactly what they carried before.
    assert props["risk_level"] is None
    assert props["triggered_rules"] == []
    assert props["detected"] is None
    assert props["spatial_anomaly_z"] is None
    assert props["status"] == "ok"
    assert props["index_values"] == _prediction()["detection"]["index_values"]
    assert props["actual_date"] == _ACTUAL
    assert props["cloud_fraction"] == 0.05


def test_mode_off_hides_a_row_assessed_under_a_baseline(client, session, manifest):
    _seed(session, _SITE_A, signal_anomaly_level="high", signal_robust_z=9.0,
          signal_anomaly_reason=None, baseline_version=manifest["baseline_version"])
    props = _props(_risk_map(client), _SITE_A)
    assert (props["signal_anomaly_level"], props["signal_robust_z"], props["signal_anomaly_reason"]) == (None, None, None)


def test_mode_off_summary_and_detect_carry_no_baseline(client, manifest, monkeypatch):
    summary = client.get("/summary").json()
    assert summary["baseline"] is None

    monkeypatch.setattr(detect_router.bridge, "detect", lambda *_a, **_k: _prediction()["detection"])
    body = client.get("/detect", params={"lat": _SITE_A["lat"], "lng": _SITE_A["lng"], "date": _TARGET}).json()
    assert body["signal_anomaly"] is None
    assert body["baseline"] is None
    assert body["signal_anomaly_level"] is None
    assert body["spatial_anomaly_z"] is None


# --------------------------------------------------------------------------
# (b)-(d) Test mode, valid artefact: scheduler -> DetectionCache -> /risk-map
# --------------------------------------------------------------------------


def test_far_above_history_is_high_and_stored_as_assess_site_returns_it(client, session, manifest, test_mode, monkeypatch):
    row = _refresh(session, monkeypatch, _SITE_A, _prediction(ndci=_HIGH_NDCI))
    expected = _expected(_SITE_A["site_id"], _HIGH_NDCI)
    assert expected["level"] == "high"
    assert _stored(row) == ("high", expected["robust_z"], None, manifest["baseline_version"])
    assert row.signal_robust_z >= 3
    # Neither the risk layer nor the withdrawn spatial statistic is filled.
    assert row.level is None
    assert row.spatial_anomaly_z is None

    body = _risk_map(client)
    props = _props(body, _SITE_A)
    assert props["signal_anomaly_level"] == "high"
    assert props["signal_robust_z"] == pytest.approx(expected["robust_z"])
    assert props["signal_robust_z"] >= 3
    assert props["signal_anomaly_reason"] is None
    assert props["risk_level"] is None
    assert props["spatial_anomaly_z"] is None

    baseline = body["baseline"]
    assert baseline["kind"] == "test"
    assert baseline["valid"] is True
    assert baseline["version"] == manifest["baseline_version"]
    assert baseline["min_season_dates_by_location"] == {_SITE_A["site_id"]: 72, _SITE_MOVED["site_id"]: 72}
    assert _STATUS_KEYS <= set(baseline)
    assert {key: baseline[key] for key in _STATUS_KEYS} == scientific_status.baseline_status()


def test_inside_the_history_range_is_normal(client, session, manifest, test_mode, monkeypatch):
    expected = _expected(_SITE_A["site_id"], 0.032)
    assert expected["level"] == "normal"
    row = _refresh(session, monkeypatch, _SITE_A, _prediction(ndci=0.032))
    assert _stored(row) == ("normal", expected["robust_z"], None, manifest["baseline_version"])
    assert _props(_risk_map(client), _SITE_A)["signal_anomaly_level"] == "normal"


@pytest.mark.parametrize("status", ["no_imagery", "no_water_pixels"])
def test_no_usable_reading_stores_no_level_with_the_detection_status_as_reason(
    client, session, manifest, test_mode, monkeypatch, status,
):
    row = _refresh(session, monkeypatch, _SITE_A, _prediction(status=status))
    assert _stored(row) == (None, None, status, manifest["baseline_version"])

    props = _props(_risk_map(client), _SITE_A)
    assert props["signal_anomaly_level"] is None
    assert props["signal_robust_z"] is None
    assert props["signal_anomaly_reason"] == status


def test_an_ok_reading_without_ndci_is_not_assessed(client, session, manifest, test_mode, monkeypatch):
    row = _refresh(session, monkeypatch, _SITE_A, _prediction(ndci=None))
    assert _stored(row) == (None, None, "missing_or_invalid_observation", manifest["baseline_version"])


def test_assessment_reasons_pass_through_unchanged(client, session, manifest, test_mode, monkeypatch):
    """Imagery 23 days older than the target: assess_site's own reason, stored as is."""
    expected = _expected(_SITE_A["site_id"], _HIGH_NDCI, actual_date="2026-02-20")
    assert expected["reason"] == "imagery_older_than_14_days"
    row = _refresh(session, monkeypatch, _SITE_A, _prediction(actual_date="2026-02-20"))
    assert _stored(row) == (None, None, "imagery_older_than_14_days", manifest["baseline_version"])


def test_a_site_the_artefact_lacks_is_not_assessed(client, session, manifest, test_mode, monkeypatch):
    row = _refresh(session, monkeypatch, _SITE_ABSENT, _prediction())
    assert _stored(row) == (None, None, "site_not_in_baseline", manifest["baseline_version"])
    assert _props(_risk_map(client), _SITE_ABSENT)["signal_anomaly_reason"] == "site_not_in_baseline"


def test_a_site_whose_coordinates_moved_since_the_build_is_not_assessed(client, session, manifest, test_mode, monkeypatch):
    """Same site_id, different place: its history describes other water."""
    row = _refresh(session, monkeypatch, _SITE_MOVED, _prediction())
    assert _stored(row) == (None, None, "site_coordinates_differ_from_baseline", manifest["baseline_version"])


def test_a_baseline_site_without_recorded_coordinates_fails_closed(client, session, test_mode, monkeypatch, _isolated):
    """Scheduler and /detect agree: no recorded place, no assessment."""
    built, rows = _artefact(without_coordinates=(_SITE_A["site_id"],))
    baseline_store.write_artifact(_isolated, built, rows)

    row = _refresh(session, monkeypatch, _SITE_A, _prediction())
    assert _stored(row) == (None, None, "baseline_site_coordinates_missing", built["baseline_version"])

    body = _detect(client, monkeypatch, _prediction()["detection"], _SITE_A["lat"], _SITE_A["lng"])
    assert body["baseline"]["valid"] is True
    assert body["signal_anomaly"]["level"] is None
    assert body["signal_anomaly"]["reason"] == "site_not_in_baseline"


def test_an_assessment_error_keeps_the_fresh_reading(client, session, manifest, test_mode, monkeypatch):
    def boom(*_a, **_k):
        raise ValueError("signal_anomaly configuration is incomplete or invalid")

    monkeypatch.setattr(bridge.baseline_logic, "assess_site", boom)
    row = _refresh(session, monkeypatch, _SITE_A, _prediction())
    assert row.stale is False and row.error is None
    assert row.index_values["ndci"] == _HIGH_NDCI
    assert _stored(row) == (None, None, "assessment_failed", manifest["baseline_version"])


# --------------------------------------------------------------------------
# (e) Test mode, invalid artefact
# --------------------------------------------------------------------------


def test_invalid_artefact_stores_the_refusal_and_shows_no_level(client, session, test_mode, monkeypatch, _isolated):
    _isolated.mkdir()
    row = _refresh(session, monkeypatch, _SITE_A, _prediction())
    assert _stored(row) == (None, None, "baseline_invalid:no_artifact", None)

    body = _risk_map(client)
    assert body["baseline"] == {
        **{key: None for key in BaselineInfo.model_fields},
        "mode": "test", "valid": False, "kind": "test", "reason": "no_artifact",
    }
    props = _props(body, _SITE_A)
    assert props["signal_anomaly_level"] is None
    assert props["signal_robust_z"] is None
    assert props["signal_anomaly_reason"] == "baseline_invalid:no_artifact"


def test_a_level_cached_under_a_now_broken_artefact_is_withdrawn(client, session, manifest, test_mode, monkeypatch, _isolated):
    _refresh(session, monkeypatch, _SITE_A, _prediction(ndci=_HIGH_NDCI))
    assert _props(_risk_map(client), _SITE_A)["signal_anomaly_level"] == "high"

    (_isolated / manifest["baseline_version"] / baseline_store.MANIFEST_NAME).write_text("{ nope", encoding="utf-8")
    body = _risk_map(client)
    assert body["baseline"]["valid"] is False
    assert body["baseline"]["reason"] == "unreadable"
    props = _props(body, _SITE_A)
    assert props["signal_anomaly_level"] is None
    assert props["signal_robust_z"] is None
    assert props["signal_anomaly_reason"] == "baseline_invalid:unreadable"


# --------------------------------------------------------------------------
# Version pairing and the withdrawn spatial statistic
# --------------------------------------------------------------------------


def test_a_row_from_another_baseline_version_is_not_shown(client, session, manifest, test_mode):
    _seed(session, _SITE_A, signal_anomaly_level="high", signal_robust_z=9.0,
          signal_anomaly_reason=None, baseline_version="TEST-20250101-0ld0ld0l")
    props = _props(_risk_map(client), _SITE_A)
    assert props["signal_anomaly_level"] is None
    assert props["signal_robust_z"] is None
    assert props["signal_anomaly_reason"] == "not_assessed_against_active_baseline"


def test_a_row_never_assessed_is_not_shown_as_assessed(client, session, manifest, test_mode):
    _seed(session, _SITE_A, signal_anomaly_level="high", signal_robust_z=9.0)
    props = _props(_risk_map(client), _SITE_A)
    assert props["signal_anomaly_level"] is None
    assert props["signal_anomaly_reason"] == "not_assessed_against_active_baseline"


def test_spatial_anomaly_z_stays_null_in_test_mode_whatever_the_row_holds(client, session, manifest, test_mode):
    _seed(session, _SITE_A, spatial_anomaly_z=9.0, detected=True, level="warning",
          signal_anomaly_level="high", signal_robust_z=4.2, baseline_version=manifest["baseline_version"])
    props = _props(_risk_map(client), _SITE_A)
    assert props["signal_anomaly_level"] == "high"  # the paired row IS shown ...
    assert props["signal_robust_z"] == 4.2
    assert props["spatial_anomaly_z"] is None  # ... but never the unvalidated statistic
    assert props["risk_level"] is None
    assert props["detected"] is None
    assert props["triggered_rules"] == []


@pytest.mark.parametrize(
    "mode,with_artefact,expected",
    [
        ("test", True, "no_cached_reading_yet"),
        ("test", False, "baseline_invalid:no_artifact"),
        ("off", True, None),
    ],
)
def test_a_site_with_no_cached_reading_says_why_in_test_mode(
    client, session, monkeypatch, _isolated, mode, with_artefact, expected,
):
    if with_artefact:
        built, rows = _artefact()
        baseline_store.write_artifact(_isolated, built, rows)
    monkeypatch.setattr(config, "BASELINE_MODE", mode)
    props = _props(_risk_map(client), _SITE_ABSENT)  # no DetectionCache row
    assert props["status"] == "no_data_yet"
    assert props["signal_anomaly_level"] is None
    assert props["signal_robust_z"] is None
    assert props["signal_anomaly_reason"] == expected


# --------------------------------------------------------------------------
# Disclaimer: the TEST-baseline variant exactly while an anomaly can be computed
# --------------------------------------------------------------------------

_EXPECTED_TEST_DISCLAIMER = (
    "Satellite index values describe water colour at pixel resolution. Small or scattered "
    "blooms may not be visible. TEST baseline mode: a monitoring site's Sentinel-2 NDCI may "
    "be compared with that site's own earlier record for the same season. Any resulting "
    "anomaly is provisional and uncalibrated, has never been checked against recorded bloom "
    "events, and is a statistical statement only — not a bloom detection, a species "
    "identification, a risk level or a forecast. Index values alone establish neither bloom "
    "presence nor absence."
)


def test_test_baseline_disclaimer_text_is_the_agreed_wording():
    assert DISCLAIMER_TEXT_TEST_BASELINE == _EXPECTED_TEST_DISCLAIMER
    assert DISCLAIMER_TEXT_TEST_BASELINE != DISCLAIMER_TEXT
    assert "not computed" in DISCLAIMER_TEXT  # the mode-off text is unchanged


def _all_disclaimers(client, monkeypatch) -> dict[str, list[str]]:
    risk_map = _risk_map(client)
    monkeypatch.setattr(detect_router.bridge, "detect", lambda *_a, **_k: _prediction()["detection"])
    detect = client.get("/detect", params={"lat": _SITE_A["lat"], "lng": _SITE_A["lng"], "date": _TARGET})
    assert detect.status_code == 200
    return {
        "/risk-map": [risk_map["disclaimer"]],
        "/risk-map features": [f["properties"]["disclaimer"] for f in risk_map["features"]],
        "/summary": [client.get("/summary").json()["disclaimer"]],
        "/detect": [detect.json()["disclaimer"]],
    }


@pytest.mark.parametrize(
    "mode,with_artefact,expected",
    [
        ("test", True, DISCLAIMER_TEXT_TEST_BASELINE),
        ("test", False, DISCLAIMER_TEXT),  # test mode, refused baseline: nothing computed
        ("off", True, DISCLAIMER_TEXT),
    ],
)
def test_every_site_response_carries_the_disclaimer_for_the_baseline_in_force(
    client, session, monkeypatch, _isolated, mode, with_artefact, expected,
):
    if with_artefact:
        built, rows = _artefact()
        baseline_store.write_artifact(_isolated, built, rows)
    monkeypatch.setattr(config, "BASELINE_MODE", mode)
    # One site with a cached row, the others (incl. _SITE_ABSENT) without one.
    _seed(session, _SITE_A)

    found = _all_disclaimers(client, monkeypatch)

    assert len(found["/risk-map features"]) >= 2
    for where, texts in found.items():
        assert texts and all(text == expected for text in texts), where


# --------------------------------------------------------------------------
# (f) /summary
# --------------------------------------------------------------------------


def test_summary_carries_the_same_baseline_block(client, manifest, test_mode):
    body = client.get("/summary").json()
    assert body["baseline"]["kind"] == "test"
    assert body["baseline"]["valid"] is True
    assert body["baseline"]["version"] == manifest["baseline_version"]
    assert {key: body["baseline"][key] for key in _STATUS_KEYS} == scientific_status.baseline_status()
    assert body["risk_level_counts"]["warning"] == 0


def test_summary_reports_an_invalid_baseline(client, test_mode):
    body = client.get("/summary").json()
    assert body["baseline"]["valid"] is False
    assert body["baseline"]["reason"] == "no_artifact"


# --------------------------------------------------------------------------
# /detect (live)
# --------------------------------------------------------------------------


def _detect(client, monkeypatch, detection: dict, lat: float, lng: float) -> dict:
    monkeypatch.setattr(detect_router.bridge, "detect", lambda *_a, **_k: detection)
    response = client.get("/detect", params={"lat": lat, "lng": lng, "date": _TARGET})
    assert response.status_code == 200
    return response.json()


def test_detect_at_a_baseline_site_returns_the_assessment(client, manifest, test_mode, monkeypatch):
    body = _detect(client, monkeypatch, _prediction(ndci=_HIGH_NDCI)["detection"], _SITE_A["lat"], _SITE_A["lng"])
    expected = _expected(_SITE_A["site_id"], _HIGH_NDCI)

    anomaly = body["signal_anomaly"]
    assert set(anomaly) == _ASSESS_KEYS | {"location_id"}
    assert {key: anomaly[key] for key in _ASSESS_KEYS} == pytest.approx({key: expected[key] for key in _ASSESS_KEYS})
    assert anomaly["level"] == "high"
    assert anomaly["location_id"] == _SITE_A["site_id"]
    assert body["signal_anomaly_level"] == "high"
    assert body["spatial_anomaly_z"] is None
    assert body["baseline"]["kind"] == "test"
    assert body["baseline"]["version"] == manifest["baseline_version"]
    assert "risk" not in json.dumps(anomaly)


def test_detect_elsewhere_is_not_assessed_against_a_site_history(client, manifest, test_mode, monkeypatch):
    body = _detect(client, monkeypatch, _prediction()["detection"], _SITE_A["lat"] + 0.01, _SITE_A["lng"])
    assert body["signal_anomaly"]["level"] is None
    assert body["signal_anomaly"]["robust_z"] is None
    assert body["signal_anomaly"]["reason"] == "site_not_in_baseline"
    assert body["signal_anomaly_level"] is None
    assert body["baseline"]["valid"] is True


def test_detect_without_a_usable_scene_states_why(client, manifest, test_mode, monkeypatch):
    body = _detect(client, monkeypatch, _prediction(status="no_imagery")["detection"], _SITE_A["lat"], _SITE_A["lng"])
    assert body["signal_anomaly"]["level"] is None
    assert body["signal_anomaly"]["reason"] == "no_imagery"


def test_detect_with_an_invalid_baseline(client, test_mode, monkeypatch):
    body = _detect(client, monkeypatch, _prediction()["detection"], _SITE_A["lat"], _SITE_A["lng"])
    assert body["baseline"]["valid"] is False
    assert body["signal_anomaly"]["level"] is None
    assert body["signal_anomaly"]["reason"] == "baseline_invalid:no_artifact"
    assert body["signal_anomaly_level"] is None


# --------------------------------------------------------------------------
# One resolution per request / per grid refresh
# --------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/risk-map", "/summary", "/detect"])
def test_each_request_resolves_the_baseline_once(client, manifest, test_mode, monkeypatch, path):
    monkeypatch.setattr(detect_router.bridge, "detect", lambda *_a, **_k: _prediction()["detection"])
    lookups = []
    real = baseline_store.latest_artifact_path
    monkeypatch.setattr(baseline_store, "latest_artifact_path", lambda *a, **k: lookups.append(1) or real(*a, **k))
    params = {"lat": _SITE_A["lat"], "lng": _SITE_A["lng"], "date": _TARGET} if path == "/detect" else None
    assert client.get(path, params=params).status_code == 200
    assert len(lookups) == 1


def test_refresh_grid_takes_one_snapshot_for_every_site(client, monkeypatch):
    snapshots = []
    real = scientific_status.baseline_snapshot
    monkeypatch.setattr(scientific_status, "baseline_snapshot", lambda: snapshots.append(real()) or snapshots[-1])
    calls = []
    monkeypatch.setattr(
        scheduler_module, "refresh_one_site",
        lambda _db, site, _target, snapshot=None: calls.append((site.site_id, snapshot)),
    )
    monkeypatch.setattr(scheduler_module.shutdown, "stop_requested", lambda: False)

    scheduler_module.refresh_grid()

    assert len(snapshots) == 1
    assert len(calls) >= 7  # the monitored grid
    assert all(snapshot is snapshots[0] for _, snapshot in calls)


def test_refresh_one_site_alone_takes_exactly_one_snapshot(client, session, manifest, test_mode, monkeypatch):
    snapshots = []
    real = scientific_status.baseline_snapshot
    monkeypatch.setattr(scientific_status, "baseline_snapshot", lambda: snapshots.append(1) or real())
    _refresh(session, monkeypatch, _SITE_A, _prediction())
    assert len(snapshots) == 1


def test_a_refresh_uses_the_snapshot_it_was_given(client, session, manifest, test_mode, monkeypatch):
    """The grid's one snapshot decides, even if the disk changed since."""
    given = scientific_status.baseline_snapshot()
    monkeypatch.setattr(scientific_status, "baseline_snapshot", lambda: pytest.fail("snapshot taken again"))
    monkeypatch.setattr(scheduler_module.bridge, "risk_level", lambda *_a, **_k: _prediction())
    monkeypatch.setattr(scheduler_module, "_refresh_images", lambda *_a, **_k: {})
    site = session.get(MonitoredSite, _SITE_A["site_id"])
    scheduler_module.refresh_one_site(session, site, _TARGET, snapshot=given)
    session.expire_all()
    row = session.execute(select(DetectionCache).where(DetectionCache.site_id == _SITE_A["site_id"])).scalar_one()
    assert row.baseline_version == given[1].version


# --------------------------------------------------------------------------
# Schema
# --------------------------------------------------------------------------


def test_baseline_info_carries_every_status_key(manifest, test_mode):
    status = scientific_status.baseline_status()
    assert set(status) == _STATUS_KEYS
    assert set(BaselineInfo.model_fields) == _STATUS_KEYS | {"reason"}
    assert BaselineInfo(**status).model_dump(exclude={"reason"}) == status
    assert "min_season_dates_by_location" in BaselineInfo.model_fields
    assert not any("risk" in name for name in BaselineInfo.model_fields)


# --------------------------------------------------------------------------
# (g) Migration of an existing database
# --------------------------------------------------------------------------


def test_new_columns_reach_an_existing_detection_cache(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'older.db'}")
    monkeypatch.setattr(db, "engine", engine)
    db.init_db()

    # An older detection_cache shape, from before signal_anomaly_level and the
    # three columns of this task, with a row in it.
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE detection_cache"))
        connection.execute(text(
            "CREATE TABLE detection_cache (id INTEGER PRIMARY KEY, site_id VARCHAR, "
            "target_date VARCHAR, status VARCHAR, spatial_anomaly_z FLOAT, index_values JSON)"
        ))
        connection.execute(text(
            "INSERT INTO detection_cache (id, site_id, target_date, status, index_values) "
            "VALUES (1, 'kept-site', '2026-03-15', 'ok', '{\"ndci\": 0.2}')"
        ))

    db.init_db()

    added = {"signal_anomaly_level", "signal_robust_z", "signal_anomaly_reason", "baseline_version"}
    columns = {column["name"] for column in inspect(engine).get_columns("detection_cache")}
    assert added <= columns
    with engine.connect() as connection:
        # An addition, not a reset: the row survives with the new columns null.
        assert connection.execute(text(
            "SELECT site_id, index_values, signal_anomaly_level, signal_robust_z, "
            "signal_anomaly_reason, baseline_version FROM detection_cache"
        )).all() == [("kept-site", '{"ndci": 0.2}', None, None, None, None)]

    db.init_db()  # idempotent
    assert {column["name"] for column in inspect(engine).get_columns("detection_cache")} == columns
    engine.dispose()
