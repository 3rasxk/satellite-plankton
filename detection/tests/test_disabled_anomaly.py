"""Regression proof: rule evaluation stays unavailable without a baseline."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import prediction  # noqa: E402

BANDS = {
    "B2": 1100.0, "B3": 1400.0, "B4": 1300.0, "B5": 1450.0,
    "B6": 1600.0, "cloud_fraction": 0.0, "actual_date": "2020-02-15",
}
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
    assert result["signal_anomaly_level"] is None
    assert result["reason"] == "not_computed_no_valid_baseline"
    assert result["triggered_rules"] == []
    assert result["detection"]["actual_date"] == "2020-02-15"
    assert "detected" not in result["detection"]
