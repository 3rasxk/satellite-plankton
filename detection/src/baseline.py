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

Level B (per-cell) helpers, also pure (numpy arrays in, numbers out):
  * ``cell_key`` / ``cell_keys`` -- the integer grid index that identifies a
    raster cell, shared by the baseline cells and the production raster, so
    the two are matched by location and never by array position;
  * ``assess_cell`` / ``assess_cells`` -- the robust z of ``signal_anomaly``
    (same formula, same floors, same boundaries) for one cell or many, from
    a cell's stored median / MAD / date count;
  * ``cell_season_summary``, ``build_level_b`` / ``validate_level_b`` -- the
    ``level_b`` block of the manifest and its fail-closed validation.

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
  * A Level B cell is ONE sampled native pixel per day at the raster scale
    (200 m by default), not an area mean; a cell's baseline describes that
    sampled pixel's own clear-sky record, nothing around it.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from signal_anomaly import (  # noqa: E402
    HIGH_AT_Z,
    MAD_SCALE,
    MAX_OBSERVATION_AGE_DAYS,
    MIN_INDEPENDENT_DATES,
    NDCI_MAX,
    NDCI_MIN,
    WATCH_AT_Z,
    _config,
    _finite,
    _finite_ndci,
    assess_signal_anomaly,
    classify_robust_z,
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

    Returns new dicts; the input rows are not mutated. Existing tags are never
    overwritten (a missing or ``None`` tag counts as absent):

    * a row already tagged with a different ``location_id`` is dropped, and so
      is a row already tagged with a different ``season_key``; neither is
      relabelled into this scope;
    * a row already tagged with a different ``preprocessing_signature`` is KEPT
      with that tag, so ``assess_signal_anomaly`` can report
      ``incompatible_preprocessing`` instead of silently using it;
    * absent tags are filled with ``location_id``, this target month's
      ``season_key`` and ``preprocessing_signature``.

    Rows whose ``acquisition_date`` cannot be parsed are dropped.
    """
    months = season_months(target_month)
    key = season_key(target_month)
    scoped: list[dict] = []
    for row in rows:
        if _month_of(row.get("acquisition_date")) not in months:
            continue
        row_location = row.get("location_id")
        if row_location is not None and row_location != location_id:
            continue
        row_season = row.get("season_key")
        if row_season is not None and row_season != key:
            continue
        tagged = dict(row)
        tagged["location_id"] = location_id
        tagged["season_key"] = key
        if tagged.get("preprocessing_signature") is None:
            tagged["preprocessing_signature"] = preprocessing_signature
        scoped.append(tagged)
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
    """True for a finite int/float (NaN, inf and bool are not numbers here)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def validate_manifest(
    manifest: dict,
    *,
    live_signature: str,
    today: date,
    live_cell_signature: str | None = None,
) -> None:
    """Raise ``BaselineInvalid`` unless the manifest is safe to activate.

    Checks run in this order and the first failure wins:
      1. required top-level keys             -> ``missing_field:<name>``
      2. ``baseline_kind == "test"``         -> ``not_test_kind``
      3. signature equals ``live_signature`` -> ``signature_mismatch``
      4. ``history_end`` not after today     -> ``history_in_future``
      5. floors in ``signal_anomaly``        -> ``below_floor``
      6. ``season_rule == SEASON_RULE``      -> ``season_rule_mismatch``
      7. ``signal_anomaly.status == "active"`` -> ``inactive_declaration``
      8. declared ``mad_scale`` / ``watch_at_z`` / ``high_at_z`` equal the
         ``signal_anomaly`` constants       -> ``threshold_mismatch``
      9. nested ``preprocessing_signature`` / ``baseline_version`` equal the
         top-level ones                      -> ``inconsistent_declaration``

    A ``history_end`` that is not an ISO date is reported as
    ``missing_field:history_end`` (unusable). A missing nested declaration
    field is ``missing_field:signal_anomaly.<name>`` (raised at the step that
    needs it). Floor values must be finite numbers (NaN, inf, bool and strings
    are ``below_floor``), so a hand-edited manifest can never loosen the floors
    owned by ``signal_anomaly.py``.

    Level B: only when ``live_cell_signature`` is given (the cell loader
    passes it; the Level A gate does not), and only after every Level A check
    passed, the ``level_b`` block must exist (``missing_field:level_b``) and
    pass ``validate_level_b``. The Level A gate therefore never depends on
    the Level B block: a stale or broken cell baseline cannot switch off the
    site baseline. Whether the season files named in ``level_b`` exist is
    the loader's check, not this pure function's.
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

    def declared(name: str):
        if name not in declaration or declaration[name] is None:
            raise BaselineInvalid(f"missing_field:signal_anomaly.{name}")
        return declaration[name]

    minimum_dates = declared("minimum_independent_dates")
    max_age = declared("max_observation_age_days")
    if not (_is_number(minimum_dates) and _is_number(max_age)):
        raise BaselineInvalid("below_floor")
    if minimum_dates < MIN_INDEPENDENT_DATES or not 0 <= max_age <= MAX_OBSERVATION_AGE_DAYS:
        raise BaselineInvalid("below_floor")

    if manifest["season_rule"] != SEASON_RULE:
        raise BaselineInvalid("season_rule_mismatch")

    if declared("status") != "active":
        raise BaselineInvalid("inactive_declaration")

    mad_scale = declared("mad_scale")
    watch_at = declared("watch_at_z")
    high_at = declared("high_at_z")
    if not (_is_number(mad_scale) and _is_number(watch_at) and _is_number(high_at)):
        raise BaselineInvalid("threshold_mismatch")
    if not math.isclose(mad_scale, MAD_SCALE, rel_tol=0.0, abs_tol=1e-12) or watch_at != WATCH_AT_Z or high_at != HIGH_AT_Z:
        raise BaselineInvalid("threshold_mismatch")

    for name in ("preprocessing_signature", "baseline_version"):
        if declared(name) != manifest[name]:
            raise BaselineInvalid("inconsistent_declaration")

    if live_cell_signature is not None:
        if manifest.get("level_b") is None:
            raise BaselineInvalid("missing_field:level_b")
        validate_level_b(manifest["level_b"], live_cell_signature=live_cell_signature, today=today)


# --------------------------------------------------------------------------
# Level B: cell identity
# --------------------------------------------------------------------------

# Earth Engine's metre-to-degree factor for an EPSG:4326 read: one degree of
# the equator, 6378137 m * pi / 180, applied to BOTH axes. A 200 m read is a
# 0.0017966306-degree grid in latitude and longitude alike.
METRES_PER_DEGREE = 111319.49079327357

# How far (in cells) a stored coordinate may sit from the key grid's cell
# centre before a builder refuses it as "not on the production pixel grid".
# Real pixelLonLat values sit within ~1e-9 cells; float32 coordinates would
# still be within ~0.004. Half a cell would mean a different grid.
CELL_GRID_TOLERANCE_CELLS = 0.05

CELL_KEY_SCHEME = (
    "(row, col) = (round((lat - d/2) / d), round((lng - d/2) / d)), d = scale_m / "
    "111319.49079327357 deg; origin = centre of the EPSG:4326 cell whose south-west "
    "corner is (0 deg, 0 deg); tolerance half a cell"
)


def cell_size_deg(scale_m: float) -> float:
    """Degrees per cell, on both axes, for an Earth Engine EPSG:4326 read at ``scale_m``."""
    if not (isinstance(scale_m, (int, float)) and not isinstance(scale_m, bool)) or not scale_m > 0:
        raise ValueError(f"scale_m must be a positive number, got {scale_m!r}")
    return scale_m / METRES_PER_DEGREE


def cell_key(lat: float, lng: float, scale_m: float) -> tuple[int, int]:
    """Integer grid index ``(row, col)`` of the raster cell containing (lat, lng).

    Grid: the one Earth Engine reads an EPSG:4326 composite on when it is
    asked for ``scale_m`` metres with no explicit transform -- pixels of
    ``d = scale_m / 111319.49079327357`` degrees on both axes, anchored at
    (0 deg, 0 deg). Its ``pixelLonLat`` values are the pixel CENTRES,
    ``(k + 1/2) * d``. Measured on every stored production raster
    (backend/data/rasters/1..5, 2026-09/10): all cell coordinates sit at
    exactly that half-cell phase. The baseline grid is produced by the
    same kind of request (same polygon, same scale), so both sides' cells
    are the same lattice.

    Origin: LAT0 = LNG0 = d/2, the centre of the cell whose south-west
    corner is the CRS origin. It is derived from ``scale_m`` alone, which
    both sides have, rather than from a bounding box: the study polygon's
    corner sits at an arbitrary phase of this lattice, and an origin at the
    wrong phase would put rounding boundaries ON the cell centres, where
    1e-7 deg of float noise flips a key.

    Key: ``(round((lat - LAT0) / d), round((lng - LNG0) / d))``. A cell
    centre maps to an integer exactly, so any point within HALF A CELL of
    a centre (about 100 m at 200 m) gets that centre's key; float noise of
    ~1e-7 deg is ~5e-5 cells. Equivalent to the index of the pixel that
    contains the point.

    Raises:
        ValueError: non-finite coordinates or a non-positive scale.
    """
    d = cell_size_deg(scale_m)
    lat = float(lat)
    lng = float(lng)
    if not (math.isfinite(lat) and math.isfinite(lng)):
        raise ValueError(f"cell coordinates must be finite, got ({lat}, {lng})")
    half = 0.5 * d
    return (int(round((lat - half) / d)), int(round((lng - half) / d)))


def cell_keys(lat, lng, scale_m: float) -> tuple[np.ndarray, np.ndarray]:
    """Vectorised ``cell_key``: ``(rows, cols)`` as int64 arrays, same arithmetic."""
    d = cell_size_deg(scale_m)
    lat = np.asarray(lat, dtype=np.float64)
    lng = np.asarray(lng, dtype=np.float64)
    if lat.shape != lng.shape:
        raise ValueError(f"lat and lng shapes differ: {lat.shape} vs {lng.shape}")
    if not (np.all(np.isfinite(lat)) and np.all(np.isfinite(lng))):
        raise ValueError("cell coordinates must be finite")
    half = 0.5 * d
    return (
        np.rint((lat - half) / d).astype(np.int64),
        np.rint((lng - half) / d).astype(np.int64),
    )


def grid_offset_cells(lat, lng, scale_m: float) -> float:
    """Largest distance, in cells, of any coordinate from its key's cell centre.

    ~0 for cells on the key grid; 0.5 for a grid anchored half a cell away
    (whose keys would be unstable). 0.0 for no cells.
    """
    d = cell_size_deg(scale_m)
    lat = np.asarray(lat, dtype=np.float64)
    lng = np.asarray(lng, dtype=np.float64)
    if lat.size == 0:
        return 0.0
    half = 0.5 * d
    worst = 0.0
    for values in (lat, lng):
        position = (values - half) / d
        worst = max(worst, float(np.max(np.abs(position - np.rint(position)))))
    return worst


# --------------------------------------------------------------------------
# Level B: assessment of one cell, and of many
# --------------------------------------------------------------------------

# Code tables of ``assess_cells`` (uint8). ``assess_cell`` returns the
# labels; the vectorised form returns these codes.
LEVEL_CODES: dict[int, str | None] = {0: None, 1: "normal", 2: "watch", 3: "high"}
REASON_CODES: dict[int, str | None] = {
    0: None,  # assessed: level is normal, watch or high
    1: "invalid_ndci",  # the cell's own NDCI is missing, non-finite or outside [-1, 1]
    2: "no_baseline",  # median or MAD missing / non-finite, or MAD negative
    3: "insufficient_independent_dates",  # n below the floor (>= 30)
    4: "zero_mad",  # MAD == 0 (or so small that the ratio is not finite)
}
LEVEL_CODE: dict[str, int] = {label: code for code, label in LEVEL_CODES.items() if label}
REASON_CODE: dict[str, int] = {label: code for code, label in REASON_CODES.items() if label}


def _cell_config(min_dates, mad_scale, watch_at_z, high_at_z) -> dict:
    """The signal_anomaly config for these parameters, validated by ``_config``.

    ``_config`` refuses anything looser than signal_anomaly's own floors and
    boundaries (fewer than 30 dates, another MAD scale, other z boundaries),
    so no caller can loosen the cell statistic either. A stricter floor is
    allowed.
    """
    return _config({
        "minimum_independent_dates": min_dates,
        "max_observation_age_days": MAX_OBSERVATION_AGE_DAYS,
        "mad_scale": mad_scale,
        "watch_at_z": watch_at_z,
        "high_at_z": high_at_z,
    })


def _cell_none(reason: str) -> dict:
    return {"level": None, "robust_z": None, "reason": reason}


def assess_cell(
    ndci,
    median,
    mad,
    n,
    *,
    min_dates: int = MIN_INDEPENDENT_DATES,
    mad_scale: float = MAD_SCALE,
    watch_at_z: float = WATCH_AT_Z,
    high_at_z: float = HIGH_AT_Z,
) -> dict:
    """One cell's NDCI against that cell's own seasonal median / MAD.

    ``robust_z = (ndci - median) / (mad_scale * mad)`` -- exactly
    ``signal_anomaly.assess_signal_anomaly``'s formula -- classified by
    ``signal_anomaly.classify_robust_z`` (z >= 2 watch, z >= 3 high; a
    negative z is ``normal``, never a tier). Checks run in signal_anomaly's
    order, first failure wins:

      1. NDCI finite and within [-1, 1]          -> ``invalid_ndci``
      2. median and MAD finite, MAD >= 0          -> ``no_baseline``
      3. n >= ``min_dates``                       -> ``insufficient_independent_dates``
      4. MAD != 0                                 -> ``zero_mad``

    The date-age and history-end (leakage) rules are the caller's: this
    function only sees the statistics, not when the cell was acquired.

    Returns ``{"level", "robust_z", "reason"}``; ``level``/``robust_z`` are
    None exactly when ``reason`` is not.

    Raises:
        ValueError: parameters looser than signal_anomaly's.
    """
    cfg = _cell_config(min_dates, mad_scale, watch_at_z, high_at_z)
    current = _finite_ndci(ndci)
    if current is None:
        return _cell_none("invalid_ndci")
    base_median = _finite(median)
    base_mad = _finite(mad)
    if base_median is None or base_mad is None or base_mad < 0:
        return _cell_none("no_baseline")
    count = _finite(n)
    if count is None or count < int(cfg["minimum_independent_dates"]):
        return _cell_none("insufficient_independent_dates")
    if base_mad == 0:
        return _cell_none("zero_mad")
    robust_z = (current - base_median) / (float(cfg["mad_scale"]) * base_mad)
    level = classify_robust_z(robust_z, cfg)
    if level is None:  # a MAD so small that the ratio overflowed
        return _cell_none("zero_mad")
    return {"level": level, "robust_z": robust_z, "reason": None}


def assess_cells(
    ndci,
    median,
    mad,
    n,
    *,
    min_dates: int = MIN_INDEPENDENT_DATES,
    mad_scale: float = MAD_SCALE,
    watch_at_z: float = WATCH_AT_Z,
    high_at_z: float = HIGH_AT_Z,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Vectorised ``assess_cell``: the same checks, order and arithmetic per element.

    Inputs are equal-shaped arrays (any numeric dtype; stored cells are
    float32 NDCI/median/MAD and uint16 n). Arithmetic and classification
    are done in float64, element for element as ``assess_cell`` does it, so
    the level and reason are identical to the scalar function's.

    Returns ``(z, level_code, reason_code)``:
      * ``z``: float32, the robust z (cast after classification), NaN where
        the cell is not assessed;
      * ``level_code``: uint8, ``LEVEL_CODES`` -- 0 not assessed, 1 normal,
        2 watch, 3 high;
      * ``reason_code``: uint8, ``REASON_CODES`` -- 0 assessed,
        1 invalid_ndci, 2 no_baseline, 3 insufficient_independent_dates,
        4 zero_mad.

    Raises:
        ValueError: parameters looser than signal_anomaly's, or shapes differ.
    """
    cfg = _cell_config(min_dates, mad_scale, watch_at_z, high_at_z)
    floor = int(cfg["minimum_independent_dates"])
    scale = float(cfg["mad_scale"])
    watch = float(cfg["watch_at_z"])
    high = float(cfg["high_at_z"])

    ndci = np.asarray(ndci, dtype=np.float64)
    median = np.asarray(median, dtype=np.float64)
    mad = np.asarray(mad, dtype=np.float64)
    n = np.asarray(n, dtype=np.float64)
    if not ndci.shape == median.shape == mad.shape == n.shape:
        raise ValueError(
            f"assess_cells needs equal shapes, got {ndci.shape}, {median.shape}, {mad.shape}, {n.shape}"
        )

    z = np.full(ndci.shape, np.nan, dtype=np.float32)
    level = np.zeros(ndci.shape, dtype=np.uint8)
    reason = np.zeros(ndci.shape, dtype=np.uint8)

    with np.errstate(invalid="ignore", divide="ignore", over="ignore"):
        pending = np.ones(ndci.shape, dtype=bool)

        def fail(condition: np.ndarray, label: str) -> None:
            nonlocal pending
            hit = pending & condition
            reason[hit] = REASON_CODE[label]
            pending = pending & ~condition

        fail(~(np.isfinite(ndci) & (ndci >= NDCI_MIN) & (ndci <= NDCI_MAX)), "invalid_ndci")
        fail(~(np.isfinite(median) & np.isfinite(mad) & (mad >= 0)), "no_baseline")
        fail(~(np.isfinite(n) & (n >= floor)), "insufficient_independent_dates")
        fail(mad == 0, "zero_mad")
        robust = (ndci - median) / (scale * mad)
        fail(~np.isfinite(robust), "zero_mad")

        codes = np.where(robust < watch, LEVEL_CODE["normal"],
                         np.where(robust < high, LEVEL_CODE["watch"], LEVEL_CODE["high"]))
        level[pending] = codes[pending]
        z[pending] = robust[pending].astype(np.float32)
    return z, level, reason


