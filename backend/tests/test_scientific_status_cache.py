"""scientific_status gates parse the detection config once per file state.

No GEE and no real config is touched: CONFIG_PATH is pointed at a tmp file.
"""

from __future__ import annotations

import os

import yaml

from src import scientific_status


def _config(active: bool) -> dict:
    return {
        "risk_evaluation": {"active": active},
        "signal_anomaly": {
            "status": "active" if active else "inactive",
            "minimum_independent_dates": 30,
            "max_observation_age_days": 14,
            "location_specific": True,
            "season_specific": True,
            "history_before_target_only": True,
            "baseline_version": "v1",
            "preprocessing_signature": "sig",
        },
    }


def _write(path, active: bool, mtime_ns: int, pad: str = "") -> None:
    path.write_text(yaml.safe_dump(_config(active)) + pad)
    os.utime(path, ns=(mtime_ns, mtime_ns))


def _setup(tmp_path, monkeypatch, active=False):
    cfg = tmp_path / "config.yaml"
    _write(cfg, active, 1_000_000_000)
    monkeypatch.setattr(scientific_status.bridge._prediction, "CONFIG_PATH", cfg)
    monkeypatch.setattr(scientific_status, "_config_cache", None)
    return cfg


def test_gates_reparse_only_when_the_config_changes_and_values_flip(tmp_path, monkeypatch):
    cfg = _setup(tmp_path, monkeypatch)
    parses = []
    real = yaml.safe_load
    monkeypatch.setattr(yaml, "safe_load", lambda f: parses.append(1) or real(f))

    for _ in range(3):
        assert scientific_status.risk_evaluation_active() is False
        assert scientific_status.signal_anomaly_active() is False
    assert len(parses) == 1

    _write(cfg, True, 2_000_000_000)
    assert scientific_status.signal_anomaly_active() is True
    assert scientific_status.risk_evaluation_active() is True
    assert len(parses) == 2

    # The safety-critical direction: active -> inactive must be seen at once.
    _write(cfg, False, 3_000_000_000)
    assert scientific_status.signal_anomaly_active() is False
    assert scientific_status.risk_evaluation_active() is False
    assert len(parses) == 3


def test_same_mtime_edit_with_a_different_size_is_still_picked_up(tmp_path, monkeypatch):
    cfg = _setup(tmp_path, monkeypatch, active=True)
    assert scientific_status.risk_evaluation_active() is True

    _write(cfg, False, 1_000_000_000, pad="# edited\n")
    assert scientific_status.risk_evaluation_active() is False


def test_callers_cannot_mutate_the_cached_config(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, active=True)
    scientific_status._load_config()["risk_evaluation"]["active"] = False
    assert scientific_status.risk_evaluation_active() is True
