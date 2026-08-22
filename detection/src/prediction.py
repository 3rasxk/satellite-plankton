"""
Rule-based risk escalation -- the prediction layer.

Data source: composes `indices.py` (Sentinel-2 spectral indices),
`climatology.py` (MODIS chlor_a baseline/z-score), and, through
`_data_pipeline.py`, live `get_modis_sst` and `get_rainfall_proxy` calls.
No trained model, no fitted weights -- every cutoff and rule is read from
`config.yaml`'s `escalation_rules`/`trend` sections (CLAUDE.md
"Non-negotiable rules": "Every threshold and rule lives in config.yaml").

Detection vs. prediction -- kept as two separate outputs with separate
confidence, per CLAUDE.md's truth boundary and
`.claude/agents/bloom-detection.md` §"Non-negotiable rules"
("Detection and prediction are separate outputs... Never merge them into
one number"):
  - `detect()` answers "is there an anomalous signal right now" --
    standard remote sensing, high confidence.
  - `risk_level()` answers "is risk trending up" -- rule-based,
    indicative only. Its docstring and `prediction_confidence_label` in
    config.yaml must be read by any caller before that word ("warning",
    "watch") reaches a UI without the caveat attached.

Limitation restated (docs/DETECTION_PLAN.md §3): published ML
forecasting reaches ~96% accuracy at 8-day lead time; this rule-based
layer is not claimed to be comparable, and no lead-time accuracy number
is computed anywhere in this module -- with the validation set's 0-of-14
real satellite matches (see thresholds.py), there is no basis to compute
one even informally.
"""

from __future__ import annotations

import sys
from pathlib import Path
from statistics import mean

import yaml

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from _data_pipeline import (  # noqa: E402
    GEEAuthError,
    NoCloudFreeImageryError,
    NoWaterPixelsError,
    get_modis_sst,
    get_rainfall_proxy,
    get_sentinel2_bands,
)
from climatology import build_climatology, z_score  # noqa: E402
from indices import compute_all_indices  # noqa: E402

CONFIG_PATH = _THIS_DIR / "config.yaml"


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


# --------------------------------------------------------------------------
# Trend / acceleration -- pure functions over a MODIS chlor_a series.
# --------------------------------------------------------------------------


def _linear_slope(points: list[tuple[float, float]]) -> float | None:
    """Least-squares slope of y over x for [(x, y), ...]. Pure function.
    Returns None if fewer than 2 points (a slope needs at least 2)."""
    n = len(points)
    if n < 2:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x_mean, y_mean = mean(xs), mean(ys)
    denom = sum((x - x_mean) ** 2 for x in xs)
    if denom == 0:
        return None
    return sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys)) / denom


def compute_trend(history: list[dict], target_date: str, window_days: int) -> dict:
    """Linear slope of chlor_a over the `window_days` ending at
    `target_date`, from a real MODIS chlor_a series (as returned by
    `get_modis_chlorophyll_history`). Handles real archive gaps -- uses
    however many observations actually fall in the window, which may be
    fewer than `window_days` (never interpolated/fabricated).

    Returns:
        {'slope_per_day': float | None, 'rising': bool | None, 'n': int}
        None slope/rising when fewer than 2 real observations fall in
        the window (e.g. a cloud-heavy stretch) -- reported, not guessed.
    """
    from datetime import datetime

    target = datetime.strptime(target_date, "%Y-%m-%d")
    windowed = [
        row
        for row in history
        if 0 <= (target - datetime.strptime(row["date"], "%Y-%m-%d")).days <= window_days
    ]
    points = [
        ((target - datetime.strptime(row["date"], "%Y-%m-%d")).days * -1.0, row["chlor_a"])
        for row in windowed
    ]
    slope = _linear_slope(points)
    return {
        "slope_per_day": slope,
        "rising": (slope > 0) if slope is not None else None,
        "n": len(windowed),
    }


