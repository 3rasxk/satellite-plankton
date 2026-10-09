"""`GET /methods` -- the Methods page's numbers, read from the code that uses them.

Offline: no GEE (every Earth Engine entry point is replaced by one that
raises), no database (SQLAlchemy session calls raise during the request),
and any TEST baseline artefact is synthetic, written under ``tmp_path`` by
the real ``detection/src/baseline.py`` (``tests/test_baseline_gate.py``'s
helper), with ``baseline_store.BASELINE_ROOT`` pointed there.

What is pinned:
  * each worked example is the registered index function's own output on the
    fixed sample bands, equal to hand arithmetic of the displayed formula;
  * metadata, roles, wavelengths and display domains are passed through from
    detection / the renderer, never restated here;
  * gates are ``scientific_status``'s answers; floors and z boundaries are the
    detection constants; scene age and the latest-scene policy are the
    effective settings, with an invalid scene threshold reported as null;
  * every reference shown is one ``LIMITATIONS.md`` already carries;
  * ``baseline`` mirrors ``baseline_status()`` in off / valid / invalid states
    and the disclaimer follows the same rule as every other response;
  * GET only; the handler is synchronous (runs off the event loop).
"""

from __future__ import annotations

import inspect
import re
import sys
import typing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ee
import pytest
from sqlalchemy.orm import Session

from src import _detection as bridge
from src import baseline_store, config, scientific_status
from src import main as main_module
from src.raster_scan import render, trigger
from src.routers import methods as methods_router
from src.schemas import DISCLAIMER_TEXT, DISCLAIMER_TEXT_TEST_BASELINE, MethodsIndex, MethodsResponse
from tests.test_baseline_gate import _artefact

logic = bridge.baseline_logic
_REPO_ROOT = Path(__file__).resolve().parents[2]
_LIMITATIONS = _REPO_ROOT / "LIMITATIONS.md"

_SAMPLE = {"B2": 800, "B3": 900, "B4": 600, "B5": 700, "B6": 650}
_INDEX_ORDER = ["ndci", "2bda", "3bda", "b2_b3_ratio"]
_RASTER_BAND = {"ndci": "ndci", "2bda": "bda2", "3bda": "bda3", "b2_b3_ratio": "b2_b3"}
_DOIS = {"10.1016/j.rse.2011.10.016", "10.3389/fmars.2023.1031901"}


# --------------------------------------------------------------------------
# Fixtures / helpers
# --------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    """Empty tmp baseline root, no cached artefact, mode off."""
    root = tmp_path / "baselines"
    monkeypatch.setattr(baseline_store, "BASELINE_ROOT", root)
    monkeypatch.setattr(baseline_store, "_artifact_cache", None)
    monkeypatch.setattr(scientific_status, "_last_baseline_warning", None)
    monkeypatch.setattr(config, "BASELINE_MODE", "off")
    return root


@pytest.fixture()
def test_mode(monkeypatch):
    monkeypatch.setattr(config, "BASELINE_MODE", "test")


@pytest.fixture()
def valid_artefact(_isolated):
    manifest, rows = _artefact()
    baseline_store.write_artifact(_isolated, manifest, rows)
    return manifest


def _get(client) -> dict:
    response = client.get("/methods")
    assert response.status_code == 200, response.text
    return response.json()


def _by_key(body: dict) -> dict:
    return {item["key"]: item for item in body["indices"]}


def _normalised(text: str) -> str:
    return " ".join(text.split())


def _references_section() -> str:
    text = _LIMITATIONS.read_text(encoding="utf-8")
    start = text.index("## Scientific references and transfer limits")
    end = text.index("\n## ", start + 1)
    return _normalised(text[start:end])


def _assert_mirrors(block: dict, status: dict) -> None:
    """Every key of ``status`` with its value; every other schema key null."""
    assert {k: v for k, v in block.items() if v is not None} == status
    assert set(status) <= set(block)


# --------------------------------------------------------------------------
# Route shape
# --------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_methods_is_get_only(client, method):
    assert getattr(client, method)("/methods").status_code == 405


