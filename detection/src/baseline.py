"""TEST seasonal baseline logic for the Sentinel-2 NDCI signal anomaly.

Data source: history rows (``{"acquisition_date": "YYYY-MM-DD", "ndci": float}``
plus optional extras) supplied by a builder such as
``data-pipeline/src/history.py``. This module touches no network, no GEE and no
files; it only scopes those rows, calls the existing robust-z calculation in
``signal_anomaly.assess_signal_anomaly`` and builds/validates the manifest that
describes a baseline.

What it provides:
  * a fixed seasonal rule (calendar month, target month +/- 1, cyclic);
  * a preprocessing signature so history made with different settings is never
    mixed;
  * ``assess_site`` -- one observation against that location's own earlier
    history in the same seasonal window (strictly earlier dates only);
  * ``self_check`` -- a replay of the history against itself, so a human can see
    how often the statistic flags the baseline's own past;
  * ``build_manifest`` / ``validate_manifest`` -- a fail-closed description of a
    baseline, which can never declare a floor weaker than ``signal_anomaly``'s.

Limitations (read before showing any output of this module):
  * The output is a statistical anomaly of one location against its OWN
    seasonal record. It is not a bloom-detection claim and not a biological
    risk claim, and it is not a forecast.
  * The baseline is a TEST baseline (``baseline_kind == "test"``). It has not
    been calibrated against recorded bloom events, so what the statistic flags
    has not been checked against what happened in the water.
  * The robust-z boundaries (2 and 3) are provisional engineering thresholds
    owned by ``signal_anomaly.py``, not validated Noctiluca thresholds.
  * Satellite pixels (~10 m) respond to water colour only; small or dispersed
    blooms can be missed, and turbid or shallow water can raise NDCI with no
    bloom present.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from signal_anomaly import (  # noqa: E402
    HIGH_AT_Z,
    MAD_SCALE,
    MAX_OBSERVATION_AGE_DAYS,
    MIN_INDEPENDENT_DATES,
    WATCH_AT_Z,
    _config,
    assess_signal_anomaly,
)

SEASON_RULE = "calendar-month window, target month +/- 1 (cyclic)"
BASELINE_KIND = "test"

_REQUIRED_TOP_LEVEL = (
    "baseline_kind",
    "baseline_version",
    "built_at",
    "history_start",
    "history_end",
    "season_rule",
    "preprocessing_signature",
    "signal_anomaly",
)


# --------------------------------------------------------------------------
# Season scope and preprocessing identity
# --------------------------------------------------------------------------


def season_months(month: int) -> tuple[int, int, int]:
    """Return ``(month - 1, month, month + 1)`` cyclic in 1..12."""
    if not 1 <= month <= 12:
        raise ValueError(f"month must be 1..12, got {month!r}")
    return ((month - 2) % 12 + 1, month, month % 12 + 1)


def season_key(month: int) -> str:
    """Seasonal bucket label for a target month (ASCII, safe in keys/filenames)."""
    if not 1 <= month <= 12:
        raise ValueError(f"month must be 1..12, got {month!r}")
    return f"m{month:02d}+-1"


def preprocessing_signature(params: dict) -> str:
    """First 16 hex chars of SHA-256 over the canonical JSON of ``params``.

    Key order does not matter; any changed value changes the signature.
    """
    canonical = json.dumps(params, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()[:16]


def version_for(built_on: date, signature: str) -> str:
    """Human-readable TEST baseline version, e.g. ``TEST-20261009-abcd1234``."""
    return f"TEST-{built_on:%Y%m%d}-{signature[:8]}"


def _month_of(iso_date: object) -> int | None:
    try:
        return date.fromisoformat(str(iso_date)).month
    except (TypeError, ValueError):
        return None


def scoped_history(
    rows: list[dict],
    location_id: str,
    target_month: int,
    preprocessing_signature: str,
) -> list[dict]:
    """Rows acquired in ``season_months(target_month)``, tagged with the scope.

    Returns new dicts carrying ``location_id``, ``season_key`` and
    ``preprocessing_signature``; the input rows are not mutated. Rows whose
    ``acquisition_date`` cannot be parsed are dropped.
    """
    months = season_months(target_month)
    key = season_key(target_month)
    scoped: list[dict] = []
    for row in rows:
        if _month_of(row.get("acquisition_date")) in months:
            scoped.append(
                {
                    **row,
                    "location_id": location_id,
                    "season_key": key,
                    "preprocessing_signature": preprocessing_signature,
                }
            )
    return scoped


# --------------------------------------------------------------------------
# Assessment and self-check
# --------------------------------------------------------------------------


def assess_site(
    rows: list[dict],
    *,
    location_id: str,
    current_ndci: float | None,
    actual_date: str | None,
    target_date: str,
    preprocessing_signature: str,
    config: dict | None = None,
) -> dict:
    """Assess one observation against the site's own seasonal history.

    The seasonal window is chosen from the month of ``target_date``. Exactly
    what ``signal_anomaly.assess_signal_anomaly`` returns is returned here,
    unchanged, and its exceptions are not caught. Only rows acquired strictly
    before ``actual_date`` are used by that function, so later rows in ``rows``
    are invisible.

    A ``target_date`` that is not an ISO date has no month, so no history can
    be scoped; the underlying call then reports ``missing_or_invalid_observation``.
    """
    target_month = _month_of(target_date)
    if target_month is None:
        history: list[dict] = []
        key = ""
    else:
        history = scoped_history(rows, location_id, target_month, preprocessing_signature)
        key = season_key(target_month)
    return assess_signal_anomaly(
        current_ndci=current_ndci,
        actual_date=actual_date,
        target_date=target_date,
        history=history,
        location_id=location_id,
        season_key=key,
        preprocessing_signature=preprocessing_signature,
        config=config,
    )


def _empty_counts() -> dict:
    return {"assessed": 0, "watch": 0, "high": 0, "no_assessment": 0, "reasons": {}}


def _tally(counts: dict, result: dict) -> None:
    if result["level"] is None:
        counts["no_assessment"] += 1
        reason = result.get("reason") or "unknown"
        counts["reasons"][reason] = counts["reasons"].get(reason, 0) + 1
        return
    counts["assessed"] += 1
    if result["level"] == "watch":
        counts["watch"] += 1
    elif result["level"] == "high":
        counts["high"] += 1


def self_check(
    rows: list[dict],
    *,
    location_id: str,
    preprocessing_signature: str,
    config: dict | None = None,
) -> dict:
    """Replay a location's history against itself, one row at a time.

    Every row is assessed through ``assess_site`` with ``target_date`` and
    ``actual_date`` both set to the row's own date, so only rows strictly
    earlier than it, inside its seasonal window, can contribute. Each row is
    counted once, in the bucket of its own calendar month
    (``by_season[season_key(month)]``), and once in ``total``.

    ``assessed`` counts rows whose ``level`` is not None (normal, watch or
    high); ``no_assessment`` counts the rest, grouped by ``reasons``. A row whose
    date cannot be parsed has no month: it is counted in ``total`` only, with
    reason ``invalid_acquisition_date``. Thus
    ``total["assessed"] + total["no_assessment"] == len(rows)`` always holds.

    This describes how the statistic behaves on the baseline's own past. It is
    not a measure of detection accuracy.
    """
    cfg = _config(config)  # resolve once instead of re-reading config.yaml per row
    by_season = {season_key(month): _empty_counts() for month in range(1, 13)}
    total = _empty_counts()

    for row in rows:
        month = _month_of(row.get("acquisition_date"))
        if month is None:
            result = {"level": None, "reason": "invalid_acquisition_date"}
        else:
            result = assess_site(
                rows,
                location_id=location_id,
                current_ndci=row.get("ndci"),
                actual_date=row["acquisition_date"],
                target_date=row["acquisition_date"],
                preprocessing_signature=preprocessing_signature,
                config=cfg,
            )
            _tally(by_season[season_key(month)], result)
        _tally(total, result)

    for counts in (*by_season.values(), total):
        counts["reasons"] = dict(sorted(counts["reasons"].items()))
    return {"by_season": by_season, "total": total}


# --------------------------------------------------------------------------
# Manifest
# --------------------------------------------------------------------------


def build_manifest(
    *,
    baseline_version: str,
    built_at: str,
    history_start: str,
    history_end: str,
    preprocessing_signature: str,
    preprocessing_params: dict,
    locations: dict[str, dict],
    self_check: dict,
    builder_git_sha: str | None,
) -> dict:
    """Describe a TEST baseline; ``signal_anomaly`` is the activation declaration.

    ``locations[id]`` is ``{"n_dates", "min_season_dates", "first", "last"}``.
    The declared ``minimum_independent_dates`` is the smallest
    ``min_season_dates`` over all locations (the weakest season anywhere), so
    the declaration is never stronger than the thinnest history it covers.
    """
    if not locations:
        raise ValueError("a baseline manifest needs at least one location")
    weakest = min(int(info["min_season_dates"]) for info in locations.values())
    return {
        "baseline_kind": BASELINE_KIND,
        "baseline_version": baseline_version,
        "built_at": built_at,
        "history_start": history_start,
        "history_end": history_end,
        "season_rule": SEASON_RULE,
        "preprocessing_signature": preprocessing_signature,
        "preprocessing_params": copy.deepcopy(preprocessing_params),
        "locations": copy.deepcopy(locations),
        "self_check": copy.deepcopy(self_check),
        "builder_git_sha": builder_git_sha,
        "signal_anomaly": {
            "status": "active",
            "minimum_independent_dates": weakest,
            "max_observation_age_days": MAX_OBSERVATION_AGE_DAYS,
            "location_specific": True,
            "season_specific": True,
            "history_before_target_only": True,
            "baseline_version": baseline_version,
            "preprocessing_signature": preprocessing_signature,
            "mad_scale": MAD_SCALE,
            "watch_at_z": WATCH_AT_Z,
            "high_at_z": HIGH_AT_Z,
        },
    }


class BaselineInvalid(ValueError):
    """A baseline manifest must not be used; ``str(exc)`` is the reason code."""


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_manifest(manifest: dict, *, live_signature: str, today: date) -> None:
    """Raise ``BaselineInvalid`` unless the manifest is safe to activate.

    Checks run in this order and the first failure wins:
      1. required top-level keys           -> ``missing_field:<name>``
      2. ``baseline_kind == "test"``       -> ``not_test_kind``
      3. signature equals ``live_signature`` -> ``signature_mismatch``
      4. ``history_end`` not after today   -> ``history_in_future``
      5. floors in ``signal_anomaly``      -> ``below_floor``

    A ``history_end`` that is not an ISO date is reported as
    ``missing_field:history_end`` (unusable). Missing or non-numeric floor
    values are ``missing_field:signal_anomaly.<name>`` and ``below_floor``
    respectively, so a hand-edited manifest can never loosen the floors owned
    by ``signal_anomaly.py``.
    """
    for name in _REQUIRED_TOP_LEVEL:
        if name not in manifest or manifest[name] is None:
            raise BaselineInvalid(f"missing_field:{name}")

    if manifest["baseline_kind"] != BASELINE_KIND:
        raise BaselineInvalid("not_test_kind")

    if manifest["preprocessing_signature"] != live_signature:
        raise BaselineInvalid("signature_mismatch")

    try:
        history_end = date.fromisoformat(str(manifest["history_end"]))
    except ValueError:
        raise BaselineInvalid("missing_field:history_end") from None
    if history_end > today:
        raise BaselineInvalid("history_in_future")

    declaration = manifest["signal_anomaly"]
    if not isinstance(declaration, dict):
        raise BaselineInvalid("missing_field:signal_anomaly")
    for name in ("minimum_independent_dates", "max_observation_age_days"):
        if name not in declaration or declaration[name] is None:
            raise BaselineInvalid(f"missing_field:signal_anomaly.{name}")
    minimum_dates = declaration["minimum_independent_dates"]
    max_age = declaration["max_observation_age_days"]
    if not (_is_number(minimum_dates) and _is_number(max_age)):
        raise BaselineInvalid("below_floor")
    if minimum_dates < MIN_INDEPENDENT_DATES or not 0 <= max_age <= MAX_OBSERVATION_AGE_DAYS:
        raise BaselineInvalid("below_floor")