def compute_acceleration(
    history: list[dict], target_date: str, short_window_days: int, long_window_days: int
) -> dict:
    """2nd-derivative proxy: short-window slope minus long-window slope.
    A positive value means recent growth is faster than the longer-run
    trend (rapid onset); near-zero means steady elevation rather than
    acceleration (docs/DETECTION_PLAN.md §3 distinction).

    Returns:
        {'acceleration': float | None, 'short_trend': dict, 'long_trend': dict}
    """
    short_trend = compute_trend(history, target_date, short_window_days)
    long_trend = compute_trend(history, target_date, long_window_days)
    accel = None
    if short_trend["slope_per_day"] is not None and long_trend["slope_per_day"] is not None:
        accel = short_trend["slope_per_day"] - long_trend["slope_per_day"]
    return {"acceleration": accel, "short_trend": short_trend, "long_trend": long_trend}


# --------------------------------------------------------------------------
# Detection -- high confidence, standard remote sensing.
# --------------------------------------------------------------------------


def detect(lat: float, lng: float, date: str, config: dict | None = None) -> dict:
    """Is there an anomalous chlorophyll signal right now, at this pixel?

    High-confidence output (docs/DETECTION_PLAN.md §1) -- standard
    spectral-index + climatology-anomaly remote sensing, no rule-based
    trend/prediction logic here (that is `risk_level`, separate output,
    separate confidence).

    Args:
        lat, lng: WGS84 coordinates.
        date: "YYYY-MM-DD".
        config: pre-loaded config.yaml dict; loaded fresh if omitted.

    Returns:
        {'anomaly_z': float | None, 'index_values': dict | None,
         'detected': bool, 'index_used': str, 'status': str,
         'reason': str | None}
        `status` is one of: 'ok', 'no_imagery' (cloud/no scene in
        window), 'no_water_pixels' (on land/shore), 'no_climatology'
        (MODIS archive gap at this location/date). `detected` is False
        (never True) whenever `status != 'ok'` -- absence of data is
        never reported as absence of a bloom.

    Raises:
        GEEAuthError: propagated, never caught (CLAUDE.md "never
        catch-and-fabricate" -- this is the one error type detect() does
        NOT convert into a status field, because it means the whole
        pipeline is unusable, not that this one reading is unavailable).
    """
    config = config or load_config()
    primary_index = config["indices"]["primary"]

    try:
        bands = get_sentinel2_bands(lat, lng, date)
    except NoCloudFreeImageryError as exc:
        return {
            "anomaly_z": None,
            "index_values": None,
            "detected": False,
            "index_used": primary_index,
            "status": "no_imagery",
            "reason": str(exc),
        }
    except NoWaterPixelsError as exc:
        return {
            "anomaly_z": None,
            "index_values": None,
            "detected": False,
            "index_used": primary_index,
            "status": "no_water_pixels",
            "reason": str(exc),
        }

    index_values = compute_all_indices(bands)
    climatology = build_climatology(lat, lng, date, config["climatology"]["window_days"])
    z = z_score(index_values[primary_index], climatology)

    if z["z"] is None:
        return {
            "anomaly_z": None,
            "index_values": index_values,
            "detected": False,
            "index_used": primary_index,
            "status": "no_climatology",
            "reason": z["reason"],
        }

    cutoff = config["thresholds"][primary_index]["elevated_z"]
    return {
        "anomaly_z": z["z"],
        "index_values": index_values,
        "detected": z["z"] >= cutoff,
        "index_used": primary_index,
        "status": "ok",
        "reason": None,
    }


# --------------------------------------------------------------------------
# Prediction -- rule-based escalation, lower confidence, explicitly
# labeled as such. Rules are DATA, read from config.yaml, not branching
# logic hard-coded per level -- evaluate_rules() is generic over
# whatever `escalation_rules` config.yaml contains.
# --------------------------------------------------------------------------

# Level order, most severe last, so the highest fully-satisfied rule wins.
_LEVEL_ORDER = ["elevated", "watch", "warning"]


def _condition_context(
    anomaly_z: float | None,
    trend_14d: dict,
    sst_anomaly: float | None,
) -> dict:
    return {
        "anomaly_z": anomaly_z,
        "trend_14d_rising": trend_14d.get("rising"),
        "sst_anomaly": sst_anomaly,
    }


