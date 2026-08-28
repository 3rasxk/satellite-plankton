"""
Dual-Model Marine Bloom Ensemble Inference Service.
Integrates Random Forest (Precision Validator) and XGBoost (Recall Screener)
via soft-voting dual consensus.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple, Union

import joblib
import numpy as np
import pandas as pd

FEATURE_COLUMNS = [
    "chlor_a",
    "sst",
    "nflh",
    "poc",
    "chlor_a_anomaly",
    "month_sin",
    "month_cos",
]


def _resolve_model_path(path_input: str, default_filename: str) -> Path:
    """Robustly resolves model artifact path across different execution working directories."""
    p = Path(path_input)
    if p.exists():
        return p

    candidates = [
        Path(path_input),
        Path("backend") / path_input,
        Path("backend/models") / default_filename,
        Path("models") / default_filename,
        Path(__file__).resolve().parent / "models" / default_filename,
        Path(__file__).resolve().parent.parent / "backend" / "models" / default_filename,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    return p


class DualModelBloomEnsemble:
    """
    Production-ready dual-model soft-voting ensemble for marine bloom detection.

    Combines:
    1. XGBoost: High-Recall Screener (Screener score, early detection)
    2. Random Forest: High-Precision Validator (False-alarm suppression)
    """

    def __init__(
        self,
        rf_path: str = "backend/models/random_forest_bloom.joblib",
        xgb_path: str = "backend/models/xgboost_bloom.joblib",
        default_threshold: float = 0.35,
    ):
        """Loads and initializes both persisted model artifacts."""
        self.rf_path = _resolve_model_path(rf_path, "random_forest_bloom.joblib")
        self.xgb_path = _resolve_model_path(xgb_path, "xgboost_bloom.joblib")
        self.default_threshold = float(default_threshold)

        if not self.rf_path.exists():
            raise FileNotFoundError(f"Random Forest model artifact not found at: {self.rf_path}")
        if not self.xgb_path.exists():
            raise FileNotFoundError(f"XGBoost model artifact not found at: {self.xgb_path}")

        self.rf_pipeline = joblib.load(self.rf_path)
        self.xgb_pipeline = joblib.load(self.xgb_path)
        self.feature_names = list(FEATURE_COLUMNS)

    def _prepare_array(
        self,
        features: Union[Dict[str, float], pd.DataFrame, pd.Series, np.ndarray, List[Dict[str, float]]],
    ) -> Tuple[np.ndarray, pd.DataFrame]:
        """Validates schema integrity and constructs ordered 2D float32 numpy array and DataFrame."""
        if isinstance(features, dict):
            missing = [col for col in self.feature_names if col not in features]
            if missing:
                raise ValueError(
                    f"Invalid feature schema: missing required column(s) {missing}. "
                    f"Expected exactly: {self.feature_names}"
                )
            arr = np.array([[features[col] for col in self.feature_names]], dtype=np.float32)
            df = None

        elif isinstance(features, pd.Series):
            missing = [col for col in self.feature_names if col not in features.index]
            if missing:
                raise ValueError(
                    f"Invalid feature schema: missing required column(s) {missing}. "
                    f"Expected exactly: {self.feature_names}"
                )
            arr = np.array([[features[col] for col in self.feature_names]], dtype=np.float32)
            df = pd.DataFrame([features.to_dict()])[self.feature_names]

        elif isinstance(features, pd.DataFrame):
            missing = [col for col in self.feature_names if col not in features.columns]
            if missing:
                raise ValueError(
                    f"Invalid feature schema: missing required column(s) {missing}. "
                    f"Expected exactly: {self.feature_names}"
                )
            df = features[self.feature_names].copy()
            arr = df.to_numpy(dtype=np.float32)

        elif isinstance(features, (np.ndarray, list)):
            arr = np.array(features, dtype=np.float32)
            if arr.ndim == 1:
                if len(arr) != len(self.feature_names):
                    raise ValueError(
                        f"Expected {len(self.feature_names)} features, but received {len(arr)} values."
                    )
                arr = arr.reshape(1, -1)
            elif arr.ndim == 2:
                if arr.shape[1] != len(self.feature_names):
                    raise ValueError(
                        f"Expected {len(self.feature_names)} columns in 2D array, but got {arr.shape[1]}."
                    )
            else:
                raise ValueError("Array input must be 1D or 2D.")
            df = pd.DataFrame(arr, columns=self.feature_names)
        else:
            raise TypeError(f"Unsupported features input type: {type(features)}")

        # Fast numpy physical bounds check
        physical_bounds = {
            "chlor_a": (0.0, 500.0, "mg/m³"),
            "sst": (0.0, 50.0, "°C"),
            "nflh": (-5.0, 10.0, "mW·cm⁻²·µm⁻¹·sr⁻¹"),
            "poc": (0.0, 10000.0, "mg/m³"),
            "chlor_a_anomaly": (-10.0, 20.0, "z-score"),
            "month_sin": (-1.01, 1.01, "cyclical"),
            "month_cos": (-1.01, 1.01, "cyclical"),
        }
        for i, (col, (min_v, max_v, unit)) in enumerate(physical_bounds.items()):
            col_vals = arr[:, i]
            valid_mask = ~np.isnan(col_vals)
            if np.any(valid_mask):
                valid_vals = col_vals[valid_mask]
                bad_mask = (valid_vals < min_v) | (valid_vals > max_v)
                if np.any(bad_mask):
                    bad_val = float(valid_vals[bad_mask][0])
                    raise ValueError(
                        f"Out of physical bounds for feature '{col}': {bad_val} {unit} "
                        f"(expected valid physical range: {min_v} to {max_v} {unit})."
                    )

        return arr, df

    def _predict_rf_fast(self, X_imputed: np.ndarray) -> np.ndarray:
        """Direct C-level decision tree traversal bypassing parallel dispatch latency."""
        model = self.rf_pipeline.named_steps["model"]
        X_c = np.ascontiguousarray(X_imputed, dtype=np.float32)
        n_classes = model.n_classes_
        all_proba = np.zeros((X_c.shape[0], n_classes), dtype=np.float64)
        for tree in model.estimators_:
            prob = tree.tree_.predict(X_c)
            all_proba += prob[:, :n_classes]
        all_proba /= len(model.estimators_)
        return all_proba

    def predict_observation(
        self,
        features: Union[Dict[str, float], pd.DataFrame, pd.Series, np.ndarray],
        threshold: float | None = None,
    ) -> Dict[str, Any]:
        """
        Executes dual inference and returns ensemble soft-voting metrics.

        Output schema:
        {
            "bloom_detected": bool,
            "ensemble_confidence": float,  # Average probability (0.000 to 1.000)
            "risk_tier": str,              # "NORMAL" (<0.35), "WATCH" (0.35 - 0.65), "WARNING" (>=0.65)
            "model_breakdown": {
                "xgb_probability": float,  # Screener score (Sensitivity focused)
                "rf_probability": float    # Validator score (Precision focused)
            },
            "decision_threshold": float
        }
        """
        arr, df = self._prepare_array(features)
        decision_threshold = float(threshold if threshold is not None else self.default_threshold)

        # Impute missing values using fast numpy array
        imputer = self.rf_pipeline.named_steps["imputer"]
        X_imp = np.ascontiguousarray(imputer.transform(arr), dtype=np.float32)

        # Fast thread-safe prediction
        rf_prob = float(self._predict_rf_fast(X_imp)[:, 1][0])
        xgb_model = self.xgb_pipeline.named_steps["model"]
        xgb_prob = float(xgb_model.predict_proba(X_imp)[:, 1][0])

        # Soft voting joint confidence
        ensemble_confidence = float((xgb_prob + rf_prob) / 2.0)
        bloom_detected = bool(ensemble_confidence >= decision_threshold)

        # Operational Risk Tier Mapping
        if ensemble_confidence >= 0.65:
            risk_tier = "WARNING"
        elif ensemble_confidence >= 0.35:
            risk_tier = "WATCH"
        else:
            risk_tier = "NORMAL"

        return {
            "bloom_detected": bloom_detected,
            "ensemble_confidence": round(ensemble_confidence, 4),
            "risk_tier": risk_tier,
            "model_breakdown": {
                "xgb_probability": round(xgb_prob, 4),
                "rf_probability": round(rf_prob, 4),
            },
            "decision_threshold": decision_threshold,
        }

    def predict_batch(
        self,
        features: Union[pd.DataFrame, np.ndarray, List[Dict[str, float]]],
        threshold: float | None = None,
    ) -> List[Dict[str, Any]]:
        """Executes batch inference efficiently across multiple observations."""
        arr, df = self._prepare_array(features)
        decision_threshold = float(threshold if threshold is not None else self.default_threshold)

        imputer = self.rf_pipeline.named_steps["imputer"]
        X_imp = np.ascontiguousarray(imputer.transform(df), dtype=np.float32)

        rf_probs = self._predict_rf_fast(X_imp)[:, 1]
        xgb_probs = self.xgb_pipeline.predict_proba(df)[:, 1]
        ensemble_confs = (xgb_probs + rf_probs) / 2.0

        results = []
        for i in range(len(df)):
            e_conf = float(ensemble_confs[i])
            if e_conf >= 0.65:
                tier = "WARNING"
            elif e_conf >= 0.35:
                tier = "WATCH"
            else:
                tier = "NORMAL"

            results.append({
                "bloom_detected": bool(e_conf >= decision_threshold),
                "ensemble_confidence": round(e_conf, 4),
                "risk_tier": tier,
                "model_breakdown": {
                    "xgb_probability": round(float(xgb_probs[i]), 4),
                    "rf_probability": round(float(rf_probs[i]), 4),
                },
                "decision_threshold": decision_threshold,
            })
        return results
