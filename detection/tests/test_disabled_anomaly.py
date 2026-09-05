"""Regression proof: real index readings cannot become unit-mismatched scores.

All satellite I/O is mocked at the existing typed bridge; index arithmetic,
event orchestration, rule evaluation, and report rendering remain real.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import prediction, thresholds  # noqa: E402

BANDS = {
    "B2": 1100.0, "B3": 1400.0, "B4": 1300.0, "B5": 1450.0,
    "B6": 1600.0, "cloud_fraction": 0.0, "actual_date": "2020-02-16",
}
CHLOR_A_CLIMATOLOGY = {"mean": 5.586, "std": 1.231, "n": 6, "reliable": True}


def forbid_score(*args, **kwargs):
    pytest.fail("No valid index baseline exists; z_score must not run")


@pytest.mark.parametrize("climatology", [CHLOR_A_CLIMATOLOGY, None])
def test_successful_satellite_reading_never_scores_indices(monkeypatch, climatology):
    monkeypatch.setattr(thresholds, "get_sentinel2_bands", lambda *a, **k: dict(BANDS))
    monkeypatch.setattr(thresholds, "build_climatology", lambda *a, **k: climatology)
    monkeypatch.setattr(thresholds, "z_score", forbid_score, raising=False)

    result = thresholds.attempt_satellite_reading(
        13.338, 100.925, "2020-02-15", 29, thresholds.load_config()
    )

    assert result["sentinel2_status"] == "ok"
    assert result["actual_date"] == "2020-02-16"
    assert result["index_values"]["ndci"] == pytest.approx(150.0 / 2750.0)
    assert result["climatology"] == climatology
    assert result["z_scores"] is None
    assert result["z_score_status"] == "not_computed_no_valid_baseline"


@pytest.mark.parametrize("error,status", [
    (thresholds.NoCloudFreeImageryError, "no_imagery"),
    (thresholds.NoWaterPixelsError, "no_water_pixels"),
])
def test_missing_imagery_keeps_independent_modis_context(monkeypatch, error, status):
    def no_bands(*args, **kwargs):
        raise error("forced unavailable")

    monkeypatch.setattr(thresholds, "get_sentinel2_bands", no_bands)
    monkeypatch.setattr(thresholds, "build_climatology", lambda *a, **k: CHLOR_A_CLIMATOLOGY)
    monkeypatch.setattr(thresholds, "z_score", forbid_score, raising=False)

    result = thresholds.attempt_satellite_reading(
        13.338, 100.925, "2020-02-15", 29, thresholds.load_config()
    )

    assert result["sentinel2_status"] == status
    assert result["index_values"] is None
    assert result["actual_date"] is None
    assert result["climatology"] == CHLOR_A_CLIMATOLOGY
    assert result["z_scores"] is None
    assert result["z_score_status"] == "not_computed_no_valid_baseline"


def test_all_events_and_proxy_stay_unevaluable_even_with_realistic_bands(monkeypatch):
    monkeypatch.setattr(thresholds, "get_sentinel2_bands", lambda *a, **k: dict(BANDS))
    monkeypatch.setattr(thresholds, "build_climatology", lambda *a, **k: CHLOR_A_CLIMATOLOGY)
    monkeypatch.setattr(thresholds, "z_score", forbid_score, raising=False)
    result = thresholds.run()

    assert result["n_events"] == 14
    assert result["matched_pairs"] == []
    assert len(result["loo_results"]) == 11  # 9 single events and 2 clusters
    assert all(row["z_scores"] is None and row["flagged"] is None for row in result["rows"])
    assert all(row["z_score_status"] == "not_computed_no_valid_baseline" for row in result["rows"])
    assert all(item["caught"] is None for item in result["loo_results"])
    assert all(item["n_flagged"] is None for item in result["sweep"])
    proxy_row = next(row for row in result["rows"] if row["event_id"] == "th_001")
    assert proxy_row["actual_date"] == "2020-02-16"
    assert proxy_row["index_values"] is not None
    for threshold in result["config"]["thresholds"].values():
        assert threshold["calibrated_elevated_z"] is None
        assert threshold["calibrated_warning_z"] is None


def test_disabled_calibration_rejects_legacy_pairs_as_evidence():
    config = thresholds.load_config()
    legacy_pairs = [{"event_id": "th_010", "z": 100.0}]
    result = thresholds.leave_one_out(thresholds.load_events(), config, legacy_pairs)
    assert all(row["caught"] is None for row in result)
    assert all("Cannot be evaluated" in row["reason"] for row in result)
    sweep = thresholds.sweep_thresholds(legacy_pairs, [1.5, 2.0])
    assert all(row["n_flagged"] is None and row["flagged_ids"] is None for row in sweep)


def test_risk_stays_unavailable_with_rising_chlorophyll_and_warm_sst(monkeypatch):
    import _data_pipeline

    monkeypatch.setattr(prediction, "get_sentinel2_bands", lambda *a, **k: dict(BANDS))
    monkeypatch.setattr(_data_pipeline, "get_modis_chlorophyll_history", lambda *a: [
        {"date": "2020-02-10", "chlor_a": 2.0},
        {"date": "2020-02-15", "chlor_a": 8.0},
    ])
    monkeypatch.setattr(prediction, "get_modis_sst", lambda *a: {
        "sst": 32.0, "sst_climatology": {"mean": 29.0, "std": 1.0},
    })
    monkeypatch.setattr(prediction, "get_rainfall_proxy", lambda *a: None)

    result = prediction.risk_level(13.338, 100.925, "2020-02-15")

    assert result["trend_14d"]["rising"] is True
    assert result["sst_anomaly"] > 0
    assert result["level"] is None
    assert result["reason"] == "not_computed_no_valid_baseline"
    assert result["triggered_rules"] == []
    assert result["detection"]["actual_date"] == "2020-02-16"
    assert "detected" not in result["detection"]


def test_report_keeps_real_index_and_date_without_any_score(monkeypatch, tmp_path):
    from src import generate_reports

    monkeypatch.setattr(thresholds, "get_sentinel2_bands", lambda *a, **k: dict(BANDS))
    monkeypatch.setattr(thresholds, "build_climatology", lambda *a, **k: CHLOR_A_CLIMATOLOGY)
    result = thresholds.run()
    monkeypatch.setattr(generate_reports, "REPORTS_DIR", tmp_path)
    generate_reports.write_event_table(result)

    report = (tmp_path / "event_table.md").read_text()
    assert "All 14 events cannot be evaluated" in report
    assert "2020-02-16" in report
    assert "0.0545" in report
    assert "11 held-out units" in report
    assert "Not computed — no valid baseline exists" in report
    assert "anomaly_z" not in report
    assert "| caught |" not in report
    assert "| th_010 |" in report
