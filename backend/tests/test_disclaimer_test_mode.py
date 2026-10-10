"""One disclaimer for the TEST baseline in force, on every response.

While BASELINE_MODE=test AND a TEST baseline is valid, the standard text
("Sentinel-2 anomaly detection is not computed -- no valid baseline exists")
is false, so EVERY response that carries `disclaimer` carries
DISCLAIMER_TEXT_TEST_BASELINE -- whether or not that response itself holds an
anomaly. With the mode off, or test mode with no usable artefact, every
response carries DISCLAIMER_TEXT. The single place is
``DisclaimerMixin.disclaimer``'s default factory
(``schemas.disclaimer_in_force``); routes that already hold one baseline
resolution pass the same text explicitly from it.

Offline: the TEST artefact is the synthetic Level A one
``test_site_anomaly._artefact`` builds through the real
``detection/src/baseline.py`` (no Level B, so no raster cell is ever
assessed), written under pytest's ``tmp_path``. The raster run is
``test_raster_pixel_anomaly``'s lattice-aligned synthetic run. GEE is
mocked at the bridge (``detect``, ``get_modis_chlorophyll_history``);
nothing here reaches Earth Engine or reads ``backend/data``.
"""

from __future__ import annotations

import logging

import pytest

from src import _detection as bridge
from src import baseline_store, config, schemas, scientific_status, site_anomaly
from src import main as main_module
from src.schemas import DISCLAIMER_TEXT, DISCLAIMER_TEXT_TEST_BASELINE, TimeseriesResponse
from tests import test_raster_pixel_anomaly as afx
from tests import test_site_anomaly as site_fx

# A point that is no baseline site's recorded coordinates: /detect computes
# no anomaly there in any mode.
_DETECT_POINT = {"lat": 13.2, "lng": 100.9, "date": "2024-03-15"}
_READING_CELL = afx.lattice_centre((afx.EP_ROW0 - 3, afx.EP_COL0 + 3))


def _detect_result(*_a, **_k) -> dict:
    return {
        "status": "ok",
        "index_used": "ndci",
        "index_values": {"ndci": 0.01, "2bda": 0.02, "3bda": 0.03, "b2_b3_ratio": 0.9},
        "reason": None,
        "cloud_fraction": 0.05,
        "actual_date": "2024-03-14",
    }


def _modis_history(*_a, **_k) -> list[dict]:
    return [{"date": f"2024-01-{day:02d}", "chlor_a": 1.0 + 0.1 * day} for day in range(1, 9)]


@pytest.fixture()
def baselines(client, tmp_path, monkeypatch):
    """Isolated baseline root (empty), clean caches, mode off; a rendered run;
    GEE mocked at the bridge. Runs are cleared afterwards."""
    root = tmp_path / "baselines"
    afx.isolate_baselines(root, monkeypatch, mode="off")
    monkeypatch.setattr(scientific_status, "_last_baseline_warning", None)
    monkeypatch.setattr(schemas, "_last_disclaimer_warning", None)
    monkeypatch.setattr(bridge, "detect", _detect_result)
    monkeypatch.setattr(bridge, "get_modis_chlorophyll_history", _modis_history)
    afx.clear_runs()
    afx.store_run(tmp_path, afx.endpoint_cells({(3, 3): 0.09}))
    yield root
    afx.clear_runs()
    baseline_store.clear_cell_cache()


def _write_valid(root) -> None:
    built, rows = site_fx._artefact()
    baseline_store.write_artifact(root, built, rows)


def _write_refused(root) -> None:
    built, rows = site_fx._artefact()
    built["preprocessing_signature"] = "0" * 64  # not the live pipeline's
    baseline_store.write_artifact(root, built, rows)


def _get(client, path: str, params: dict | None = None, *, status: int = 200) -> dict:
    response = client.get(path, params=params)
    assert response.status_code == status, (path, response.text)
    return response.json()