def _eval_condition(expr: str, ctx: dict) -> bool:
    """Evaluate one condition string from config.yaml's escalation_rules
    against the runtime context. Conditions are restricted to a fixed
    vocabulary (the keys `_condition_context` provides) via a tiny,
    explicit parser -- deliberately NOT `eval()` on arbitrary config
    text, so a config file can never execute arbitrary code.

    Supported shape: "<name> <op> <value>" where op in
    {>=, <=, >, <, ==} and value is a float or the literal true/false.
    Returns False (not True) if the named variable is None (missing
    data must never satisfy a rule and silently escalate risk).
    """
    parts = expr.split()
    if len(parts) != 3:
        raise ValueError(f"Unsupported condition shape in config.yaml: {expr!r}")
    name, op, raw_value = parts
    if name not in ctx:
        raise ValueError(f"Unknown condition variable {name!r} in config.yaml: {expr!r}")

    value = ctx[name]
    if value is None:
        return False

    target = {"true": True, "false": False}.get(raw_value.lower())
    if target is None:
        target = float(raw_value)

    ops = {
        ">=": lambda a, b: a >= b,
        "<=": lambda a, b: a <= b,
        ">": lambda a, b: a > b,
        "<": lambda a, b: a < b,
        "==": lambda a, b: a == b,
    }
    if op not in ops:
        raise ValueError(f"Unsupported operator in config.yaml condition: {expr!r}")
    return ops[op](value, target)


def evaluate_rules(ctx: dict, escalation_rules: dict) -> dict:
    """Evaluate every level's conditions against ctx.

    Returns:
        {'level': str, 'triggered_rules': [level, ...]}
        `level` is the highest level (per `_LEVEL_ORDER`) whose every
        condition is satisfied, or 'normal' if none are. `triggered_rules`
        lists every level that independently fired (not just the winning
        one) so the frontend can explain a red cell fully
        (`.claude/agents/bloom-detection.md` §"Handoff").
    """
    triggered = []
    for level in _LEVEL_ORDER:
        conditions = escalation_rules[level]["conditions"]
        if all(_eval_condition(c, ctx) for c in conditions):
            triggered.append(level)

    winning = triggered[-1] if triggered else "normal"
    return {"level": winning, "triggered_rules": triggered}


def risk_level(lat: float, lng: float, date: str, config: dict | None = None) -> dict:
    """Is risk trending up? Rule-based, indicative -- lower confidence
    than `detect()`. Never call this the same "score" as detect()'s
    anomaly_z; the two are returned in the same dict here only for
    handoff convenience (`.claude/agents/bloom-detection.md` §"Handoff"
    return shape), not merged into one number.

    Args:
        lat, lng: WGS84 coordinates.
        date: "YYYY-MM-DD".
        config: pre-loaded config.yaml dict; loaded fresh if omitted.

    Returns:
        {'level': 'normal'|'elevated'|'watch'|'warning',
         'triggered_rules': [...], 'detection': {...detect() output...},
         'trend_14d': {...}, 'sst': {...} | None,
         'rainfall': {...} | None,
         'confidence_label': str  # config.yaml's prediction_confidence_label,
                                   # always attached so this never travels
                                   # without its caveat}

    Raises:
        GEEAuthError: propagated, never caught.
    """
    from _data_pipeline import get_modis_chlorophyll_history

    config = config or load_config()
    detection = detect(lat, lng, date, config)

    history = get_modis_chlorophyll_history(lat, lng)
    trend_cfg = config["trend"]
    trend_14d = compute_trend(history, date, trend_cfg["long_window_days"])

    sst_anomaly = None
    sst_result = None
    try:
        sst_result = get_modis_sst(lat, lng, date)
        if sst_result["sst"] is not None and sst_result["sst_climatology"] is not None:
            clim = sst_result["sst_climatology"]
            if clim["std"] > 0:
                sst_anomaly = (sst_result["sst"] - clim["mean"]) / clim["std"]
    except GEEAuthError:
        raise

    rainfall = None
    try:
        rainfall = get_rainfall_proxy(lat, lng, date)
    except GEEAuthError:
        raise

    ctx = _condition_context(detection["anomaly_z"], trend_14d, sst_anomaly)
    evaluation = evaluate_rules(ctx, config["escalation_rules"])

    return {
        "level": evaluation["level"],
        "triggered_rules": evaluation["triggered_rules"],
        "detection": detection,
        "trend_14d": trend_14d,
        "sst": sst_result,
        "sst_anomaly": sst_anomaly,
        "rainfall": rainfall,
        "confidence_label": config["prediction_confidence_label"],
    }
