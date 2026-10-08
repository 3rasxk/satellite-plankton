"""Provisional Sentinel-2 signal-anomaly calculation boundary.

This module is intentionally not connected to ``prediction.risk_level``. The
repository does not yet persist a location- and season-specific Sentinel-2
history with a preprocessing signature, so production responses must keep
``signal_anomaly_level`` null. These pure helpers define and test the minimum
scientific compatibility checks a future baseline builder must pass; they do
not claim bloom detection or biological risk.

The statistic is robust_z = (current NDCI - median NDCI) / (1.4826 * MAD).
Its z=2 and z=3 boundaries are provisional engineering thresholds, not
validated Noctiluca thresholds.
"""

from __future__ import annotations

from datetime import date
import math
from pathlib import Path
from statistics import median
from typing import Any

import yaml

CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"

NORMAL = "normal"
WATCH = "watch"
HIGH_ANOMALY = "high"
NO_ASSESSMENT_TH = "ไม่มีข้อมูลประเมิน"

_LABELS_TH = {
    NORMAL: "ปกติ",
    WATCH: "เฝ้าระวัง",
    HIGH_ANOMALY: "ผิดปกติสูง",
}

MIN_INDEPENDENT_DATES = 30
MAX_OBSERVATION_AGE_DAYS = 14
MAD_SCALE = 1.4826
WATCH_AT_Z = 2.0
HIGH_AT_Z = 3.0
NDCI_MIN = -1.0
NDCI_MAX = 1.0


def _config(config: dict | None = None) -> dict:
    if config is None:
        with open(CONFIG_PATH) as handle:
            config = yaml.safe_load(handle)
    cfg = config.get("signal_anomaly", config)
    try:
        minimum_dates = int(cfg["minimum_independent_dates"])
        max_age = int(cfg["max_observation_age_days"])
        mad_scale = float(cfg["mad_scale"])
        watch_at = float(cfg["watch_at_z"])
        high_at = float(cfg["high_at_z"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("signal_anomaly configuration is incomplete or invalid") from exc
    if minimum_dates < MIN_INDEPENDENT_DATES:
        raise ValueError("minimum_independent_dates must be at least 30")
    if max_age < 0 or max_age > MAX_OBSERVATION_AGE_DAYS:
        raise ValueError("max_observation_age_days must remain between 0 and 14")
    if not math.isclose(mad_scale, MAD_SCALE, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("mad_scale must remain 1.4826 for the documented robust z-score")
    if watch_at != WATCH_AT_Z or high_at != HIGH_AT_Z:
        raise ValueError("provisional robust-z boundaries must remain 2 and 3")
    return cfg


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _finite_ndci(value: Any) -> float | None:
    number = _finite(value)
    if number is None or number < NDCI_MIN or number > NDCI_MAX:
        return None
    return number


def classify_robust_z(robust_z: float | None, config: dict | None = None) -> str | None:
    """Classify a valid robust z-score using provisional config thresholds."""
    value = _finite(robust_z)
    if value is None:
        return None
    cfg = _config(config)
    if value < float(cfg["watch_at_z"]):
        return NORMAL
    if value < float(cfg["high_at_z"]):
        return WATCH
    return HIGH_ANOMALY


def _no_assessment(reason: str, independent_date_count: int = 0) -> dict:
    return {
        "level": None,
        "label_th": NO_ASSESSMENT_TH,
        "robust_z": None,
        "median_ndci": None,
        "mad": None,
        "independent_date_count": independent_date_count,
        "reason": reason,
    }


def assess_signal_anomaly(
    *,
    current_ndci: float | None,
    actual_date: str | None,
    target_date: str,
    history: list[dict],
    location_id: str,
    season_key: str,
    preprocessing_signature: str,
    config: dict | None = None,
) -> dict:
    """Assess one observation only against scientifically compatible history.

    ``history`` rows are first scoped to the exact location, seasonal bucket,
    and preprocessing signature. Only finite observations acquired strictly
    before the current observation are eligible; this also excludes every
    observation after the target date. Multiple samples from one acquisition
    date are reduced to one daily median before the configurable independent-
    date minimum is checked.

    This function is a validation/calculation boundary for future use. The
    current production data model cannot supply this history and does not call
    it.
    """
    cfg = _config(config)
    current = _finite_ndci(current_ndci)
    if current is None or not actual_date:
        return _no_assessment("missing_or_invalid_observation")

    try:
        observed_on = date.fromisoformat(actual_date)
        target_on = date.fromisoformat(target_date)
    except (TypeError, ValueError):
        return _no_assessment("missing_or_invalid_observation")

    age_days = (target_on - observed_on).days
    if age_days < 0:
        return _no_assessment("imagery_after_target_date")
    if age_days > int(cfg["max_observation_age_days"]):
        return _no_assessment("imagery_older_than_14_days")
    if not location_id or not season_key or not preprocessing_signature:
        return _no_assessment("incompatible_baseline_scope")

    scoped_rows = [
        row for row in history
        if row.get("location_id") == location_id and row.get("season_key") == season_key
    ]
    compatible_rows = [
        row for row in scoped_rows
        if row.get("preprocessing_signature") == preprocessing_signature
    ]
    if scoped_rows and not compatible_rows:
        return _no_assessment("incompatible_preprocessing")

    values_by_date: dict[date, list[float]] = {}
    for row in compatible_rows:
        try:
            acquired_on = date.fromisoformat(row["acquisition_date"])
        except (KeyError, TypeError, ValueError):
            continue
        # Strictly earlier than the observation is stronger than merely
        # earlier than the target and prevents same-scene or future leakage.
        if acquired_on >= observed_on or acquired_on > target_on:
            continue
        value = _finite_ndci(row.get("ndci"))
        if value is not None:
            values_by_date.setdefault(acquired_on, []).append(value)

    daily_values = [median(values) for values in values_by_date.values()]
    date_count = len(daily_values)
    if date_count < int(cfg["minimum_independent_dates"]):
        return _no_assessment("insufficient_independent_dates", date_count)

    baseline_median = median(daily_values)
    mad = median(abs(value - baseline_median) for value in daily_values)
    if mad == 0:
        result = _no_assessment("zero_mad", date_count)
        result.update({"median_ndci": baseline_median, "mad": mad})
        return result

    robust_z = (current - baseline_median) / (float(cfg["mad_scale"]) * mad)
    level = classify_robust_z(robust_z, cfg)
    return {
        "level": level,
        "label_th": _LABELS_TH[level],
        "robust_z": robust_z,
        "median_ndci": baseline_median,
        "mad": mad,
        "independent_date_count": date_count,
        "reason": None,
    }
