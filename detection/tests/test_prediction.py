"""
Unit tests for the pure, GEE-free logic in `src/prediction.py`: trend/
acceleration math over a synthetic `history` list, the config-driven rule
condition parser (`_eval_condition`), and rule evaluation (`evaluate_rules`).

This is the safety-relevant layer (CLAUDE.md's rule-based risk
escalation) -- in particular, `evaluate_rules` must never let missing
data (`anomaly_z=None`) escalate risk. See
`test_evaluate_rules_missing_anomaly_z_never_escalates_to_warning` below.

Nothing here calls `detect()` or `risk_level()` (both make real GEE
calls via `_data_pipeline.py`) -- only the pure helper functions are
exercised, with hand-built `history`/`ctx` arguments. Importing
`src.prediction` itself is safe without GEE auth or credentials: it only
imports `_data_pipeline` for names at module load time (no
`ee.Initialize()` call happens on import).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.prediction import (  # noqa: E402
    _eval_condition,
    _linear_slope,
    compute_acceleration,
    compute_trend,
    evaluate_rules,
    load_config,
)


# --------------------------------------------------------------------------
# _linear_slope
# --------------------------------------------------------------------------


def test_linear_slope_normal_case():
    points = [(0.0, 1.0), (1.0, 2.0), (2.0, 3.0)]
    assert _linear_slope(points) == pytest.approx(1.0)


def test_linear_slope_fewer_than_two_points_returns_none():
    assert _linear_slope([]) is None
    assert _linear_slope([(0.0, 1.0)]) is None


def test_linear_slope_zero_x_variance_returns_none():
    # All points share the same x -- a vertical "slope" is undefined,
    # not a divide-by-zero crash.
    points = [(1.0, 5.0), (1.0, 7.0), (1.0, 9.0)]
    assert _linear_slope(points) is None


# --------------------------------------------------------------------------
# compute_trend -- synthetic MODIS chlor_a history, no GEE call (history
# is passed in directly as a plain list of dicts).
# --------------------------------------------------------------------------


def test_compute_trend_rising():
    history = [
        {"date": "2024-01-01", "chlor_a": 1.0},
        {"date": "2024-01-08", "chlor_a": 2.0},
        {"date": "2024-01-15", "chlor_a": 3.0},
    ]
    result = compute_trend(history, "2024-01-15", window_days=14)
    assert result["n"] == 3
    assert result["rising"] is True
    assert result["slope_per_day"] == pytest.approx(1.0 / 7.0)


def test_compute_trend_falling():
    history = [
        {"date": "2024-01-01", "chlor_a": 3.0},
        {"date": "2024-01-08", "chlor_a": 2.0},
        {"date": "2024-01-15", "chlor_a": 1.0},
    ]
    result = compute_trend(history, "2024-01-15", window_days=14)
    assert result["n"] == 3
    assert result["rising"] is False
    assert result["slope_per_day"] == pytest.approx(-1.0 / 7.0)


def test_compute_trend_fewer_than_two_points_in_window_is_none():
    history = [
        {"date": "2024-01-15", "chlor_a": 5.0},  # in window
        {"date": "2023-01-01", "chlor_a": 1.0},  # far outside the 14-day window
    ]
    result = compute_trend(history, "2024-01-15", window_days=14)
    assert result["n"] == 1
    assert result["slope_per_day"] is None
    assert result["rising"] is None


def test_compute_trend_windowing_excludes_past_and_future_points():
    history = [
        {"date": "2023-12-01", "chlor_a": 99.0},  # 46 days before target -> excluded
        {"date": "2024-01-01", "chlor_a": 1.0},  # exactly window_days=14 before -> included (boundary)
        {"date": "2024-01-10", "chlor_a": 2.0},  # inside window -> included
        {"date": "2024-01-15", "chlor_a": 3.0},  # target date itself -> included
        {"date": "2024-01-20", "chlor_a": 100.0},  # after target date -> excluded
    ]
    result = compute_trend(history, "2024-01-15", window_days=14)
    assert result["n"] == 3
    assert result["rising"] is True


def test_compute_trend_uses_real_gap_fewer_points_than_window_implies():
    # window_days=14 but the "archive" only actually has 2 observations
    # in that stretch (a cloud-heavy gap) -- compute_trend must use those
    # 2 real points, not fabricate/interpolate the missing days.
    history = [
        {"date": "2024-01-02", "chlor_a": 1.0},
        {"date": "2024-01-15", "chlor_a": 4.0},
    ]
    result = compute_trend(history, "2024-01-15", window_days=14)
    assert result["n"] == 2
    assert result["rising"] is True
    # x=-13 -> y=1.0, x=0 -> y=4.0
    assert result["slope_per_day"] == pytest.approx(3.0 / 13.0)


# --------------------------------------------------------------------------
# compute_acceleration -- short-window slope vs. long-window slope.
# --------------------------------------------------------------------------


def test_compute_acceleration_detects_rapid_onset():
    # Flat for the first 8 days (2024-01-01..08), then a steep, perfectly
    # linear rise for the last 7 days (2024-01-08..15). The 7-day short
    # window sees only the steep rise (slope 1.0/day); the 14-day long
    # window sees the flat stretch too, so its slope is smaller.
    history = [
        {"date": "2024-01-01", "chlor_a": 1.0},
        {"date": "2024-01-02", "chlor_a": 1.0},
        {"date": "2024-01-03", "chlor_a": 1.0},
        {"date": "2024-01-04", "chlor_a": 1.0},
        {"date": "2024-01-05", "chlor_a": 1.0},
        {"date": "2024-01-06", "chlor_a": 1.0},
        {"date": "2024-01-07", "chlor_a": 1.0},
        {"date": "2024-01-08", "chlor_a": 1.0},
        {"date": "2024-01-09", "chlor_a": 2.0},
        {"date": "2024-01-10", "chlor_a": 3.0},
        {"date": "2024-01-11", "chlor_a": 4.0},
        {"date": "2024-01-12", "chlor_a": 5.0},
        {"date": "2024-01-13", "chlor_a": 6.0},
        {"date": "2024-01-14", "chlor_a": 7.0},
        {"date": "2024-01-15", "chlor_a": 8.0},
    ]
    result = compute_acceleration(history, "2024-01-15", short_window_days=7, long_window_days=14)

    assert result["short_trend"]["slope_per_day"] == pytest.approx(1.0)
    assert result["long_trend"]["slope_per_day"] < result["short_trend"]["slope_per_day"]
    assert result["acceleration"] is not None
    assert result["acceleration"] > 0


def test_compute_acceleration_none_when_either_trend_is_none():
    # Only one real point total -> both short and long trend slopes are
    # None -> acceleration must also be None, not a crash on `None - None`.
    history = [{"date": "2024-01-15", "chlor_a": 5.0}]
    result = compute_acceleration(history, "2024-01-15", short_window_days=7, long_window_days=14)
    assert result["short_trend"]["slope_per_day"] is None
    assert result["long_trend"]["slope_per_day"] is None
    assert result["acceleration"] is None


# --------------------------------------------------------------------------
# _eval_condition -- the config-file-safety boundary. Every operator,
# true/false literals, None-context-value safety, and malformed-input
# guards.
# --------------------------------------------------------------------------

_CTX = {"anomaly_z": 2.0, "trend_14d_rising": True, "sst_anomaly": 0.5}


def test_eval_condition_ge_operator():
    assert _eval_condition("anomaly_z >= 2.0", _CTX) is True
    assert _eval_condition("anomaly_z >= 2.1", _CTX) is False


def test_eval_condition_le_operator():
    assert _eval_condition("anomaly_z <= 2.0", _CTX) is True
    assert _eval_condition("anomaly_z <= 1.9", _CTX) is False


def test_eval_condition_gt_operator():
    assert _eval_condition("anomaly_z > 1.9", _CTX) is True
    assert _eval_condition("anomaly_z > 2.0", _CTX) is False


def test_eval_condition_lt_operator():
    assert _eval_condition("anomaly_z < 2.1", _CTX) is True
    assert _eval_condition("anomaly_z < 2.0", _CTX) is False


def test_eval_condition_eq_operator():
    assert _eval_condition("sst_anomaly == 0.5", _CTX) is True
    assert _eval_condition("sst_anomaly == 0.6", _CTX) is False


def test_eval_condition_true_false_literal_parsing():
    assert _eval_condition("trend_14d_rising == true", _CTX) is True
    assert _eval_condition("trend_14d_rising == false", _CTX) is False

    ctx_not_rising = {**_CTX, "trend_14d_rising": False}
    assert _eval_condition("trend_14d_rising == false", ctx_not_rising) is True
    assert _eval_condition("trend_14d_rising == true", ctx_not_rising) is False


@pytest.mark.parametrize("op", [">=", "<=", ">", "<", "=="])
def test_eval_condition_none_context_value_returns_false_for_every_operator(op):
    ctx_missing = {"anomaly_z": None, "trend_14d_rising": True, "sst_anomaly": 0.5}
    assert _eval_condition(f"anomaly_z {op} 1.5", ctx_missing) is False


def test_eval_condition_none_context_value_returns_false_even_for_boolean_literal():
    ctx_missing = {"anomaly_z": 2.0, "trend_14d_rising": None, "sst_anomaly": 0.5}
    assert _eval_condition("trend_14d_rising == true", ctx_missing) is False
    assert _eval_condition("trend_14d_rising == false", ctx_missing) is False


def test_eval_condition_unknown_variable_raises_value_error():
    with pytest.raises(ValueError):
        _eval_condition("not_a_real_variable >= 1.0", _CTX)


def test_eval_condition_malformed_expression_too_few_tokens_raises():
    with pytest.raises(ValueError):
        _eval_condition("anomaly_z>=1.5", _CTX)


def test_eval_condition_malformed_expression_too_many_tokens_raises():
    with pytest.raises(ValueError):
        _eval_condition("anomaly_z >= 1.5 extra", _CTX)


# --------------------------------------------------------------------------
# evaluate_rules -- against the REAL escalation_rules shape loaded from
# detection/src/config.yaml (not hand-copied), so this is pinned to what
# actually ships.
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def escalation_rules():
    config = load_config()
    return config["escalation_rules"]


def test_evaluate_rules_normal_when_nothing_triggers(escalation_rules):
    ctx = {"anomaly_z": 0.5, "trend_14d_rising": False, "sst_anomaly": -1.0}
    result = evaluate_rules(ctx, escalation_rules)
    assert result["level"] == "normal"
    assert result["triggered_rules"] == []


def test_evaluate_rules_elevated_only(escalation_rules):
    # anomaly_z satisfies "elevated" (>= 1.5) but not "watch" (needs
    # trend_14d_rising == true too) or "warning".
    ctx = {"anomaly_z": 1.6, "trend_14d_rising": False, "sst_anomaly": -1.0}
    result = evaluate_rules(ctx, escalation_rules)
    assert result["triggered_rules"] == ["elevated"]
    assert result["level"] == "elevated"


def test_evaluate_rules_elevated_and_watch_wins_watch(escalation_rules):
    # anomaly_z satisfies elevated and watch (>= 1.5, rising) but not
    # warning (needs >= 2.0 and sst_anomaly > 0).
    ctx = {"anomaly_z": 1.6, "trend_14d_rising": True, "sst_anomaly": -1.0}
    result = evaluate_rules(ctx, escalation_rules)
    assert result["triggered_rules"] == ["elevated", "watch"]
    assert result["level"] == "watch"


def test_evaluate_rules_all_three_wins_warning(escalation_rules):
    ctx = {"anomaly_z": 2.5, "trend_14d_rising": True, "sst_anomaly": 0.5}
    result = evaluate_rules(ctx, escalation_rules)
    assert result["triggered_rules"] == ["elevated", "watch", "warning"]
    assert result["level"] == "warning"


def test_evaluate_rules_missing_anomaly_z_never_escalates_to_warning(escalation_rules):
    """THE safety-critical case: anomaly_z is missing (None) while every
    other variable is set to a value that would otherwise satisfy
    `warning`'s non-anomaly_z conditions. Missing data must resolve to
    'normal', never silently escalate risk.
    """
    ctx = {"anomaly_z": None, "trend_14d_rising": True, "sst_anomaly": 0.5}
    result = evaluate_rules(ctx, escalation_rules)
    assert result["level"] == "normal"
    assert result["triggered_rules"] == []
