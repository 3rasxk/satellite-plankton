"""
Unit tests and Temporal Integrity Checks for Multi-Horizon Bloom Transition Forecaster.
Verifies:
1. Non-Leakage Invariance: Future rows cannot affect past/present features.
2. Monotonic Probability Consistency: P(1d) <= P(3d) <= P(7d) <= P(14d).
3. Plausible Timeline Assignment: Rapid bloom surges predict early arrival (<7d).
4. Full Output Schema Compliance.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add backend to sys.path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import numpy as np
import pandas as pd
import pytest

from forecast_service import MultiHorizonBloomForecast, compute_leakage_safe_features


@pytest.fixture(scope="module")
def sample_station_history():
    """Generates a realistic 10-observation time series history for a station."""
    base_date = datetime(2026, 8, 1)
    rows = []
    for i in range(10):
        d = base_date + timedelta(days=i * 3)
        rows.append({
            "date": d,
            "chlor_a": 1.5 + (i * 0.4),  # Steady rise
            "sst": 29.5 + (i * 0.2),
            "nflh": 0.02 + (i * 0.03),
            "poc": 150.0 + (i * 50.0),
            "chlor_a_anomaly": -0.5 + (i * 0.25),
            "label": 0,
        })
    return pd.DataFrame(rows)


def test_non_leakage_invariance(sample_station_history):
    """
    1. Non-Leakage Invariance Test:
    Modifying or appending future observations (row t+1, t+2) MUST NOT change
    any lag or rolling feature values at row t.
    """
    df_original = sample_station_history.copy()
    features_before = compute_leakage_safe_features(df_original)

    # Pick index t = 7
    t = 7
    target_row_before = features_before.iloc[t].to_dict()

    # Create a modified future dataframe where row 8 and 9 are drastically altered
    df_modified = sample_station_history.copy()
    df_modified.loc[8, "chlor_a"] = 999.0
    df_modified.loc[9, "chlor_a"] = 888.0
    df_modified.loc[8, "sst"] = 45.0
    df_modified.loc[9, "sst"] = 45.0

    features_after = compute_leakage_safe_features(df_modified)
    target_row_after = features_after.iloc[t].to_dict()

    # Compare all engineered features at time t
    for col in [
        "chlor_a_lag1", "chlor_a_lag3", "delta_chlor_a_1",
        "chlor_a_roll_mean_3", "chlor_a_roll_max_7", "sst_lag1", "sst_roll_mean_3"
    ]:
        val_before = target_row_before[col]
        val_after = target_row_after[col]
        assert np.isclose(val_before, val_after, equal_nan=True), (
            f"Leakage detected in feature '{col}' at index {t}: before={val_before}, after={val_after}"
        )


def test_monotonic_probability_consistency(sample_station_history):
    """
    2. Monotonic Probability Consistency Test:
    Cumulative risk must satisfy P(1d) <= P(3d) <= P(7d) <= P(14d).
    """
    forecaster = MultiHorizonBloomForecast()
    result = forecaster.predict_future_warning(sample_station_history, site_key="CHONBURI_BUOY_01")

    probs = result["estimated_bloom_arrival"]["horizon_probabilities"]
    p1 = probs["within_1d"]
    p3 = probs["within_3d"]
    p7 = probs["within_7d"]
    p14 = probs["within_14d"]

    assert p1 <= p3, f"Non-monotonic probability: P(1d)={p1} > P(3d)={p3}"
    assert p3 <= p7, f"Non-monotonic probability: P(3d)={p3} > P(7d)={p7}"
    assert p7 <= p14, f"Non-monotonic probability: P(7d)={p7} > P(14d)={p14}"
    assert 0.0 <= p1 <= 1.0
    assert 0.0 <= p14 <= 1.0


def test_plausible_timeline_assignment():
    """
    3. Plausible Timeline Assignment Test:
    A sharply spiking chlorophyll trajectory cannot output an arrival prediction of '>14 days (Stable)'.
    """
    forecaster = MultiHorizonBloomForecast()

    # Rapid bloom emergence sequence
    base_date = datetime(2026, 8, 1)
    spiking_data = pd.DataFrame([
        {"date": base_date + timedelta(days=0), "chlor_a": 2.0, "sst": 30.0, "chlor_a_anomaly": 0.2},
        {"date": base_date + timedelta(days=3), "chlor_a": 3.5, "sst": 30.8, "chlor_a_anomaly": 0.9},
        {"date": base_date + timedelta(days=6), "chlor_a": 6.8, "sst": 31.5, "chlor_a_anomaly": 1.8},
        {"date": base_date + timedelta(days=9), "chlor_a": 12.5, "sst": 32.2, "chlor_a_anomaly": 2.9},  # Sharp surge
    ])

    result = spiking_data_res = forecaster.predict_future_warning(spiking_data, site_key="PATTAYA_BAY_01")
    arrival = result["estimated_bloom_arrival"]["predicted_days_range"]
    p7 = result["forecast_7d"]["risk_probability"]

    assert arrival != ">14 days (Stable)", f"Expected early arrival warning for spiking data, but got: {arrival}"
    assert p7 >= 0.60, f"Expected 7d risk probability >= 0.60, got {p7}"
    assert result["forecast_7d"]["risk_tier"] == "HIGH_RISK"
    assert result["forecast_7d"]["forecast_alert"] is True


def test_forecast_output_schema_integrity(sample_station_history):
    """
    4. Output Schema Compliance Test:
    Validates exact structured JSON response schema.
    """
    forecaster = MultiHorizonBloomForecast()
    out = forecaster.predict_future_warning(sample_station_history, site_key="CHAOPHRAYA_01")

    # Assert top-level keys
    assert "site_key" in out
    assert "forecast_timestamp" in out
    assert "current_status" in out
    assert "forecast_7d" in out
    assert "estimated_bloom_arrival" in out
    assert "driving_factors" in out

    # Assert forecast_7d sub-schema
    f7d = out["forecast_7d"]
    assert isinstance(f7d["risk_probability"], float)
    assert f7d["risk_tier"] in ["LOW_RISK", "ELEVATED", "HIGH_RISK"]
    assert isinstance(f7d["forecast_alert"], bool)

    # Assert arrival sub-schema
    arr = out["estimated_bloom_arrival"]
    assert isinstance(arr["predicted_days_range"], str)
    assert len(arr["confidence_interval"]) == 2
    assert all(k in arr["horizon_probabilities"] for k in ["within_1d", "within_3d", "within_7d", "within_14d"])

    # Assert driving factors is a non-empty list of strings
    assert isinstance(out["driving_factors"], list)
    assert len(out["driving_factors"]) > 0