def test_handler_is_synchronous_so_it_runs_off_the_event_loop():
    assert not inspect.iscoroutinefunction(methods_router.get_methods)


def test_response_validates_against_the_schema_and_round_trips(client):
    body = _get(client)
    model = MethodsResponse.model_validate(body)
    assert model.model_dump(mode="json") == body
    assert body["api_version"] == main_module.app.version


def test_root_lists_the_endpoint(client):
    assert "/methods" in client.get("/").json()["endpoints"]


def test_no_gee_and_no_database_during_the_request(client, monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("/methods must not reach Earth Engine or the database")

    for name in ("Initialize", "Authenticate", "Image", "ImageCollection", "FeatureCollection",
                 "Feature", "Geometry", "Number", "Date", "List", "Dictionary", "Reducer", "Filter"):
        monkeypatch.setattr(ee, name, refuse, raising=False)
    for name in ("computeValue", "getInfo", "getList", "getAssetRoots"):
        monkeypatch.setattr(ee.data, name, refuse, raising=False)
    for name in ("detect", "risk_level", "get_sentinel2_bands", "get_modis_chlorophyll_history",
                 "get_ndci_history", "assess_new_scenes", "build_index_composite",
                 "download_composite_arrays", "get_newest_scene_timestamp",
                 "get_true_color_image", "get_ndci_heatmap"):
        monkeypatch.setattr(bridge, name, refuse)
    for name in ("execute", "scalars", "scalar", "get", "query"):
        monkeypatch.setattr(Session, name, refuse)

    assert len(_get(client)["indices"]) == 4


# --------------------------------------------------------------------------
# Indices
# --------------------------------------------------------------------------


def test_indices_follow_the_registry_order(client):
    assert [item["key"] for item in _get(client)["indices"]] == _INDEX_ORDER == list(bridge.INDEX_FUNCTIONS)


def test_worked_examples_equal_hand_arithmetic_of_the_displayed_formulas(client):
    indices = _by_key(_get(client))
    for item in indices.values():
        assert item["worked_example"]["bands"] == _SAMPLE
    assert indices["ndci"]["worked_example"]["value"] == (700 - 600) / (700 + 600)
    assert indices["2bda"]["worked_example"]["value"] == 700 / 600
    assert indices["3bda"]["worked_example"]["value"] == (1 / 600 - 1 / 700) * 650
    assert indices["b2_b3_ratio"]["worked_example"]["value"] == 800 / 900


def test_worked_example_is_labelled_illustrative(client):
    for item in _get(client)["indices"]:
        assert "illustrative" in item["worked_example"]["note"].lower()


def test_worked_example_value_comes_from_the_registered_function_at_request_time(client, monkeypatch):
    monkeypatch.setitem(bridge.INDEX_FUNCTIONS, "3bda", lambda bands: 0.123456)
    assert _by_key(_get(client))["3bda"]["worked_example"]["value"] == 0.123456


def test_bridge_exposes_the_registry_prediction_actually_uses():
    compute_all = bridge._prediction.compute_all_indices
    assert compute_all.__globals__["INDEX_FUNCTIONS"] is bridge.INDEX_FUNCTIONS
    assert compute_all.__globals__["INDEX_METADATA"] is bridge.INDEX_METADATA


def test_index_metadata_is_passed_through_unchanged(client):
    for key, item in _by_key(_get(client)).items():
        meta = bridge.INDEX_METADATA[key]
        assert item["name"] == meta["name"]
        assert item["formula"] == meta["formula"]
        assert item["bands"] == list(meta["bands"])
        assert item["role"] == meta["role"]
        assert item["note"] == meta["note"]


def test_schema_role_vocabulary_is_detections():
    indices_module = sys.modules[bridge._prediction.compute_all_indices.__module__]
    annotation = MethodsIndex.model_fields["role"].annotation
    assert typing.get_args(annotation) == indices_module.INDEX_ROLES


def test_roles_and_the_2bda_caveat(client):
    indices = _by_key(_get(client))
    assert indices["ndci"]["role"] == "primary"
    assert indices["2bda"]["role"] == "derived"
    assert "must not be treated as an independent confirming signal" in indices["2bda"]["note"]
    assert indices["b2_b3_ratio"]["role"] == "exploratory"
    assert "species classifier" in indices["b2_b3_ratio"]["note"]


def test_wavelengths_are_only_the_documented_ones(client):
    body = _get(client)
    for key, item in _by_key(body).items():
        expected = {b: bridge.BAND_WAVELENGTHS_NM[b] for b in bridge.INDEX_METADATA[key]["bands"]
                    if b in bridge.BAND_WAVELENGTHS_NM}
        assert item["wavelengths_nm"] == expected
    assert _by_key(body)["b2_b3_ratio"]["wavelengths_nm"] == {}
    assert body["sentinel2"]["wavelengths_nm"] == bridge.BAND_WAVELENGTHS_NM
    assert "B2" not in body["sentinel2"]["wavelengths_nm"]


def test_raster_band_names_map_one_to_one_onto_the_stored_bands(client):
    indices = _by_key(_get(client))
    assert {key: item["raster_band"] for key, item in indices.items()} == _RASTER_BAND
    assert set(_RASTER_BAND.values()) == set(bridge.RASTER_INDEX_BANDS)


def test_display_domain_is_the_renderers_and_null_where_none_is_agreed(client):
    indices = _by_key(_get(client))
    low, high = render.BAND_DOMAINS["ndci"]
    assert indices["ndci"]["display_domain"] == {"min": low, "max": high}
    assert (low, high) == tuple(bridge.NDCI_RAMP_DOMAIN)
    for key in ("2bda", "3bda", "b2_b3_ratio"):
        assert indices[key]["display_domain"] is None


def test_display_domain_is_read_from_the_renderer_at_request_time(client, monkeypatch):
    monkeypatch.setitem(render.BAND_DOMAINS, "bda2", (0.5, 2.0))
    assert _by_key(_get(client))["2bda"]["display_domain"] == {"min": 0.5, "max": 2.0}


# --------------------------------------------------------------------------
# Sensors
# --------------------------------------------------------------------------


def test_sentinel2_block_is_the_live_pipeline_settings(client, monkeypatch):
    monkeypatch.delenv("SENTINEL2_MAX_SCENE_AGE_DAYS", raising=False)
    s2 = _get(client)["sentinel2"]
    params = bridge.preprocessing_params()
    assert s2["collection"] == params["collection"] == "COPERNICUS/S2_SR_HARMONIZED"
    assert s2["bands"] == params["bands"]
    assert s2["native_resolution_m"] == bridge.BAND_NATIVE_RESOLUTION_M
    assert s2["scale_factor"] == bridge.INDEX_SCALE_FACTOR == 10000
    assert s2["max_scene_age_days"] == bridge.default_max_scene_age_days()
    assert s2["max_cloud_fraction"] == params["max_cloud_fraction"]
    assert s2["cloud_mask_scl_classes"] == params["cloud_classes"]
    assert s2["min_water_occurrence_pct"] == params["min_water_occurrence_pct"]


def test_revisit_days_is_the_figure_the_index_module_states(client):
    revisit = _get(client)["sentinel2"]["revisit_days"]
    module_doc = sys.modules[bridge._prediction.compute_all_indices.__module__].__doc__
    assert f"~{revisit}-day revisit" in module_doc


def test_max_scene_age_is_the_effective_value_at_request_time(client, monkeypatch):
    monkeypatch.setenv("SENTINEL2_MAX_SCENE_AGE_DAYS", "9")
    assert _get(client)["sentinel2"]["max_scene_age_days"] == 9 == bridge.default_max_scene_age_days()


def test_modis_block_is_the_data_pipeline_constants(client):
    modis_module = sys.modules["data_pipeline_src"].modis
    modis = _get(client)["modis"]
    assert modis["collection"] == modis_module.COLLECTION_ID
    assert modis["bands"] == [modis_module.CHLOR_A_BAND, modis_module.SST_BAND]
    # The Level-3 mapped grid (~4.6 km), as data-pipeline/src/modis.py says to
    # state it -- not the instrument's ~1 km nadir figure.
    assert modis["grid_resolution_m"] == modis_module.DEFAULT_SCALE_M == 4638
    assert modis["record_start"] == modis_module.ARCHIVE_START


# --------------------------------------------------------------------------
# Gates, floors, statistic
# --------------------------------------------------------------------------


def test_gates_are_scientific_status_unpatched(client):
    gates = _get(client)["gates"]
    assert gates["risk_evaluation_active"] is scientific_status.risk_evaluation_active()
    assert gates["signal_anomaly_active"] is scientific_status.signal_anomaly_active()


@pytest.mark.parametrize("risk", [True, False])
@pytest.mark.parametrize("signal", [True, False])
def test_gates_follow_scientific_status(client, monkeypatch, risk, signal):
    monkeypatch.setattr(scientific_status, "risk_evaluation_active", lambda: risk)
    monkeypatch.setattr(scientific_status, "signal_anomaly_active", lambda: signal)
    gates = _get(client)["gates"]
    assert gates["risk_evaluation_active"] is risk
    assert gates["signal_anomaly_active"] is signal


def test_floors_are_the_detection_constants(client):
    floors = _get(client)["gates"]["signal_anomaly_floors"]
    assert floors == {
        "min_independent_dates": bridge._signal_anomaly.MIN_INDEPENDENT_DATES,
        "max_observation_age_days": bridge._signal_anomaly.MAX_OBSERVATION_AGE_DAYS,
    } == {"min_independent_dates": 30, "max_observation_age_days": 14}


def test_floors_are_read_through_the_bridge_at_request_time(client, monkeypatch):
    monkeypatch.setattr(bridge, "SIGNAL_ANOMALY_MIN_INDEPENDENT_DATES", 31)
    monkeypatch.setattr(bridge, "SIGNAL_ANOMALY_MAX_OBSERVATION_AGE_DAYS", 13)
    floors = _get(client)["gates"]["signal_anomaly_floors"]
    assert floors == {"min_independent_dates": 31, "max_observation_age_days": 13}


def test_statistic_is_the_detection_definition(client):
    stat = _get(client)["gates"]["signal_anomaly_statistic"]
    module = bridge._signal_anomaly
    assert stat["mad_scale"] == module.MAD_SCALE
    assert stat["watch_at_z"] == module.WATCH_AT_Z == 2.0
    assert stat["high_at_z"] == module.HIGH_AT_Z == 3.0
    assert stat["formula"] in module.__doc__
    assert "provisional" in stat["note"] and "not validated" in stat["note"]
    assert _normalised(stat["note"]) in _normalised(module.__doc__)


# --------------------------------------------------------------------------
# Latest-scene policy
# --------------------------------------------------------------------------


def test_latest_scene_policy_is_the_effective_configuration(client, monkeypatch):
    monkeypatch.delenv("RASTER_SCENE_MAX_CLOUD_FRACTION", raising=False)
    monkeypatch.delenv("RASTER_SCENE_MIN_WATER_PIXELS", raising=False)
    policy = _get(client)["latest_scene_policy"]
    max_cloud, min_water = bridge.scene_thresholds()
    assert policy == {
        "max_cloud_fraction": max_cloud,
        "min_water_pixels": min_water,
        "poll_interval_hours": config.RASTER_SCAN_POLL_INTERVAL_HOURS,
        "min_scan_interval_hours": config.RASTER_SCAN_MIN_INTERVAL_HOURS,
        "settle_hours": trigger.SETTLE_HOURS,
    }


def test_latest_scene_thresholds_are_read_at_request_time(client, monkeypatch):
    monkeypatch.setenv("RASTER_SCENE_MAX_CLOUD_FRACTION", "0.35")
    monkeypatch.setenv("RASTER_SCENE_MIN_WATER_PIXELS", "250")
    policy = _get(client)["latest_scene_policy"]
    assert (policy["max_cloud_fraction"], policy["min_water_pixels"]) == (0.35, 250)


@pytest.mark.parametrize("name,value", [
    ("RASTER_SCENE_MAX_CLOUD_FRACTION", "banana"),
    ("RASTER_SCENE_MIN_WATER_PIXELS", "-3"),
])
def test_invalid_scene_threshold_env_is_null_not_a_guess(client, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    policy = _get(client)["latest_scene_policy"]
    assert policy["max_cloud_fraction"] is None and policy["min_water_pixels"] is None
    assert policy["settle_hours"] == trigger.SETTLE_HOURS


# --------------------------------------------------------------------------
# Season rule
# --------------------------------------------------------------------------


def test_season_rule_and_windows_are_detection_s(client):
    body = _get(client)
    assert body["season_rule"] == logic.SEASON_RULE
    assert body["season_windows"] == [
        {"month": m, "key": logic.season_key(m), "months": list(logic.season_months(m))}
        for m in range(1, 13)
    ]


# --------------------------------------------------------------------------
# References
# --------------------------------------------------------------------------


def test_every_doi_shown_appears_in_limitations(client):
    text = _LIMITATIONS.read_text(encoding="utf-8")
    references = _get(client)["references"]
    assert {ref["doi"] for ref in references} == _DOIS
    for ref in references:
        assert ref["doi"] in text


def test_citations_and_notes_are_copied_from_the_references_section(client):
    section = _references_section()
    for ref in _get(client)["references"]:
        assert ref["doi"] in section
        assert _normalised(ref["citation"]) in section, ref["id"]
        assert _normalised(ref["note"]) in section, ref["id"]


# --------------------------------------------------------------------------
# Baseline block and disclaimer
# --------------------------------------------------------------------------


def test_mode_off_baseline_block_and_disclaimer(client, valid_artefact):
    body = _get(client)
    _assert_mirrors(body["baseline"], {"mode": "off"})
    assert scientific_status.baseline_status() == {"mode": "off"}
    assert body["disclaimer"] == DISCLAIMER_TEXT


def test_valid_test_baseline_block_and_disclaimer(client, valid_artefact, test_mode):
    body = _get(client)
    status = scientific_status.baseline_status()
    assert status["valid"] is True
    _assert_mirrors(body["baseline"], status)
    # The per-site support in each site's weakest seasonal window.
    assert body["baseline"]["min_season_dates_by_location"] == {
        site: info["min_season_dates"] for site, info in valid_artefact["locations"].items()
    }
    assert body["baseline"]["base_rates"] == valid_artefact["self_check"]["total"]
    assert body["disclaimer"] == DISCLAIMER_TEXT_TEST_BASELINE
    # A valid TEST baseline opens the signal gate only; never risk evaluation.
    assert body["gates"]["signal_anomaly_active"] is True
    assert body["gates"]["risk_evaluation_active"] is False


def test_test_mode_without_an_artefact(client, test_mode):
    body = _get(client)
    status = scientific_status.baseline_status()
    assert status == {"mode": "test", "valid": False, "kind": "test", "reason": "no_artifact"}
    _assert_mirrors(body["baseline"], status)
    assert body["disclaimer"] == DISCLAIMER_TEXT
    assert body["gates"]["signal_anomaly_active"] is False


def test_test_mode_with_a_refused_artefact(client, _isolated, test_mode):
    tomorrow = (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()
    manifest, rows = _artefact(history_end=tomorrow)
    baseline_store.write_artifact(_isolated, manifest, rows)
    body = _get(client)
    status = scientific_status.baseline_status()
    assert status["valid"] is False and status["reason"] == "history_in_future"
    _assert_mirrors(body["baseline"], status)
    assert body["disclaimer"] == DISCLAIMER_TEXT


def test_response_never_carries_a_risk_level(client):
    text = re.sub(r"\s+", " ", client.get("/methods").text)
    assert '"risk_level"' not in text
