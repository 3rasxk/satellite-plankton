"""Read-only activation gates for unvalidated scientific outputs.

Data sources: detection/src/config.yaml, read through the detection bridge;
and, only when ``config.BASELINE_MODE`` is exactly ``"test"``, the newest
TEST baseline artefact under ``backend/data/baselines/`` (read and validated
by ``baseline_store``).

Two independent ways can open the Sentinel-2 signal-anomaly gate, both
through the same ``_signal_anomaly_active`` predicate and the same floors
(detection/src/signal_anomaly.py's constants):
  * the config path -- config.yaml's own ``signal_anomaly`` declaration
    (unchanged; inactive in this repository);
  * the TEST path -- a baseline artefact that ``validate_manifest`` accepts
    against the live preprocessing signature and today's date, and whose
    ``signal_anomaly`` declaration passes the predicate.
Risk evaluation is opened by the config path only; no baseline artefact can
open it.

Limitations: the config path only checks that the config *declares* the
provenance fields of an active baseline; it does not prove such a baseline
exists. The TEST path proves the artefact exists, parses, and declares
floors no weaker than detection's -- not that the baseline is calibrated:
a TEST baseline is provisional and has never been checked against recorded
bloom events, so an anomaly it supports is a statistical statement about a
site's own seasonal record, not a bloom detection or a risk.
"""

from __future__ import annotations

import copy
import logging
import os
from statistics import median

from . import _detection as bridge
from . import baseline_store
from . import config as backend_config

logger = logging.getLogger(__name__)

_REAL_LOADER = bridge.load_prediction_config
_config_cache: tuple[tuple[int, int, int, str], dict] | None = None
# Last baseline-failure warning logged, so a persistent fault is logged once
# rather than on every request that consults the gate.
_last_baseline_warning: str | None = None


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
    """Validate the minimum provenance declarations for an active baseline.

    The date-count floor and age ceiling are detection/src/signal_anomaly.py's
    constants, read through the bridge -- not backend literals.
    """
    signal = config.get("signal_anomaly", {})
    try:
        minimum_dates = int(signal.get("minimum_independent_dates", 0))
        max_age_days = int(signal.get("max_observation_age_days", 99))
    except (TypeError, ValueError):
        return False
    return bool(
        signal.get("status") == "active"
        and minimum_dates >= bridge.SIGNAL_ANOMALY_MIN_INDEPENDENT_DATES
        and 0 <= max_age_days <= bridge.SIGNAL_ANOMALY_MAX_OBSERVATION_AGE_DAYS
        and signal.get("location_specific") is True
        and signal.get("season_specific") is True
        and signal.get("history_before_target_only") is True
        and isinstance(signal.get("baseline_version"), str)
        and bool(signal["baseline_version"].strip())
        and isinstance(signal.get("preprocessing_signature"), str)
        and bool(signal["preprocessing_signature"].strip())
    )


def risk_evaluation_active() -> bool:
    """True only for calibrated risk backed by a compatible active baseline.

    Config path only: BASELINE_MODE and the TEST baseline never enter here.
    """
    config = _load_config()
    return (
        config.get("risk_evaluation", {}).get("active") is True
        and _signal_anomaly_active(config)
    )


def _warn_baseline(message: str, *, exc_info: bool = False) -> None:
    global _last_baseline_warning
    if message != _last_baseline_warning:
        logger.warning(message, exc_info=exc_info)
        _last_baseline_warning = message


def _invalid(reason: str) -> dict:
    return {"mode": "test", "valid": False, "kind": "test", "reason": reason}


def _baseline_state() -> tuple[dict, dict | None]:
    """``(baseline_status() payload, the valid manifest's declaration or None)``.

    Never raises. Mode off returns before any file is touched.
    """
    global _last_baseline_warning
    try:
        if backend_config.BASELINE_MODE != "test":
            return {"mode": "off"}, None
        manifest = baseline_store.active_manifest()
        if manifest is None:
            _warn_baseline(
                "BASELINE_MODE=test but no complete baseline artefact under "
                f"{baseline_store.BASELINE_ROOT}; signal anomaly stays off (no_artifact)"
            )
            return _invalid("no_artifact"), None
        declaration = manifest["signal_anomaly"]
        # validate_manifest checks floors and thresholds; the gate predicate
        # also needs location/season/history-before-target declarations. A
        # declaration it rejects does not activate, so it is not "valid".
        if not _signal_anomaly_active({"signal_anomaly": declaration}):
            raise bridge.baseline_logic.BaselineInvalid("inactive_declaration")
        status = {
            "mode": "test",
            "valid": True,
            "kind": manifest["baseline_kind"],
            "version": manifest["baseline_version"],
            "built_at": manifest["built_at"],
            "history_start": manifest["history_start"],
            "history_end": manifest["history_end"],
            "season_rule": manifest["season_rule"],
            "min_independent_dates": declaration["minimum_independent_dates"],
            "median_independent_dates": median(
                info["n_dates"] for info in manifest["locations"].values()
            ),
            "preprocessing_signature": manifest["preprocessing_signature"],
            "base_rates": manifest["self_check"]["total"],
        }
    except bridge.baseline_logic.BaselineInvalid as exc:
        _warn_baseline(f"TEST baseline refused ({exc}); signal anomaly stays off")
        return _invalid(str(exc)), None
    except Exception as exc:  # noqa: BLE001 -- the gate must fail closed, never raise
        _warn_baseline(
            f"TEST baseline unreadable ({type(exc).__name__}: {exc}); signal anomaly stays off",
            exc_info=True,
        )
        return _invalid("unreadable"), None
    _last_baseline_warning = None
    return status, declaration


def baseline_status() -> dict:
    """Describe the TEST baseline in force; never raises.

    ``{"mode": "off"}`` unless ``config.BASELINE_MODE`` (read now) is exactly
    ``"test"``. In test mode, either the valid description (version, dates,
    season rule, declared and median date counts, preprocessing signature,
    ``base_rates`` = the manifest's self-check totals) or
    ``{"mode": "test", "valid": False, "kind": "test", "reason": ...}`` with
    ``no_artifact``, a ``BaselineInvalid`` reason, or ``unreadable``.
    Each call returns a fresh dict.
    """
    return _baseline_state()[0]


def signal_anomaly_active() -> bool:
    """True only after the Sentinel-2 baseline pipeline is activated.

    The config path is unchanged. In addition, with BASELINE_MODE == "test",
    true when the TEST baseline is valid and its own declaration passes the
    same predicate. The TEST path never raises.
    """
    config = _load_config()
    if _signal_anomaly_active(config):
        return True
    # _baseline_state() hands back a declaration only when the artefact
    # validated AND that declaration passed _signal_anomaly_active (inside
    # its own try, so this path cannot raise).
    status, declaration = _baseline_state()
    return status.get("valid") is True and declaration is not None
