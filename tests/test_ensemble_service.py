"""
Unit tests and latency benchmarks for DualModelBloomEnsemble.
Validates artifact existence, schema validation, soft-voting math,
extreme case classification, and <5.0ms inference latency.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import numpy as np
import pandas as pd
import pytest

from ensemble_service import DualModelBloomEnsemble, FEATURE_COLUMNS


@pytest.fixture(scope="module")
def ensemble_service():
    return DualModelBloomEnsemble()


def test_artifact_existence():
    """1. Artifact Existence: Ensure model artifacts exist on disk."""
    candidates_rf = [
        Path("backend/models/random_forest_bloom.joblib"),
        Path("models/random_forest_bloom.joblib"),
        Path(__file__).resolve().parent.parent / "backend" / "models" / "random_forest_bloom.joblib",
    ]
    candidates_xgb = [
        Path("backend/models/xgboost_bloom.joblib"),
        Path("models/xgboost_bloom.joblib"),
        Path(__file__).resolve().parent.parent / "backend" / "models" / "xgboost_bloom.joblib",
    ]
    assert any(p.exists() for p in candidates_rf), "random_forest_bloom.joblib missing"
    assert any(p.exists() for p in candidates_xgb), "xgboost_bloom.joblib missing"


def test_schema_integrity_rejects_missing_features(ensemble_service):
    """2. Schema Integrity: Verify ensemble rejects inputs missing any of the 7 core features."""
    incomplete_input = {
        "chlor_a": 1.2,
        "sst": 29.5,
        "nflh": 0.05,
        # missing poc, chlor_a_anomaly, month_sin, month_cos
    }
    with pytest.raises(ValueError, match="Invalid feature schema: missing required column"):
        ensemble_service.predict_observation(incomplete_input)

    df_incomplete = pd.DataFrame([incomplete_input])
    with pytest.raises(ValueError, match="Invalid feature schema: missing required column"):
        ensemble_service.predict_observation(df_incomplete)


def test_dual_decision_logic_soft_voting(ensemble_service):
    """3. Dual Decision Logic: Ensure ensemble_confidence is exact arithmetic mean of XGB and RF."""
    sample_features = {
        "chlor_a": 3.5,
        "sst": 30.1,
        "nflh": 0.12,
        "poc": 450.0,
        "chlor_a_anomaly": 1.2,
        "month_sin": 0.5,
        "month_cos": 0.866,
    }
    result = ensemble_service.predict_observation(sample_features)

    xgb_p = result["model_breakdown"]["xgb_probability"]
    rf_p = result["model_breakdown"]["rf_probability"]
    expected_conf = round((xgb_p + rf_p) / 2.0, 4)

    assert result["ensemble_confidence"] == pytest.approx(expected_conf, abs=1e-4)
    assert result["bloom_detected"] == (result["ensemble_confidence"] >= result["decision_threshold"])


def test_extreme_scenarios(ensemble_service):
    """4. Extreme Scenarios: Clean water vs High-Anomaly Bloom."""
    # Clean baseline water
    clean_water = {
        "chlor_a": 0.35,
        "sst": 28.5,
        "nflh": 0.01,
        "poc": 90.0,
        "chlor_a_anomaly": -1.2,
        "month_sin": 0.0,
        "month_cos": 1.0,
    }
    clean_result = ensemble_service.predict_observation(clean_water)
    assert clean_result["risk_tier"] == "NORMAL"
    assert clean_result["bloom_detected"] is False
    assert clean_result["ensemble_confidence"] < 0.35

    # Massive confirmed bloom
    bloom_water = {
        "chlor_a": 18.5,
        "sst": 31.5,
        "nflh": 0.65,
        "poc": 2800.0,
        "chlor_a_anomaly": 4.2,
        "month_sin": 0.5,
        "month_cos": -0.866,
    }
    bloom_result = ensemble_service.predict_observation(bloom_water)
    assert bloom_result["risk_tier"] == "WARNING"
    assert bloom_result["bloom_detected"] is True
    assert bloom_result["ensemble_confidence"] >= 0.65


def test_inference_latency_benchmark(ensemble_service):
    """5. Inference Latency Benchmark: Assert single observation runs in < 5.0 ms."""
    sample = {
        "chlor_a": 4.8,
        "sst": 30.2,
        "nflh": 0.22,
        "poc": 620.0,
        "chlor_a_anomaly": 1.8,
        "month_sin": 0.866,
        "month_cos": -0.5,
    }

    # Warmup
    for _ in range(10):
        ensemble_service.predict_observation(sample)

    # Measure over 100 iterations
    n_iters = 100
    start = time.perf_counter()
    for _ in range(n_iters):
        ensemble_service.predict_observation(sample)
    total_time_ms = (time.perf_counter() - start) * 1000.0
    avg_latency_ms = total_time_ms / n_iters

    print(f"\n[LATENCY BENCHMARK] Average single inference latency: {avg_latency_ms:.3f} ms")
    assert avg_latency_ms < 5.0, f"Inference too slow: {avg_latency_ms:.3f} ms (expected < 5.0 ms)"
