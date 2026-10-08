"""Pure regression tests for the provisional satellite-signal contract.

These tests do not activate anomaly output. They pin the validation boundary a
future baseline builder must satisfy before ``signal_anomaly_level`` can be
populated: matching location/season/preprocessing, independent acquisition
dates before the current observation, freshness, minimum history, and nonzero
MAD.
"""

from datetime import date, timedelta
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.signal_anomaly import (  # noqa: E402
    HIGH_ANOMALY,
    NO_ASSESSMENT_TH,
    NORMAL,
    WATCH,
    assess_signal_anomaly,
    classify_robust_z,
)


def _history(values, *, start=date(2024, 1, 1), future=0):
    rows = [
        {
            "acquisition_date": (start + timedelta(days=i)).isoformat(),
            "ndci": value,
            "location_id": "cell-1",
            "season_key": "dry",
            "preprocessing_signature": "s2-sr-harmonized:v1",
        }
        for i, value in enumerate(values)
    ]
    rows.extend(
        {
            "acquisition_date": (date(2025, 2, 1) + timedelta(days=i)).isoformat(),
            "ndci": 999.0,
            "location_id": "cell-1",
            "season_key": "dry",
            "preprocessing_signature": "s2-sr-harmonized:v1",
        }
        for i in range(future)
    )
    return rows


def _valid_values(count=30):
    """Plausible NDCI observations spanning -0.15 through 0.14."""
    return [-0.15 + 0.01 * i for i in range(count)]


@pytest.mark.parametrize(
    ("z", "expected"),
    [(1.999, NORMAL), (2.0, WATCH), (2.999, WATCH), (3.0, HIGH_ANOMALY)],
)
def test_provisional_robust_z_boundaries(z, expected):
    assert classify_robust_z(z) == expected


def test_consistent_history_computes_the_documented_robust_z():
    values = _valid_values()
    result = assess_signal_anomaly(
        current_ndci=0.145,
        actual_date="2024-02-01",
        target_date="2024-02-01",
        history=_history(values),
        location_id="cell-1",
        season_key="dry",
        preprocessing_signature="s2-sr-harmonized:v1",
    )
    expected = (0.145 - (-0.005)) / (1.4826 * 0.075)
    assert result["robust_z"] == pytest.approx(expected)
    assert result["independent_date_count"] == 30
    assert result["level"] == NORMAL


def test_fewer_than_30_independent_dates_returns_no_assessment():
    result = assess_signal_anomaly(
        current_ndci=0.2, actual_date="2024-02-01", target_date="2024-02-01",
        history=_history(_valid_values(29)), location_id="cell-1", season_key="dry",
        preprocessing_signature="s2-sr-harmonized:v1",
    )
    assert result["level"] is None
    assert result["label_th"] == NO_ASSESSMENT_TH
    assert result["reason"] == "insufficient_independent_dates"


def test_zero_mad_returns_no_assessment():
    result = assess_signal_anomaly(
        current_ndci=0.2, actual_date="2024-02-01", target_date="2024-02-01",
        history=_history([0.1] * 30), location_id="cell-1", season_key="dry",
        preprocessing_signature="s2-sr-harmonized:v1",
    )
    assert result["level"] is None
    assert result["reason"] == "zero_mad"


@pytest.mark.parametrize(
    ("current_ndci", "actual_date", "target_date", "reason"),
    [
        (None, "2024-02-01", "2024-02-01", "missing_or_invalid_observation"),
        (0.2, None, "2024-02-01", "missing_or_invalid_observation"),
        (0.2, "2024-01-01", "2024-02-01", "imagery_older_than_14_days"),
        (0.2, "2024-02-02", "2024-02-01", "imagery_after_target_date"),
    ],
)
def test_missing_stale_or_future_current_observation_returns_no_assessment(
    current_ndci, actual_date, target_date, reason,
):
    result = assess_signal_anomaly(
        current_ndci=current_ndci, actual_date=actual_date, target_date=target_date,
        history=_history(_valid_values()), location_id="cell-1", season_key="dry",
        preprocessing_signature="s2-sr-harmonized:v1",
    )
    assert result["level"] is None
    assert result["reason"] == reason


