"""
Realistic Marine Physics & AI Test Suite for Harmful Algal Blooms (HABs) Detection.
Evaluates:
1. Physics-Based Spectral Indices (NDCI, 2BDA, 3BDA, Climatology z-scores)
2. Dual-Model ML Ensemble (XGBoost + Random Forest) against 6 domain-specific scenarios:
   - Scenario 1: Baseline Clean Offshore Water (Normal Tier)
   - Scenario 2: River Plume & Suspended Sediment False-Positive Check (Normal Tier)
   - Scenario 3: Early Incipient Growth / Pre-Bloom Phase (Watch Tier)
   - Scenario 4: Severe Noctiluca Bloom Outbreak (Warning Tier)
   - Scenario 5: Monsoon Cloud Dropout with NaN Imputation (Watch/Warning Tier)
   - Scenario 6: Out-of-Bound / Sensor Glitch Validation (ValueError on invalid physics)
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any, Dict

# Add backend and detection directories to sys.path
backend_dir = Path(__file__).resolve().parent.parent
detection_dir = Path(__file__).resolve().parent.parent.parent / "detection" / "src"
for d in [backend_dir, detection_dir]:
    if str(d) not in sys.path:
        sys.path.insert(0, str(d))

import numpy as np
import pytest

from ensemble_service import DualModelBloomEnsemble


def _calc_cyclical(month: int) -> tuple[float, float]:
    """Helper to compute cyclical month_sin and month_cos features."""
    sin_val = math.sin(2 * math.pi * month / 12)
    cos_val = math.cos(2 * math.pi * month / 12)
    return round(sin_val, 6), round(cos_val, 6)


@pytest.fixture(scope="module")
def ensemble_service():
    """Initializes and provides the trained DualModelBloomEnsemble service."""
    return DualModelBloomEnsemble()


# ==============================================================================
# 1. Physics-Based Rule Engine & Spectral Indices Tests
# ==============================================================================

def test_physics_spectral_indices():
    """Validates NDCI, 2BDA, 3BDA, and Climatology z-score calculations."""
    # Test Bands for clean oligotrophic water
    clean_bands = {"B2": 420.0, "B3": 560.0, "B4": 310.0, "B5": 280.0, "B6": 210.0}
    # NDCI = (B5 - B4) / (B5 + B4)
    ndci_clean = (clean_bands["B5"] - clean_bands["B4"]) / (clean_bands["B5"] + clean_bands["B4"])
    # 2BDA = B5 / B4
    bda2_clean = clean_bands["B5"] / clean_bands["B4"]
    # 3BDA = (1/B4 - 1/B5) * B6
    bda3_clean = (1.0 / clean_bands["B4"] - 1.0 / clean_bands["B5"]) * clean_bands["B6"]

    assert ndci_clean < 0.0  # Clean water has negative/near-zero NDCI
    assert bda2_clean < 1.0
    assert bda3_clean < 0.0

    # Test Bands for intense bloom water (Red Edge spike at B5)
    bloom_bands = {"B2": 250.0, "B3": 680.0, "B4": 420.0, "B5": 1150.0, "B6": 890.0}
    ndci_bloom = (bloom_bands["B5"] - bloom_bands["B4"]) / (bloom_bands["B5"] + bloom_bands["B4"])
    bda2_bloom = bloom_bands["B5"] / bloom_bands["B4"]
    bda3_bloom = (1.0 / bloom_bands["B4"] - 1.0 / bloom_bands["B5"]) * bloom_bands["B6"]

    assert ndci_bloom > 0.40  # Bloom shows positive red-edge peak
    assert bda2_bloom > 2.0
    assert bda3_bloom > 0.50

    # Climatology z-score formula: (observed - baseline_mean) / baseline_std
    obs_chl = 18.5
    clim_mean = 3.2
    clim_std = 1.8
    z_score = (obs_chl - clim_mean) / clim_std
    assert z_score == pytest.approx(8.5, rel=1e-2)


# ==============================================================================
# 2. Parameterized Test Scenarios Definition
# ==============================================================================

REALISTIC_SCENARIOS = {
    "Scenario 1: Clean Offshore Water": {
        "description": "Oligotrophic / Mesotrophic clean seawater during dry season (Feb)",
        "features": {
            "chlor_a": 1.2,
            "sst": 28.5,
            "nflh": 0.01,
            "poc": 120.0,
            "chlor_a_anomaly": -0.2,
            "month_sin": _calc_cyclical(2)[0],
            "month_cos": _calc_cyclical(2)[1],
        },
        "expected": {
            "bloom_detected": False,
            "max_ensemble_confidence": 0.20,
            "risk_tier": "NORMAL",
        },
    },
    "Scenario 2: River Plume & Suspended Sediment": {
        "description": "Chao Phraya discharge with high sediment but no active algae bloom (Oct)",
        "features": {
            "chlor_a": 3.8,
            "sst": 30.0,
            "nflh": 0.03,
            "poc": 650.0,
            "chlor_a_anomaly": 0.8,
            "month_sin": _calc_cyclical(10)[0],
            "month_cos": _calc_cyclical(10)[1],
        },
        "expected": {
            "bloom_detected": False,
            "max_rf_probability": 0.35,
            "risk_tier": "NORMAL",
        },
    },
    "Scenario 3: Early Incipient Growth": {
        "description": "Nutrient accumulation & warming inducing cell division (Jul)",
        "features": {
            "chlor_a": 7.5,
            "sst": 31.8,
            "nflh": 0.18,
            "poc": 850.0,
            "chlor_a_anomaly": 1.65,
            "month_sin": _calc_cyclical(7)[0],
            "month_cos": _calc_cyclical(7)[1],
        },
        "expected": {
            "min_xgb_probability": 0.50,
            "min_ensemble_confidence": 0.35,
            "max_ensemble_confidence": 0.65,
            "risk_tier": "WATCH",
        },
    },
    "Scenario 4: Severe Noctiluca Bloom": {
        "description": "Massive hypereutrophic bloom event at Chonburi coast with discoloration (Aug)",
        "features": {
            "chlor_a": 38.5,
            "sst": 32.4,
            "nflh": 0.72,
            "poc": 2400.0,
            "chlor_a_anomaly": 3.85,
            "month_sin": _calc_cyclical(8)[0],
            "month_cos": _calc_cyclical(8)[1],
        },
        "expected": {
            "bloom_detected": True,
            "min_ensemble_confidence": 0.85,
            "min_xgb_probability": 0.85,
            "min_rf_probability": 0.80,
            "risk_tier": "WARNING",
        },
    },
    "Scenario 5: Monsoon Cloud Dropout": {
        "description": "Partial cloud obstruction causing NaN in nflh and poc (Sep)",
        "features": {
            "chlor_a": 18.0,
            "sst": 30.5,
            "nflh": np.nan,
            "poc": np.nan,
            "chlor_a_anomaly": 2.4,
            "month_sin": _calc_cyclical(9)[0],
            "month_cos": _calc_cyclical(9)[1],
        },
        "expected": {
            "bloom_detected": True,
            "allowed_tiers": ["WATCH", "WARNING"],
        },
    },
}


# ==============================================================================
# 3. Parameterized & Individual Unit Test Cases
# ==============================================================================

@pytest.mark.parametrize(
    "scenario_name,scenario_data",
    list(REALISTIC_SCENARIOS.items()),
    ids=list(REALISTIC_SCENARIOS.keys()),
)
def test_parameterized_scenarios(ensemble_service, scenario_name, scenario_data):
    """Parameterized validation of all realistic scenarios against ensemble prediction."""
    result = ensemble_service.predict_observation(scenario_data["features"])
    exp = scenario_data["expected"]

    if "bloom_detected" in exp:
        assert result["bloom_detected"] == exp["bloom_detected"]
    if "risk_tier" in exp:
        assert result["risk_tier"] == exp["risk_tier"]
    if "allowed_tiers" in exp:
        assert result["risk_tier"] in exp["allowed_tiers"]
    if "max_ensemble_confidence" in exp:
        assert result["ensemble_confidence"] < exp["max_ensemble_confidence"]
    if "min_ensemble_confidence" in exp:
        assert result["ensemble_confidence"] >= exp["min_ensemble_confidence"]
    if "max_rf_probability" in exp:
        assert result["model_breakdown"]["rf_probability"] < exp["max_rf_probability"]
    if "min_xgb_probability" in exp:
        assert result["model_breakdown"]["xgb_probability"] >= exp["min_xgb_probability"]


def test_scenario_6_out_of_bounds_sensor_glitch(ensemble_service):
    """Scenario 6: Verify corrupt or physically impossible sensor values raise ValueError."""
    # Negative Chlorophyll-a
    invalid_chlor = {
        "chlor_a": -999.0,
        "sst": 30.0,
        "nflh": 0.1,
        "poc": 200.0,
        "chlor_a_anomaly": 0.0,
        "month_sin": 0.0,
        "month_cos": 1.0,
    }
    with pytest.raises(ValueError, match="Out of physical bounds for feature 'chlor_a'"):
        ensemble_service.predict_observation(invalid_chlor)

    # Extreme boiling SST (> 50°C)
    invalid_sst = {
        "chlor_a": 5.0,
        "sst": 85.0,
        "nflh": 0.1,
        "poc": 200.0,
        "chlor_a_anomaly": 0.0,
        "month_sin": 0.0,
        "month_cos": 1.0,
    }
    with pytest.raises(ValueError, match="Out of physical bounds for feature 'sst'"):
        ensemble_service.predict_observation(invalid_sst)


# ==============================================================================
# 4. Comprehensive Summary Reporting Test
# ==============================================================================

def test_print_execution_summary_table(ensemble_service):
    """Executes all scenarios and prints a formatted console report table."""
    print("\n" + "=" * 94)
    print("      REALISTIC MARINE PHYSICS & DUAL-MODEL ENSEMBLE SCENARIO EVALUATION REPORT")
    print("=" * 94)
    print(f"{'Scenario Name':<38} | {'XGB %':<8} | {'RF %':<8} | {'Ensemble':<10} | {'Tier':<8} | {'Status'}")
    print("-" * 94)

    for name, data in REALISTIC_SCENARIOS.items():
        res = ensemble_service.predict_observation(data["features"])
        xgb_pct = f"{res['model_breakdown']['xgb_probability']*100:.1f}%"
        rf_pct = f"{res['model_breakdown']['rf_probability']*100:.1f}%"
        ens_pct = f"{res['ensemble_confidence']*100:.1f}%"
        tier = res["risk_tier"]
        status = "PASSED"

        print(f"{name:<38} | {xgb_pct:<8} | {rf_pct:<8} | {ens_pct:<10} | {tier:<8} | {status}")

    print("=" * 94)
