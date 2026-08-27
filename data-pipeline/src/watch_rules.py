"""Pure Sentinel-2 watch rules for upper-Gulf NDCI overlays.

Data source: Sentinel-2-derived NDCI, trend, and SST inputs supplied by callers.
Limitation: these rules do not fetch, authenticate, or validate source data;
they classify only the values provided to them.
"""

from collections import defaultdict
from datetime import date

import numpy as np

LEVEL_NONE = 0
LEVEL_ELEVATED = 1
LEVEL_WATCH = 2
LEVEL_WARNING = 3


def qa60_clear(values):
    qa = np.asarray(values, dtype=np.uint16)
    return ((qa & (1 << 10)) == 0) & ((qa & (1 << 11)) == 0)


def classify_levels(
    *, z, slope_per_day, trend_observations, current_sst, seasonal_sst,
    elevated_z: float, warning_z: float, min_trend_observations: int,
):
    z_arr = np.asarray(z, dtype=float)
    slope = np.asarray(slope_per_day, dtype=float)
    count = np.asarray(trend_observations, dtype=float)
    current = np.asarray(current_sst, dtype=float)
    seasonal = np.asarray(seasonal_sst, dtype=float)
    if not (z_arr.shape == slope.shape == count.shape == current.shape == seasonal.shape):
        raise ValueError("all classification inputs must have identical shapes")

    result = np.zeros(z_arr.shape, dtype=np.uint8)
    elevated = np.isfinite(z_arr) & (z_arr >= elevated_z)
    rising = np.isfinite(slope) & (count >= min_trend_observations) & (slope > 0)
    sst_above = np.isfinite(current) & np.isfinite(seasonal) & (current > seasonal)
    result[elevated] = LEVEL_ELEVATED
    result[elevated & rising] = LEVEL_WATCH
    result[(z_arr >= warning_z) & rising & sst_above] = LEVEL_WARNING
    return result


def linear_daily_trend(observations):
    by_date = defaultdict(list)
    for date_string, value in observations:
        if value is not None and np.isfinite(float(value)):
            by_date[date.fromisoformat(date_string)].append(float(value))
    daily = [(day, float(np.median(values))) for day, values in sorted(by_date.items())]
    serialized = [{"date": day.isoformat(), "ndci": value} for day, value in daily]
    if len(daily) < 2:
        return {"daily_values": serialized, "distinct_dates": len(daily), "slope_per_day": None, "rising": False}
    x = np.array([(day - daily[0][0]).days for day, _ in daily], dtype=float)
    y = np.array([value for _, value in daily], dtype=float)
    slope = float(np.polyfit(x, y, 1)[0])
    return {"daily_values": serialized, "distinct_dates": len(daily), "slope_per_day": slope, "rising": slope > 0}