# --------------------------------------------------------------------------
# Level B: season summary and the manifest's level_b block
# --------------------------------------------------------------------------

# A Level B build is refused if any season has fewer than this share of its
# cells with n >= MIN_INDEPENDENT_DATES (spike, 2026-10-09: 99.4 %).
LEVEL_B_MIN_CELL_SHARE = 0.90

_LEVEL_B_REQUIRED = (
    "scale_m",
    "cell_preprocessing_signature",
    "history_start",
    "history_end",
    "seasons",
    "min_independent_dates",
    "min_cell_share",
)
_SEASON_REQUIRED = ("file", "months", "cells", "cells_n_ge_floor")


def cells_file_name(month: int) -> str:
    """``cells_mMM.npz`` -- the Level B file of the season for target month ``month``."""
    if isinstance(month, bool) or not isinstance(month, int) or not 1 <= month <= 12:
        raise ValueError(f"month must be 1..12, got {month!r}")
    return f"cells_m{month:02d}.npz"


def cell_share_ok(cells_n_ge_floor: int, cells: int, share: float = LEVEL_B_MIN_CELL_SHARE) -> bool:
    """True when a season has cells and at least ``share`` of them reach the floor."""
    return cells > 0 and cells_n_ge_floor / cells >= share


def cell_season_summary(n, mad, *, floor: int = MIN_INDEPENDENT_DATES) -> dict:
    """Counts and spread of one season's stored cells (plain JSON numbers).

    ``n_*`` describe every stored cell (n >= 1); the MAD percentiles describe
    only cells with ``n >= floor`` -- the cells that can be assessed. A value
    with nothing to describe is None, never a made-up 0.
    """
    n = np.asarray(n)
    mad = np.asarray(mad, dtype=np.float64)
    cells = int(n.size)
    reaching = n >= floor
    count = int(np.count_nonzero(reaching))
    usable_mad = mad[reaching]

    def pct(q: float) -> float | None:
        return float(np.percentile(usable_mad, q)) if usable_mad.size else None

    return {
        "cells": cells,
        "cells_n_ge_floor": count,
        "share_n_ge_floor": count / cells if cells else 0.0,
        "n_median": float(np.median(n)) if cells else None,
        "n_min": int(n.min()) if cells else None,
        "n_max": int(n.max()) if cells else None,
        "mad_p05": pct(5),
        "mad_p50": pct(50),
        "mad_p95": pct(95),
    }


