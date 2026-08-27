"""Pure temporal and anomaly primitives for the upper-Gulf NDCI watch overlay.

Data sources: date inputs and caller-provided NDCI arrays; no Earth Engine
calls are made here. Limitations: these helpers only construct seasonal
windows and apply numerical masking; they do not fetch imagery or make a
scientific validation claim.
"""

from datetime import date, timedelta
from typing import Any

import numpy as np

NUMERICAL_STD_EPSILON = 1e-6


def _prior_year_anchor(target: date, years_back: int) -> date:
    try:
        return target.replace(year=target.year - years_back)
    except ValueError:
        return target.replace(year=target.year - years_back, day=28)


def seasonal_windows(
    target_date: str, *, baseline_years: int, window_days: int
) -> list[tuple[str, str]]:
    target = date.fromisoformat(target_date)
    windows = []
    for years_back in range(1, baseline_years + 1):
        anchor = _prior_year_anchor(target, years_back)
        start = anchor - timedelta(days=window_days)
        end_exclusive = anchor + timedelta(days=window_days + 1)
        windows.append((start.isoformat(), end_exclusive.isoformat()))
    return windows


def compute_watch_mask(
    latest: Any,
    seasonal_mean: Any,
    seasonal_std: Any,
    observation_count: Any,
    *,
    threshold_z: float,
    min_observations: int,
    std_epsilon: float = NUMERICAL_STD_EPSILON,
) -> np.ndarray:
    latest_arr = np.asarray(latest, dtype=float)
    mean_arr = np.asarray(seasonal_mean, dtype=float)
    std_arr = np.asarray(seasonal_std, dtype=float)
    count_arr = np.asarray(observation_count, dtype=float)
    if not (latest_arr.shape == mean_arr.shape == std_arr.shape == count_arr.shape):
        raise ValueError("latest, mean, std, and count must have identical shapes")
    valid = (
        np.isfinite(latest_arr)
        & np.isfinite(mean_arr)
        & np.isfinite(std_arr)
        & (std_arr > std_epsilon)
        & (count_arr >= min_observations)
    )
    z = np.full(latest_arr.shape, np.nan, dtype=float)
    z[valid] = (latest_arr[valid] - mean_arr[valid]) / std_arr[valid]
    return valid & (z >= threshold_z)