def _all_disclaimers(client) -> dict[str, str]:
    """Every endpoint's `disclaimer`, keyed by where it came from."""
    lat, lng = _READING_CELL
    pixel = _get(client, "/raster-scan/pixel", {"lat": lat, "lng": lng})
    outside = _get(client, "/raster-scan/pixel", {"lat": 10.0, "lng": 99.0})
    ndci = _get(client, "/raster-scan/highlights", {"mode": "ndci"})
    default = _get(client, "/raster-scan/highlights")
    # No Level B in any artefact here: no cell is ever assessed.
    assert pixel["state"] == "reading" and pixel["anomaly"] is None
    assert outside["anomaly"] is None
    assert ndci["mode"] == default["mode"] == "ndci"
    risk_map = _get(client, "/risk-map")
    assert risk_map["features"]
    found = {
        "/raster-scan": _get(client, "/raster-scan")["disclaimer"],
        "/raster-scan/pixel reading": pixel["disclaimer"],
        "/raster-scan/pixel outside": outside["disclaimer"],
        "/raster-scan/highlights?mode=ndci": ndci["disclaimer"],
        "/raster-scan/highlights (default)": default["disclaimer"],
        "/timeseries": _get(client, "/timeseries", {"lat": 13.2, "lng": 100.9})["disclaimer"],
        "/summary": _get(client, "/summary")["disclaimer"],
        "/risk-map": risk_map["disclaimer"],
        "/methods": _get(client, "/methods")["disclaimer"],
        "/detect": _get(client, "/detect", _DETECT_POINT)["disclaimer"],
        "/regional-scan (410)": _get(client, "/regional-scan", status=410)["disclaimer"],
    }
    for feature in risk_map["features"]:
        found[f"/risk-map feature {feature['properties']['site_id']}"] = feature["properties"]["disclaimer"]
    return found


def _assert_everywhere(found: dict[str, str], expected: str) -> None:
    wrong = {where: text for where, text in found.items() if text != expected}
    assert not wrong, f"{len(wrong)} response(s) carry the other text: {sorted(wrong)}"


# --------------------------------------------------------------------------
# The matrix
# --------------------------------------------------------------------------


def test_valid_test_baseline_gives_the_test_text_on_every_response(client, baselines, monkeypatch):
    _write_valid(baselines)
    monkeypatch.setattr(config, "BASELINE_MODE", "test")
    assert scientific_status.baseline_status()["valid"] is True

    _assert_everywhere(_all_disclaimers(client), DISCLAIMER_TEXT_TEST_BASELINE)


def test_mode_off_gives_the_standard_text_everywhere_even_with_a_valid_artefact(
        client, baselines, monkeypatch):
    _write_valid(baselines)
    monkeypatch.setattr(config, "BASELINE_MODE", "off")

    _assert_everywhere(_all_disclaimers(client), DISCLAIMER_TEXT)


@pytest.mark.parametrize("artefact", ["none", "refused"])
def test_test_mode_without_a_usable_artefact_gives_the_standard_text(
        client, baselines, monkeypatch, artefact):
    if artefact == "refused":
        _write_refused(baselines)
    monkeypatch.setattr(config, "BASELINE_MODE", "test")
    status = scientific_status.baseline_status()
    assert status["mode"] == "test" and status["valid"] is False

    _assert_everywhere(_all_disclaimers(client), DISCLAIMER_TEXT)


def test_the_text_follows_the_baseline_from_one_request_to_the_next(client, baselines, monkeypatch):
    """Resolved per model, never frozen at import or at the first request."""
    monkeypatch.setattr(config, "BASELINE_MODE", "test")
    assert _get(client, "/raster-scan")["disclaimer"] == DISCLAIMER_TEXT  # no artefact yet
    _write_valid(baselines)
    assert _get(client, "/raster-scan")["disclaimer"] == DISCLAIMER_TEXT_TEST_BASELINE
    monkeypatch.setattr(config, "BASELINE_MODE", "off")
    assert _get(client, "/raster-scan")["disclaimer"] == DISCLAIMER_TEXT


# --------------------------------------------------------------------------
# The factory: explicit wins, never raises, cost
# --------------------------------------------------------------------------


def test_an_explicit_disclaimer_wins_and_skips_the_factory(baselines, monkeypatch):
    _write_valid(baselines)
    monkeypatch.setattr(config, "BASELINE_MODE", "test")
    assert TimeseriesResponse(lat=0.0, lng=0.0, points=[]).disclaimer == DISCLAIMER_TEXT_TEST_BASELINE

    monkeypatch.setattr(scientific_status, "baseline_status",
                        lambda: pytest.fail("factory ran for an explicit disclaimer"))
    explicit = TimeseriesResponse(lat=0.0, lng=0.0, points=[], disclaimer=DISCLAIMER_TEXT)
    assert explicit.disclaimer == DISCLAIMER_TEXT


@pytest.mark.parametrize(
    "module,name",
    [
        (scientific_status, "baseline_status"),  # the never-raising view itself broken
        (baseline_store, "active_manifest"),     # the loader behind it
        (site_anomaly, "disclaimer_for"),
    ],
)
def test_the_factory_never_raises_and_falls_back_to_the_standard_text(
        client, baselines, monkeypatch, module, name):
    _write_valid(baselines)
    monkeypatch.setattr(config, "BASELINE_MODE", "test")

    def _boom(*_a, **_k):
        raise RuntimeError("forced for test")

    monkeypatch.setattr(module, name, _boom)

    assert schemas.disclaimer_in_force() == DISCLAIMER_TEXT
    assert TimeseriesResponse(lat=0.0, lng=0.0, points=[]).disclaimer == DISCLAIMER_TEXT
    assert _get(client, "/raster-scan")["disclaimer"] == DISCLAIMER_TEXT
    assert _get(client, "/timeseries", {"lat": 13.2, "lng": 100.9})["disclaimer"] == DISCLAIMER_TEXT


