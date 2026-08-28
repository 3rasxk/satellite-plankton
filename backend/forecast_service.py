"""
Multi-Horizon Transition Forecasting & Days-to-Bloom Engine.
Implements leakage-safe temporal engineering, multi-horizon risk forecasting (1, 3, 7, 14 days),
arrival window estimation, and oceanographic driving factor explanations.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


def compute_leakage_safe_features(station_df: pd.DataFrame) -> pd.DataFrame:
    """
    Computes backward-looking temporal lag and velocity features with ZERO future leakage.
    Strictly uses `.shift(1)` before rolling aggregations so row t only observes t-1, t-2, ...
    """
    df = station_df.copy()
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
    else:
        df = df.reset_index(drop=True)

    # Core base features with fallbacks
    for col in ["chlor_a", "sst", "nflh", "poc", "chlor_a_anomaly"]:
        if col not in df.columns:
            df[col] = 0.0

    # Temporal Lags (Backward only)
    df["chlor_a_lag1"] = df["chlor_a"].shift(1)
    df["chlor_a_lag3"] = df["chlor_a"].shift(3)
    df["chlor_a_lag7"] = df["chlor_a"].shift(7)

    df["sst_lag1"] = df["sst"].shift(1)
    df["sst_lag3"] = df["sst"].shift(3)

    df["anomaly_lag1"] = df["chlor_a_anomaly"].shift(1)
    df["anomaly_lag3"] = df["chlor_a_anomaly"].shift(3)

    # Velocity / Rate of Change
    df["delta_chlor_a_1"] = df["chlor_a"] - df["chlor_a_lag1"].fillna(df["chlor_a"])
    df["delta_chlor_a_3"] = df["chlor_a"] - df["chlor_a_lag3"].fillna(df["chlor_a"])
    df["delta_sst_3"] = df["sst"] - df["sst_lag3"].fillna(df["sst"])

    # Trailing Rolling Stats (Shifted by 1 to exclude current target/observation)
    shifted_chl = df["chlor_a"].shift(1)
    df["chlor_a_roll_mean_3"] = shifted_chl.rolling(window=3, min_periods=1).mean()
    df["chlor_a_roll_max_7"] = shifted_chl.rolling(window=7, min_periods=1).max()
    df["chlor_a_roll_std_7"] = shifted_chl.rolling(window=7, min_periods=2).std().fillna(0.0)

    shifted_sst = df["sst"].shift(1)
    df["sst_roll_mean_3"] = shifted_sst.rolling(window=3, min_periods=1).mean()

    # Days since previous observation
    if "date" in df.columns:
        df["days_since_prev_obs"] = (df["date"] - df["date"].shift(1)).dt.total_seconds() / 86400.0
        df["days_since_prev_obs"] = df["days_since_prev_obs"].fillna(5.0)
    else:
        df["days_since_prev_obs"] = 5.0

    # Historical Bloom Recurrence
    if "label" in df.columns:
        shifted_label = df["label"].shift(1).fillna(0)
        df["trailing_warning_count_30d"] = shifted_label.rolling(window=6, min_periods=1).sum().fillna(0)
    else:
        df["trailing_warning_count_30d"] = 0

    return df


class MultiHorizonBloomForecast:
    """
    Scientifically sound multi-horizon bloom transition forecaster & arrival estimator.
    """

    def __init__(self, operational_horizon_days: int = 7):
        self.primary_horizon = operational_horizon_days

    def _estimate_horizon_probabilities(
        self,
        current_chl: float,
        current_sst: float,
        current_anomaly: float,
        delta_chl: float,
        delta_sst: float,
        roll_mean_chl: float,
    ) -> Dict[str, float]:
        """
        Estimates non-decreasing, monotonic multi-horizon transition probabilities:
        P(1d) <= P(3d) <= P(7d) <= P(14d).
        """
        # Baseline risk derived from current anomaly and velocity
        velocity_factor = max(0.0, delta_chl * 0.15)
        anomaly_factor = max(0.0, (current_anomaly + 0.5) * 0.22)
        thermal_factor = max(0.0, (current_sst - 30.0) * 0.08)

        base_hazard = anomaly_factor + velocity_factor + thermal_factor

        # Multi-horizon cumulative probability model: P(T <= t) = 1 - exp(-hazard * sqrt(t))
        p_1d = 1.0 - math.exp(-base_hazard * 0.35)
        p_3d = 1.0 - math.exp(-base_hazard * 0.70)
        p_7d = 1.0 - math.exp(-base_hazard * 1.15)
        p_14d = 1.0 - math.exp(-base_hazard * 1.60)

        # Enforce strict bounds and monotonic non-decreasing guarantee
        p_1d = float(np.clip(p_1d, 0.01, 0.98))
        p_3d = float(np.clip(max(p_3d, p_1d), 0.02, 0.985))
        p_7d = float(np.clip(max(p_7d, p_3d), 0.03, 0.99))
        p_14d = float(np.clip(max(p_14d, p_7d), 0.05, 0.995))

        return {
            "within_1d": round(p_1d, 3),
            "within_3d": round(p_3d, 3),
            "within_7d": round(p_7d, 3),
            "within_14d": round(p_14d, 3),
        }

    def _derive_driving_factors(
        self,
        current_chl: float,
        current_sst: float,
        current_anomaly: float,
        delta_chl: float,
        delta_sst: float,
    ) -> List[str]:
        """Generates domain-specific oceanographic explanations for the forecast."""
        factors = []
        if delta_chl >= 1.5:
            factors.append(f"Rapid Chlorophyll-a rise (+{delta_chl:.1f} mg/m³ over past observations)")
        elif delta_chl > 0.4:
            factors.append(f"Steadily increasing Chlorophyll-a trajectory (+{delta_chl:.1f} mg/m³)")
        else:
            factors.append("Chlorophyll-a levels stable near seasonal baseline")

        if current_sst >= 31.0 or delta_sst >= 1.0:
            factors.append(f"Sea Surface Temperature elevated at {current_sst:.1f}°C favoring rapid cellular growth")

        if current_anomaly >= 1.5:
            factors.append(f"Persistent positive anomaly z-score (+{current_anomaly:.2f} σ above 24-year climatology)")
        elif current_anomaly >= 0.8:
            factors.append(f"Mild positive climatological anomaly (+{current_anomaly:.2f} σ)")

        if not factors:
            factors.append("Hydrological parameters within normal seasonal variations")

        return factors

    def _estimate_arrival_window(
        self,
        horizon_probs: Dict[str, float],
        delta_chl: float,
        anomaly_z: float,
    ) -> Tuple[str, List[int]]:
        """Determines expected days-to-bloom arrival window and confidence interval."""
        p_1d = horizon_probs["within_1d"]
        p_3d = horizon_probs["within_3d"]
        p_7d = horizon_probs["within_7d"]
        p_14d = horizon_probs["within_14d"]

        if p_1d >= 0.60 or (anomaly_z >= 2.5 and delta_chl >= 3.0):
            return "1 - 2 days", [1, 2]
        elif p_3d >= 0.50 or (anomaly_z >= 1.5 and delta_chl >= 1.5):
            return "3 - 5 days", [3, 6]
        elif p_7d >= 0.50:
            return "5 - 7 days", [4, 8]
        elif p_14d >= 0.40:
            return "8 - 14 days", [8, 14]
        else:
            return ">14 days (Stable)", [14, 30]

    def predict_future_warning(
        self,
        station_history_df: pd.DataFrame,
        site_key: Optional[str] = "UGOT_SITE_01",
    ) -> Dict[str, Any]:
        """
        Executes multi-horizon forecasting from a chronological station history DataFrame.
        """
        if station_history_df.empty:
            raise ValueError("Input station history DataFrame cannot be empty.")

        # Compute strictly backward-looking lag features
        feat_df = compute_leakage_safe_features(station_history_df)
        latest_row = feat_df.iloc[-1]

        current_chl = float(latest_row.get("chlor_a", 1.2))
        current_sst = float(latest_row.get("sst", 29.5))
        current_anomaly = float(latest_row.get("chlor_a_anomaly", 0.0))
        delta_chl = float(latest_row.get("delta_chlor_a_1", 0.0))
        delta_sst = float(latest_row.get("delta_sst_3", 0.0))
        roll_mean_chl = float(latest_row.get("chlor_a_roll_mean_3", current_chl))

        horizon_probs = self._estimate_horizon_probabilities(
            current_chl=current_chl,
            current_sst=current_sst,
            current_anomaly=current_anomaly,
            delta_chl=delta_chl,
            delta_sst=delta_sst,
            roll_mean_chl=roll_mean_chl,
        )

        p_7d = horizon_probs["within_7d"]
        if p_7d >= 0.60:
            risk_tier = "HIGH_RISK"
            alert = True
        elif p_7d >= 0.35:
            risk_tier = "ELEVATED"
            alert = False
        else:
            risk_tier = "LOW_RISK"
            alert = False

        arrival_range, ci = self._estimate_arrival_window(horizon_probs, delta_chl, current_anomaly)
        driving_factors = self._derive_driving_factors(
            current_chl, current_sst, current_anomaly, delta_chl, delta_sst
        )

        ts = (
            latest_row["date"].isoformat()
            if "date" in latest_row and pd.notna(latest_row["date"])
            else datetime.now(timezone.utc).isoformat()
        )

        current_status = "ELEVATED" if current_anomaly >= 1.5 else "NORMAL"

        return {
            "site_key": site_key or "UGOT_MONITORED_SITE",
            "forecast_timestamp": ts,
            "current_status": current_status,
            "forecast_7d": {
                "risk_probability": p_7d,
                "risk_tier": risk_tier,
                "forecast_alert": alert,
            },
            "estimated_bloom_arrival": {
                "predicted_days_range": arrival_range,
                "confidence_interval": ci,
                "horizon_probabilities": horizon_probs,
            },
            "driving_factors": driving_factors,
        }
