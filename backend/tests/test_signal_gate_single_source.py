"""The signal-anomaly activation floors have one definition.

detection/src/signal_anomaly.py owns MIN_INDEPENDENT_DATES and
MAX_OBSERVATION_AGE_DAYS. backend's activation gate must read those same
objects through the detection bridge, not carry its own literals, so the
two can never silently disagree. The floors themselves (>= 30 dates,
<= 14 days) must never loosen.
"""

from __future__ import annotations

import pytest

from src import scientific_status


def _active(min_dates: int, max_age: int) -> dict:
    return {
        "risk_evaluation": {"active": True},
        "signal_anomaly": {
            "status": "active",
            "minimum_independent_dates": min_dates,
            "max_observation_age_days": max_age,
            "location_specific": True,
            "season_specific": True,
            "history_before_target_only": True,
            "baseline_version": "v1",
            "preprocessing_signature": "sig",
        },
    }


def _use(monkeypatch, cfg: dict) -> None:
    monkeypatch.setattr(scientific_status.bridge, "load_prediction_config", lambda: cfg)


def test_bridge_exposes_the_detection_constants_not_copies():
    bridge = scientific_status.bridge
    module = bridge._signal_anomaly
    assert module.__file__.endswith("detection/src/signal_anomaly.py")
    assert bridge.SIGNAL_ANOMALY_MIN_INDEPENDENT_DATES == module.MIN_INDEPENDENT_DATES
    assert bridge.SIGNAL_ANOMALY_MAX_OBSERVATION_AGE_DAYS == module.MAX_OBSERVATION_AGE_DAYS
    # Today's floors; this test fails if anyone loosens them.
    assert module.MIN_INDEPENDENT_DATES >= 30
    assert module.MAX_OBSERVATION_AGE_DAYS <= 14


def test_gate_follows_a_stricter_detection_minimum(monkeypatch):
    _use(monkeypatch, _active(30, 14))
    assert scientific_status.signal_anomaly_active() is True
    monkeypatch.setattr(scientific_status.bridge, "SIGNAL_ANOMALY_MIN_INDEPENDENT_DATES", 40)
    assert scientific_status.signal_anomaly_active() is False
    assert scientific_status.risk_evaluation_active() is False


def test_gate_follows_a_stricter_detection_age_ceiling(monkeypatch):
    _use(monkeypatch, _active(30, 14))
    monkeypatch.setattr(scientific_status.bridge, "SIGNAL_ANOMALY_MAX_OBSERVATION_AGE_DAYS", 7)
    assert scientific_status.signal_anomaly_active() is False


@pytest.mark.parametrize("min_dates,max_age", [(29, 14), (30, 15), (30, -1)])
def test_gate_never_opens_below_todays_floors(monkeypatch, min_dates, max_age):
    _use(monkeypatch, _active(min_dates, max_age))
    assert scientific_status.signal_anomaly_active() is False
    assert scientific_status.risk_evaluation_active() is False