def test_a_factory_failure_is_logged_once_not_per_response(baselines, monkeypatch, caplog):
    monkeypatch.setattr(config, "BASELINE_MODE", "test")

    def _boom():
        raise RuntimeError("forced for test")

    monkeypatch.setattr(scientific_status, "baseline_status", _boom)
    with caplog.at_level(logging.WARNING, logger=schemas.logger.name):
        for _ in range(3):
            assert schemas.disclaimer_in_force() == DISCLAIMER_TEXT
    assert len([r for r in caplog.records if r.name == schemas.logger.name]) == 1


def _count(monkeypatch, module, name) -> list:
    calls: list = []
    real = getattr(module, name)
    monkeypatch.setattr(module, name, lambda *a, **k: calls.append(1) or real(*a, **k))
    return calls


# Routes that leave the disclaimer to DisclaimerMixin's default factory.
_FACTORY_BACKED = [
    ("/raster-scan", None),
    ("/timeseries", {"lat": 13.2, "lng": 100.9}),
]
# Routes that resolve the baseline themselves and pass the text explicitly.
_EXPLICIT = [
    ("/raster-scan/highlights", {"mode": "ndci"}),
    ("/raster-scan/pixel", {"lat": _READING_CELL[0], "lng": _READING_CELL[1]}),
]


@pytest.mark.parametrize("path,params", _FACTORY_BACKED + _EXPLICIT)
def test_mode_off_costs_no_file_work(client, baselines, monkeypatch, path, params):
    _write_valid(baselines)
    lookups = _count(monkeypatch, baseline_store, "latest_artifact_path")
    reads = _count(monkeypatch, baseline_store, "read_artifact")
    assert _get(client, path, params)["disclaimer"] == DISCLAIMER_TEXT
    assert lookups == [] and reads == []


@pytest.mark.parametrize("path,params", _FACTORY_BACKED + _EXPLICIT)
def test_test_mode_costs_one_resolution_per_response(client, baselines, monkeypatch, path, params):
    _write_valid(baselines)
    monkeypatch.setattr(config, "BASELINE_MODE", "test")
    scientific_status.baseline_status()  # warm the stat-keyed parse cache
    resolutions = _count(monkeypatch, scientific_status, "baseline_status")
    reads = _count(monkeypatch, baseline_store, "read_artifact")
    assert _get(client, path, params)["disclaimer"] == DISCLAIMER_TEXT_TEST_BASELINE
    assert len(resolutions) == 1
    assert reads == [], "unchanged files are never parsed again"


@pytest.mark.parametrize("path,params", _FACTORY_BACKED)
def test_a_factory_backed_response_does_one_artefact_lookup(client, baselines, monkeypatch,
                                                            path, params):
    _write_valid(baselines)
    monkeypatch.setattr(config, "BASELINE_MODE", "test")
    scientific_status.baseline_status()
    lookups = _count(monkeypatch, baseline_store, "latest_artifact_path")
    assert _get(client, path, params)["disclaimer"] == DISCLAIMER_TEXT_TEST_BASELINE
    assert len(lookups) == 1


# --------------------------------------------------------------------------
# OpenAPI
# --------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["off", "test"])
def test_openapi_still_builds_and_documents_both_texts(client, baselines, monkeypatch, mode):
    _write_valid(baselines)
    monkeypatch.setattr(config, "BASELINE_MODE", mode)
    # FastAPI caches the schema after the first build; force a fresh one.
    monkeypatch.setattr(main_module.app, "openapi_schema", None)

    components = _get(client, "/openapi.json")["components"]["schemas"]

    carrying = {name: s for name, s in components.items() if "disclaimer" in s.get("properties", {})}
    assert {"DetectResponse", "RiskMapProperties", "RiskMapResponse", "TimeseriesResponse",
            "SummaryResponse", "RasterScanResponse", "RasterPixelResponse",
            "RasterHighlightsResponse", "RasterAnomalyHighlightsResponse",
            "MethodsResponse"} <= set(carrying)
    for name, schema in carrying.items():
        prop = schema["properties"]["disclaimer"]
        assert prop["type"] == "string", name
        assert prop["examples"] == [DISCLAIMER_TEXT, DISCLAIMER_TEXT_TEST_BASELINE], name
        assert "default" not in prop, f"{name}: the text depends on the baseline in force"
        assert "TEST-baseline variant" in prop["description"], name
        assert "disclaimer" not in schema.get("required", []), name
