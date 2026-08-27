import numpy as np

from src.watch_rules import (
    LEVEL_ELEVATED,
    LEVEL_NONE,
    LEVEL_WARNING,
    LEVEL_WATCH,
    classify_levels,
    linear_daily_trend,
    qa60_clear,
)


def test_classify_levels_uses_highest_proven_rule_and_safe_downgrades():
    result = classify_levels(
        z=[1.49, 1.50, 1.80, 2.20, 2.20, np.nan],
        slope_per_day=[0.1, np.nan, 0.02, 0.03, -0.01, 0.1],
        trend_observations=[3, 0, 2, 2, 3, 3],
        current_sst=[30, 30, np.nan, 30, 30, 30],
        seasonal_sst=[29, 29, np.nan, 29, 29, 29],
        elevated_z=1.5,
        warning_z=2.0,
        min_trend_observations=2,
    )
    assert result.tolist() == [
        LEVEL_NONE,
        LEVEL_ELEVATED,
        LEVEL_WATCH,
        LEVEL_WARNING,
        LEVEL_ELEVATED,
        LEVEL_NONE,
    ]


def test_linear_daily_trend_deduplicates_dates_with_a_median():
    result = linear_daily_trend([
        ("2026-08-14", 0.10),
        ("2026-08-14", 0.30),
        ("2026-08-20", 0.40),
    ])
    assert result["distinct_dates"] == 2
    assert result["daily_values"] == [
        {"date": "2026-08-14", "ndci": 0.20},
        {"date": "2026-08-20", "ndci": 0.40},
    ]
    assert result["slope_per_day"] > 0
    assert result["rising"] is True


def test_linear_daily_trend_requires_two_dates():
    result = linear_daily_trend([("2026-08-20", 0.40)])
    assert result == {
        "daily_values": [{"date": "2026-08-20", "ndci": 0.40}],
        "distinct_dates": 1,
        "slope_per_day": None,
        "rising": False,
    }


def test_qa60_clear_rejects_cloud_and_cirrus_bits():
    values = np.array([0, 1 << 10, 1 << 11, (1 << 10) | (1 << 11)])
    assert qa60_clear(values).tolist() == [True, False, False, False]
