#!/usr/bin/env python3
"""
Dual-Model Marine Bloom Ensemble Pipeline (Random Forest + XGBoost)
Training, evaluation, artifact export, and metadata persistence.
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import math
from pathlib import Path
from typing import Tuple

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import Pipeline
from xgboost import XGBClassifier

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("train_dual_models")

FEATURE_COLUMNS = [
    "chlor_a",
    "sst",
    "nflh",
    "poc",
    "chlor_a_anomaly",
    "month_sin",
    "month_cos",
]


def find_dataset_path(custom_path: str | None = None) -> Path:
    """Finds the ugot_modis dataset across common repository locations."""
    if custom_path and Path(custom_path).exists():
        return Path(custom_path)

    candidates = [
        Path("train-model/data/dataset_train/ugot_modis_dataset.parquet"),
        Path("../train-model/data/dataset_train/ugot_modis_dataset.parquet"),
        Path(__file__).resolve().parent.parent / "train-model" / "data" / "dataset_train" / "ugot_modis_dataset.parquet",
        Path(__file__).resolve().parent.parent / "train-model" / "data" / "dataset_train" / "ugot_modis_dataset.csv",
        Path(__file__).resolve().parent / "data" / "ugot_modis_dataset.parquet",
    ]

    for c in candidates:
        if c.exists():
            return c

    raise FileNotFoundError(
        "Could not find training dataset ugot_modis_dataset.parquet. "
        "Please provide --data-path <path>."
    )


def load_and_preprocess_data(data_path: Path) -> Tuple[pd.DataFrame, pd.Series, pd.Series]:
    """Loads dataset and ensures feature schema and cyclical month features."""
    logger.info(f"Loading training data from {data_path}...")
    if str(data_path).endswith(".parquet"):
        df = pd.read_parquet(data_path)
    else:
        df = pd.read_csv(data_path)

    # Ensure cyclical month features exist
    if "month_sin" not in df.columns or "month_cos" not in df.columns:
        if "month" in df.columns:
            month = df["month"]
        elif "date" in df.columns:
            month = pd.to_datetime(df["date"]).dt.month
        else:
            raise ValueError("Dataset must contain 'month', 'date', or ('month_sin', 'month_cos').")
        df["month_sin"] = month.apply(lambda m: math.sin(2 * math.pi * m / 12))
        df["month_cos"] = month.apply(lambda m: math.cos(2 * math.pi * m / 12))

    # Ensure grouping variable
    if "site_key" not in df.columns:
        if "station_id" in df.columns:
            df["site_key"] = df["station_id"]
        elif "lat" in df.columns and "lng" in df.columns:
            df["site_key"] = df["lat"].round(1).astype(str) + "_" + df["lng"].round(1).astype(str)
        else:
            df["site_key"] = "site_default"

    # Filter required features and label
    X = df[FEATURE_COLUMNS].copy()
    y = df["label"].astype(int).copy()
    groups = df["site_key"].astype(str).copy()

    # Drop rows where label is missing or all satellite features are NaN
    satellite_bands = ["chlor_a", "sst", "nflh", "poc", "chlor_a_anomaly"]
    valid_mask = y.notna() & ~X[satellite_bands].isna().all(axis=1)
    X = X.loc[valid_mask]
    y = y.loc[valid_mask]
    groups = groups.loc[valid_mask]

    logger.info(f"Loaded {len(X):,} valid records across {groups.nunique()} stations. Class 1 (bloom): {y.sum():,} ({y.mean()*100:.2f}%)")
    return X, y, groups


def build_xgboost_pipeline(scale_pos_weight: float) -> Pipeline:
    """Builds the primary screening XGBoost classifier pipeline with high recall."""
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        (
            "model",
            XGBClassifier(
                n_estimators=200,
                max_depth=5,
                learning_rate=0.08,
                reg_lambda=1.0,
                scale_pos_weight=scale_pos_weight,
                objective="binary:logistic",
                eval_metric="logloss",
                random_state=42,
                n_jobs=-1,
            ),
        ),
    ])


def build_random_forest_pipeline() -> Pipeline:
    """Builds the precision-validating Random Forest classifier pipeline."""
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        (
            "model",
            RandomForestClassifier(
                n_estimators=300,
                max_depth=12,
                min_samples_split=5,
                class_weight="balanced_subsample",
                random_state=42,
                n_jobs=-1,
            ),
        ),
    ])


def evaluate_model(pipeline: Pipeline, X_test: pd.DataFrame, y_test: pd.Series, model_name: str) -> dict:
    """Computes comprehensive evaluation metrics on held-out test split."""
    y_pred = pipeline.predict(X_test)
    y_prob = pipeline.predict_proba(X_test)[:, 1]

    cm = confusion_matrix(y_test, y_pred)
    tn, fp, fn, tp = cm.ravel()

    prec = float(precision_score(y_test, y_pred, pos_label=1, zero_division=0))
    rec = float(recall_score(y_test, y_pred, pos_label=1, zero_division=0))
    f1 = float(f1_score(y_test, y_pred, pos_label=1, zero_division=0))
    acc = float(accuracy_score(y_test, y_pred))

    metrics = {
        "model_name": model_name,
        "precision_class_1": prec,
        "recall_class_1": rec,
        "f1_class_1": f1,
        "accuracy": acc,
        "confusion_matrix": {
            "TN": int(tn),
            "FP": int(fp),
            "FN": int(fn),
            "TP": int(tp),
        },
    }

    logger.info(
        f"=== {model_name} Test Results ===\n"
        f"  Precision (Class 1): {prec*100:.2f}%\n"
        f"  Recall    (Class 1): {rec*100:.2f}%\n"
        f"  F1-Score  (Class 1): {f1*100:.2f}%\n"
        f"  Accuracy:            {acc*100:.2f}%\n"
        f"  Confusion Matrix:    TN={tn:,}, FP={fp:,}, FN={fn:,}, TP={tp:,}"
    )
    return metrics


def train_and_export_ensemble(data_path: Path | None = None, output_dir: Path | None = None):
    """Executes 70/30 Grouped Stratified split, trains both pipelines, evaluates, and exports artifacts."""
    if output_dir is None:
        output_dir = Path(__file__).resolve().parent / "models"
    output_dir.mkdir(parents=True, exist_ok=True)

    dataset_file = find_dataset_path(str(data_path) if data_path else None)
    X, y, groups = load_and_preprocess_data(dataset_file)

    # 70/30 Grouped Split (Zero Spatial Leakage across station locations)
    gss = GroupShuffleSplit(n_splits=1, train_size=0.70, random_state=42)
    train_idx, test_idx = next(gss.split(X, y, groups=groups))

    X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
    y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]

    logger.info(
        f"Data split: Train={len(X_train):,} rows ({y_train.sum():,} blooms), "
        f"Test={len(X_test):,} rows ({y_test.sum():,} blooms) across {groups.iloc[test_idx].nunique()} held-out stations."
    )

    # Compute scale_pos_weight for XGBoost
    n_neg = int((y_train == 0).sum())
    n_pos = int((y_train == 1).sum())
    scale_pos_weight = n_neg / max(1, n_pos)
    logger.info(f"XGBoost scale_pos_weight: {scale_pos_weight:.2f}")

    # 1. Train & Evaluate XGBoost Screener
    xgb_pipeline = build_xgboost_pipeline(scale_pos_weight=scale_pos_weight)
    logger.info("Fitting XGBoost Classifier pipeline...")
    xgb_pipeline.fit(X_train, y_train)
    xgb_metrics = evaluate_model(xgb_pipeline, X_test, y_test, "XGBoost (High-Recall Screener)")

    # 2. Train & Evaluate Random Forest Validator
    rf_pipeline = build_random_forest_pipeline()
    logger.info("Fitting Random Forest Classifier pipeline...")
    rf_pipeline.fit(X_train, y_train)
    rf_metrics = evaluate_model(rf_pipeline, X_test, y_test, "Random Forest (High-Precision Validator)")

    # 3. Evaluate Dual Soft-Voting Ensemble
    xgb_test_probs = xgb_pipeline.predict_proba(X_test)[:, 1]
    rf_test_probs = rf_pipeline.predict_proba(X_test)[:, 1]
    ensemble_probs = (xgb_test_probs + rf_test_probs) / 2.0
    ensemble_preds = (ensemble_probs >= 0.35).astype(int)

    cm_ens = confusion_matrix(y_test, ensemble_preds)
    tn_e, fp_e, fn_e, tp_e = cm_ens.ravel()
    ensemble_metrics = {
        "model_name": "Dual-Model Soft-Voting Ensemble",
        "decision_threshold": 0.35,
        "precision_class_1": float(precision_score(y_test, ensemble_preds, pos_label=1, zero_division=0)),
        "recall_class_1": float(recall_score(y_test, ensemble_preds, pos_label=1, zero_division=0)),
        "f1_class_1": float(f1_score(y_test, ensemble_preds, pos_label=1, zero_division=0)),
        "accuracy": float(accuracy_score(y_test, ensemble_preds)),
        "confusion_matrix": {"TN": int(tn_e), "FP": int(fp_e), "FN": int(fn_e), "TP": int(tp_e)},
    }
    logger.info(
        f"=== Dual Ensemble Test Results (Threshold=0.35) ===\n"
        f"  Precision: {ensemble_metrics['precision_class_1']*100:.2f}%\n"
        f"  Recall:    {ensemble_metrics['recall_class_1']*100:.2f}%\n"
        f"  F1-Score:  {ensemble_metrics['f1_class_1']*100:.2f}%\n"
        f"  Accuracy:  {ensemble_metrics['accuracy']*100:.2f}%"
    )

    # 4. Export Artifacts
    rf_path = output_dir / "random_forest_bloom.joblib"
    xgb_path = output_dir / "xgboost_bloom.joblib"
    meta_path = output_dir / "ensemble_metadata.json"

    logger.info(f"Saving Random Forest artifact to {rf_path} (compress=3)...")
    joblib.dump(rf_pipeline, rf_path, compress=3)

    logger.info(f"Saving XGBoost artifact to {xgb_path} (compress=3)...")
    joblib.dump(xgb_pipeline, xgb_path, compress=3)

    metadata = {
        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "feature_schema": FEATURE_COLUMNS,
        "decision_thresholds": {
            "NORMAL": "< 0.35",
            "WATCH": "0.35 - 0.65",
            "WARNING": ">= 0.65",
            "default_operational_threshold": 0.35,
        },
        "performance": {
            "xgboost": xgb_metrics,
            "random_forest": rf_metrics,
            "ensemble": ensemble_metrics,
        },
    }

    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)
    logger.info(f"Saved ensemble metadata to {meta_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train and export Dual-Model Bloom Detection Ensemble.")
    parser.add_argument("--data-path", type=str, default=None, help="Path to ugot_modis_dataset parquet/csv.")
    parser.add_argument("--output-dir", type=str, default=None, help="Destination directory for joblib artifacts.")
    args = parser.parse_args()

    train_and_export_ensemble(
        data_path=Path(args.data_path) if args.data_path else None,
        output_dir=Path(args.output_dir) if args.output_dir else None,
    )
