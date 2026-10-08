"""Read-only activation gates for unvalidated scientific outputs.

Data source: detection/src/config.yaml, read through the detection bridge.
Limitation: the gates only check that the config *declares* the provenance
fields of an active baseline; they do not validate that such a baseline
actually exists or is scientifically sound.
"""

from __future__ import annotations

import copy
import os

from . import _detection as bridge

_REAL_LOADER = bridge.load_prediction_config
_config_cache: tuple[tuple[int, int, int, str], dict] | None = None


def _load_config() -> dict:
    """Parsed detection config, re-read when the file's mtime, size or inode changes.

    The gates run on every /risk-map, /summary and /alerts request; parsing
    the YAML each time was blocking file I/O on the event loop. A replaced
    loader (tests) or an unreadable path falls through uncached.
    """
    global _config_cache
    if bridge.load_prediction_config is not _REAL_LOADER:
        return bridge.load_prediction_config()
    path = getattr(bridge._prediction, "CONFIG_PATH", None)
    try:
        st = os.stat(path)
    except (TypeError, OSError):
        return _REAL_LOADER()
    key = (st.st_mtime_ns, st.st_size, st.st_ino, str(path))
    if _config_cache is None or _config_cache[0] != key:
        _config_cache = (key, _REAL_LOADER())
    # A copy, so a caller can never mutate the cached gate inputs.
    return copy.deepcopy(_config_cache[1])


def _signal_anomaly_active(config: dict) -> bool:
    """Validate the minimum provenance declarations for an active baseline."""
    signal = config.get("signal_anomaly", {})
    try:
        minimum_dates = int(signal.get("minimum_independent_dates", 0))
        max_age_days = int(signal.get("max_observation_age_days", 99))
    except (TypeError, ValueError):
        return False
    return bool(
        signal.get("status") == "active"
        and minimum_dates >= 30
        and 0 <= max_age_days <= 14
        and signal.get("location_specific") is True
        and signal.get("season_specific") is True
        and signal.get("history_before_target_only") is True
        and isinstance(signal.get("baseline_version"), str)
        and bool(signal["baseline_version"].strip())
        and isinstance(signal.get("preprocessing_signature"), str)
        and bool(signal["preprocessing_signature"].strip())
    )


def risk_evaluation_active() -> bool:
    """True only for calibrated risk backed by a compatible active baseline."""
    config = _load_config()
    return (
        config.get("risk_evaluation", {}).get("active") is True
        and _signal_anomaly_active(config)
    )


def signal_anomaly_active() -> bool:
    """True only after the Sentinel-2 baseline pipeline is activated."""
    config = _load_config()
    return _signal_anomaly_active(config)