def test_future_history_never_satisfies_minimum_or_changes_baseline():
    result = assess_signal_anomaly(
        current_ndci=0.2,
        actual_date="2024-01-30",
        target_date="2024-01-30",
        history=_history(_valid_values(29), future=40),
        location_id="cell-1",
        season_key="dry",
        preprocessing_signature="s2-sr-harmonized:v1",
    )
    assert result["level"] is None
    assert result["independent_date_count"] == 29
    assert result["reason"] == "insufficient_independent_dates"


def test_mismatched_preprocessing_returns_no_assessment():
    result = assess_signal_anomaly(
        current_ndci=0.2, actual_date="2024-02-01", target_date="2024-02-01",
        history=_history(_valid_values()), location_id="cell-1", season_key="dry",
        preprocessing_signature="different-pipeline",
    )
    assert result["level"] is None
    assert result["reason"] == "incompatible_preprocessing"


@pytest.mark.parametrize(("location_id", "season_key"), [("cell-2", "dry"), ("cell-1", "wet")])
def test_history_from_another_location_or_season_cannot_enter_baseline(location_id, season_key):
    result = assess_signal_anomaly(
        current_ndci=0.2, actual_date="2024-02-01", target_date="2024-02-01",
        history=_history(_valid_values()), location_id=location_id, season_key=season_key,
        preprocessing_signature="s2-sr-harmonized:v1",
    )
    assert result["level"] is None
    assert result["independent_date_count"] == 0
    assert result["reason"] == "insufficient_independent_dates"


def test_minimum_independent_dates_can_be_made_more_conservative():
    custom = {
        "minimum_independent_dates": 31,
        "max_observation_age_days": 14,
        "mad_scale": 1.4826,
        "watch_at_z": 2.0,
        "high_at_z": 3.0,
    }
    result = assess_signal_anomaly(
        current_ndci=0.16, actual_date="2024-02-01", target_date="2024-02-01",
        history=_history(_valid_values()), location_id="cell-1", season_key="dry",
        preprocessing_signature="s2-sr-harmonized:v1", config=custom,
    )
    assert result["independent_date_count"] == 30
    assert result["reason"] == "insufficient_independent_dates"


def test_minimum_independent_dates_cannot_be_weakened_below_30():
    custom = {
        "minimum_independent_dates": 29,
        "max_observation_age_days": 14,
        "mad_scale": 1.4826,
        "watch_at_z": 2.0,
        "high_at_z": 3.0,
    }
    with pytest.raises(ValueError, match="at least 30"):
        classify_robust_z(2.0, custom)


@pytest.mark.parametrize("current_ndci", [-1.01, 1.01, float("inf")])
def test_impossible_or_non_finite_current_ndci_returns_no_assessment(current_ndci):
    result = assess_signal_anomaly(
        current_ndci=current_ndci,
        actual_date="2024-02-01",
        target_date="2024-02-01",
        history=_history(_valid_values()),
        location_id="cell-1",
        season_key="dry",
        preprocessing_signature="s2-sr-harmonized:v1",
    )
    assert result["level"] is None
    assert result["reason"] == "missing_or_invalid_observation"


def test_impossible_historical_ndci_is_excluded_from_the_baseline():
    values = _valid_values(29) + [1.01]
    result = assess_signal_anomaly(
        current_ndci=0.2,
        actual_date="2024-02-01",
        target_date="2024-02-01",
        history=_history(values),
        location_id="cell-1",
        season_key="dry",
        preprocessing_signature="s2-sr-harmonized:v1",
    )
    assert result["level"] is None
    assert result["independent_date_count"] == 29
    assert result["reason"] == "insufficient_independent_dates"