def build_level_b(
    *,
    scale_m: int,
    cell_preprocessing_signature: str,
    cell_preprocessing_params: dict,
    built_at: str,
    query_start: str,
    query_end_exclusive: str,
    seasons: dict[str, dict],
) -> dict:
    """The manifest's ``level_b`` block.

    ``history_end`` is the LAST DAY the history query could contain -- the
    day before ``query_end_exclusive`` -- not the last date that happened to
    have data: it is the leakage cutoff, and a cell is only ever assessed
    when its own acquisition date is strictly later than it.
    ``history_start`` is the earliest acquisition date of any season (the
    query start if no season reported one).
    """
    end = date.fromisoformat(query_end_exclusive)
    firsts = [info.get("first_date") for info in seasons.values() if info.get("first_date")]
    d = cell_size_deg(scale_m)
    return {
        "scale_m": int(scale_m),
        "cell_preprocessing_signature": cell_preprocessing_signature,
        "cell_preprocessing_params": copy.deepcopy(cell_preprocessing_params),
        "built_at": built_at,
        "query_start": query_start,
        "query_end_exclusive": query_end_exclusive,
        "history_start": min(firsts) if firsts else query_start,
        "history_end": (end - timedelta(days=1)).isoformat(),
        "history_end_rule": (
            "last day the history query could contain (its end is exclusive); a cell is "
            "assessed only when its own acquisition date is strictly later"
        ),
        "season_rule": SEASON_RULE,
        "min_independent_dates": MIN_INDEPENDENT_DATES,
        "min_cell_share": LEVEL_B_MIN_CELL_SHARE,
        "cell_key": {"scheme": CELL_KEY_SCHEME, "deg_per_cell": d, "origin_deg": [d / 2, d / 2]},
        "seasons": copy.deepcopy(seasons),
    }


def _is_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def validate_level_b(level_b: object, *, live_cell_signature: str, today: date) -> None:
    """Raise ``BaselineInvalid`` unless the ``level_b`` block is safe to use.

    First failure wins:
      1. a dict with every required key       -> ``missing_field:level_b[.<name>]``
      2. cell signature equals the live one    -> ``cell_signature_mismatch``
      3. ISO dates, ``history_end`` <= today,
         ``history_start`` <= ``history_end``  -> ``missing_field:level_b.<date>`` /
                                                  ``level_b_history_in_future`` /
                                                  ``level_b_bad_history``
      4. positive integer ``scale_m``          -> ``level_b_bad_scale``
      5. declared floors not looser than
         MIN_INDEPENDENT_DATES / LEVEL_B_MIN_CELL_SHARE -> ``level_b_below_floor``
      6. exactly the twelve season keys        -> ``level_b_seasons_incomplete``
      7. each season well-formed: canonical file name, its three months,
         counts with 0 <= cells_n_ge_floor <= cells -> ``level_b_bad_season:<key>``
      8. each season meets the cell share      -> ``level_b_below_floor:<key>``
    """
    if not isinstance(level_b, dict):
        raise BaselineInvalid("missing_field:level_b")
    for name in _LEVEL_B_REQUIRED:
        if level_b.get(name) is None:
            raise BaselineInvalid(f"missing_field:level_b.{name}")

    if level_b["cell_preprocessing_signature"] != live_cell_signature:
        raise BaselineInvalid("cell_signature_mismatch")

    try:
        history_start = date.fromisoformat(str(level_b["history_start"]))
    except ValueError:
        raise BaselineInvalid("missing_field:level_b.history_start") from None
    try:
        history_end = date.fromisoformat(str(level_b["history_end"]))
    except ValueError:
        raise BaselineInvalid("missing_field:level_b.history_end") from None
    if history_end > today:
        raise BaselineInvalid("level_b_history_in_future")
    if history_start > history_end:
        raise BaselineInvalid("level_b_bad_history")

    scale_m = level_b["scale_m"]
    if not isinstance(scale_m, int) or isinstance(scale_m, bool) or scale_m <= 0:
        raise BaselineInvalid("level_b_bad_scale")

    floor = level_b["min_independent_dates"]
    share = level_b["min_cell_share"]
    if not (_is_number(floor) and _is_number(share)):
        raise BaselineInvalid("level_b_below_floor")
    if floor < MIN_INDEPENDENT_DATES or share < LEVEL_B_MIN_CELL_SHARE or share > 1:
        raise BaselineInvalid("level_b_below_floor")

    seasons = level_b["seasons"]
    expected = {season_key(month): month for month in range(1, 13)}
    if not isinstance(seasons, dict) or set(seasons) != set(expected):
        raise BaselineInvalid("level_b_seasons_incomplete")

    for key, month in expected.items():
        info = seasons[key]
        if (
            not isinstance(info, dict)
            or any(info.get(name) is None for name in _SEASON_REQUIRED)
            or info["file"] != cells_file_name(month)
            or info["months"] != list(season_months(month))
            or not _is_count(info["cells"])
            or not _is_count(info["cells_n_ge_floor"])
            or info["cells_n_ge_floor"] > info["cells"]
        ):
            raise BaselineInvalid(f"level_b_bad_season:{key}")
        if not cell_share_ok(info["cells_n_ge_floor"], info["cells"], share):
            raise BaselineInvalid(f"level_b_below_floor:{key}")
