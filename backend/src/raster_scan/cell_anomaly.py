"""
Per-cell TEST anomaly: a stored raster cell's NDCI against that cell's OWN
seasonal history (the Level B baseline).

Data sources -- nothing new is measured here, no GEE call, no network, no
database:
  * the cells of ONE stored raster run (`storage.read_cells`, the blob the
    overlay was drawn from), handed in by the caller;
  * ONE `scientific_status.baseline_status()` (the TEST baseline in force)
    and ONE season of the Level B cell baseline
    (`baseline_store.cell_baseline_or_reason`, never raises), paired only
    when both name the same baseline version.

The statistic is detection's: `baseline.assess_cells` (through the bridge)
decides every cell's level and its baseline-side reason -- robust
z = (ndci - median) / (1.4826 * mad), watch at z >= 2, high at z >= 3, the
same function, floors and boundaries as the 7 monitoring sites
(`signal_anomaly.py`). The z reported is the float64 value assess_cells
classified (its own float32 output is that value cast for storage), so a
displayed z of exactly 2.0 is always a `watch`. This module adds only the
two date rules assess_cells leaves to its caller, and the bookkeeping.

When a cell is assessable
-------------------------
Season = `season_key(month of the run's date_used)`: the run's target
month, the rule the sites use. A measured cell is assessable only if ALL
of these hold; otherwise it carries exactly ONE reason, the first rule it
fails in this order (so the reasons partition the measured cells):

  1. `invalid`             NDCI non-finite or outside [-1, 1], NDCI
                           DEGENERATE (|ndci| >= 1 - 1e-6, see below), or
                           acquired AFTER date_used (the observation rules
                           first, as in signal_anomaly);
  2. `low_signal`          any visible band (B4 red, B3 green, B2 blue as
                           stored) below MIN_VISIBLE_DN = 50 DN, or not a
                           finite number (see "Data-quality screens");
  3. `too_old`             acquired more than 14 days before date_used
                           (signal_anomaly.MAX_OBSERVATION_AGE_DAYS; 14
                           days exactly is allowed);
  4. `not_after_history`   acquired on or before `level_b.history_end` --
                           the leakage guard: the baseline may contain
                           that very acquisition, so it is never compared
                           with itself (strictly after only);
  5. `no_baseline`         no baseline cell with its `cell_key` in this
                           season's file (or unusable statistics);
  6. `insufficient_dates`  n below the floor the Level B block declares
                           (validated >= 30, never loosened);
  7. `zero_mad`            MAD == 0 (z undefined).

A reason is never a default: an unassessable cell has no z and no level.
Dates are the cell's own UTC acquisition day (epoch ms // 86 400 000, the
`acquired_date` the pixel endpoint reports). There are SEVEN reason
buckets; `assessable` plus the seven counts equals `measured`.

Data-quality screens (backend rules, 2026-10-09/10)
---------------------------------------------------
Both screens change WHICH cells are scored and pinned, never the
statistic. A screened cell is still a measured cell: the map paints it and
`/raster-scan/pixel` reports its stored values. detection's [-1, 1]
validity rule and its robust z are unchanged; these are stricter backend
rules on top of them, applied in both highlight modes (and in anomaly mode
they are the `invalid` and `low_signal` buckets).

* Degenerate NDCI. NDCI = (B5 - B4) / (B5 + B4) is exactly +1 when B4 is
  zero and exactly -1 when B5 is zero. A zero band is not a physical
  water-colour value; in the stored rasters these cells sit mostly at mask
  edges (run 5: 90 cells at 1.0, z 24-33, topping both pin lists). A
  reading with |ndci| >= 1 - 1e-6 (`DEGENERATE_NDCI_ABS`, float32 noise
  included) is never assessed (`invalid`) and never a pin.
* Low visible signal. MIN_VISIBLE_DN = 50 DN (about 0.005 reflectance at
  S2_SR_HARMONIZED's 1/10000 scale) on each of the stored visible bands.
  THIS IS A DEVELOPER-CHOSEN SCREENING THRESHOLD, NOT VALIDATED AGAINST
  FIELD DATA. Rationale: S2_SR_HARMONIZED removes the processing-baseline
  offset and clips at 0, so very dark water, shadow and residual
  cloud/land edges come out near 0 DN -- a noise floor where a ratio such
  as NDCI explodes (live run 6: the top five anomaly pins, z 19-26 and NDCI
  0.72-0.97, had red 1-13 DN while the run's red median is 356 and its 1st
  percentile 127). A cell with ANY of red (B4), green (B3) or blue (B2)
  below 50 DN, or with a non-finite stored value there (cannot be checked,
  so screened), is `low_signal`: never assessed and never a pin. A run
  whose blob does not store the three visible bands cannot be screened, so
  it is never scored (anomaly mode answers 409 `visible_bands_missing`;
  NDCI mode ranks as before and says the screen did not run). The value is
  not configurable by environment on purpose: changing it changes what the
  API scores, so it changes in code, with its tests.

Limitations -- read before quoting a number from this
-----------------------------------------------------
* TEST baseline: provisional and uncalibrated, never checked against
  recorded bloom events. A watch/high cell is a statistical anomaly of one
  sampled pixel against its own clear-sky record in a three-month season
  window -- not a bloom detection, not a species, not a forecast, and
  not a risk level. A normal (or negative) z does not mean safe water.
* High NDCI also comes from suspended sediment (river mouths), shallow
  bottom, sun glint and cloud edges; a wide MAD in sediment-driven water
  lowers z, a narrow one raises it. Nothing here separates those causes.
* A cell is ONE nearest-neighbour-sampled native pixel per day at the
  raster scale (200 m), not an area mean, and its baseline describes that
  sampled pixel's history only. Small or dispersed blooms may be missed.
* The cutoff is the baseline's `history_end`: right after a rebuild most
  cells of an older run predate it and are reported `not_after_history`
  (counted, never assessed).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np

from .. import _detection as bridge
from .. import baseline_store
from ..baseline_store import CellBaseline
from ..site_anomaly import baseline_block, disclaimer_for, is_test_mode

# Reason buckets, in the priority order of the module docstring.
INVALID = "invalid"
LOW_SIGNAL = "low_signal"
TOO_OLD = "too_old"
NOT_AFTER_HISTORY = "not_after_history"
NO_BASELINE = "no_baseline"
INSUFFICIENT_DATES = "insufficient_dates"
ZERO_MAD = "zero_mad"
REASON_ORDER: tuple[str, ...] = (
    INVALID, LOW_SIGNAL, TOO_OLD, NOT_AFTER_HISTORY, NO_BASELINE, INSUFFICIENT_DATES, ZERO_MAD,
)
# Array codes: 0 = assessable, k = REASON_ORDER[k - 1].
REASON_CODE: dict[str, int] = {name: code for code, name in enumerate(REASON_ORDER, start=1)}

# Why no anomaly can be computed at all (the 409 `reason` of
# /raster-scan/highlights?mode=anomaly). `invalid:<code>` is the refusal
# code of a baseline that exists but must not be used.
MODE_OFF = "mode_off"
NO_CELL_BASELINE = "no_cell_baseline"
RUN_DATE_UNUSABLE = "run_date_unusable"
VERSION_MISMATCH = "version_mismatch"
VISIBLE_BANDS_MISSING = "visible_bands_missing"

# The order of the `counts` block. `assessable` plus the SEVEN reason
# counts partition `measured`; watch and high count assessable cells at or
# over each boundary; flagged_share = (watch + high) / assessable.
COUNT_KEYS: tuple[str, ...] = (
    "measured", "assessable", NO_BASELINE, INSUFFICIENT_DATES, ZERO_MAD,
    NOT_AFTER_HISTORY, TOO_OLD, INVALID, LOW_SIGNAL, "watch", "high", "flagged_share",
)

# |ndci| at or above this is a degenerate reading (a zero band), not a value.
DEGENERATE_NDCI_TOLERANCE = 1e-6
DEGENERATE_NDCI_ABS = 1.0 - DEGENERATE_NDCI_TOLERANCE
DEGENERATE_NDCI_RULE = "abs(ndci) >= 1 - 1e-6"

# Developer-chosen screening threshold, NOT validated against field data:
# a cell whose stored red, green or blue band is below this many digital
# numbers (S2_SR_HARMONIZED, reflectance x 10000; 50 DN ~ 0.005) is too
# close to the post-offset noise floor for a band ratio to mean anything.
# It changes which cells are scored and pinned, not the statistic. See
# the module docstring, "Data-quality screens". Deliberately no env var.
MIN_VISIBLE_DN = 50
# The stored visible bands, as (raster band name, Sentinel-2 band), in
# red/green/blue order -- data-pipeline/src/raster.py `_index_bands` stores
# B4 as true_red, B3 as true_green, B2 as true_blue.
VISIBLE_BANDS: tuple[tuple[str, str], ...] = tuple(
    zip(bridge.RASTER_TRUE_COLOR_BANDS, ("B4", "B3", "B2"))
)
_VISIBLE_KEYS = ("red", "green", "blue")

_MS_PER_DAY = 86_400_000
_EPOCH = date(1970, 1, 1)
_LOGIC_REASON = bridge.baseline_logic.REASON_CODE
_LEVEL = bridge.baseline_logic.LEVEL_CODES


def is_degenerate_ndci(ndci) -> np.ndarray:
    """True where |ndci| >= ``DEGENERATE_NDCI_ABS`` (one band zero). Vectorised;
    NaN is not degenerate (it is not a reading at all)."""
    values = np.abs(np.asarray(ndci, dtype=np.float64))
    with np.errstate(invalid="ignore"):
        return values >= DEGENERATE_NDCI_ABS


class VisibleBandsMissing(RuntimeError):
    """The run's blob does not store the three visible bands, so the
    low-signal screen cannot run and nothing may be scored."""


def visible_dn(cells: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    """The stored (red, green, blue) DN arrays as float64, or None when any
    of the three bands is not in the blob."""
    if any(name not in cells for name, _band in VISIBLE_BANDS):
        return None
    return tuple(np.asarray(cells[name], dtype=np.float64) for name, _band in VISIBLE_BANDS)


def is_low_signal(red, green, blue) -> np.ndarray:
    """True where ANY visible band is below ``MIN_VISIBLE_DN`` or not finite
    (unverifiable support is screened, never assumed). Vectorised."""
    low = np.zeros(np.shape(red), dtype=bool)
    with np.errstate(invalid="ignore"):
        for band in (red, green, blue):
            values = np.asarray(band, dtype=np.float64)
            low |= ~np.isfinite(values) | (values < MIN_VISIBLE_DN)
    return low


def visible_bands_dict(red: float, green: float, blue: float) -> dict[str, float | None]:
    """``{"red", "green", "blue"}`` of one cell: the stored DN widened, None
    where not finite."""
    return {
        key: (float(value) if np.isfinite(value) else None)
        for key, value in zip(_VISIBLE_KEYS, (red, green, blue))
    }


@dataclass(frozen=True)
class AnomalyContext:
    """One request's baseline: a valid status and the season's cells, same version."""

    status: dict
    cells: CellBaseline
    date_used: date
    season_key: str

    @property
    def disclaimer(self) -> str:
        """The TEST-baseline truth-boundary text (`site_anomaly.disclaimer_for`)."""
        return disclaimer_for(self.status)

    def baseline(self) -> dict:
        """The response's `baseline` block: `baseline_status()` plus `level_b`."""
        block = baseline_block(self.status) or {}
        summary = dict(self.cells.summary)
        summary["months"] = list(summary.get("months") or self.cells.months)
        summary["max_observation_age_days"] = bridge.SIGNAL_ANOMALY_MAX_OBSERVATION_AGE_DAYS
        block["level_b"] = summary
        return block


@dataclass(frozen=True)
class Unavailable:
    """Why no cell anomaly can be computed for this run (never an exception)."""

    reason: str
    cause: str | None
    season_key: str | None


def _season_of(date_used: str | None) -> tuple[date, str] | None:
    try:
        target = date.fromisoformat(str(date_used))
    except (TypeError, ValueError):
        return None
    return target, bridge.baseline_logic.season_key(target.month)


def resolve(status: dict, date_used: str | None) -> AnomalyContext | Unavailable:
    """Pair ONE ``baseline_status()`` with the season of ``date_used``. Never raises.

    Mode off -> ``mode_off`` before any file is looked at. Otherwise the
    season file is loaded once (``cell_baseline_or_reason``, cached) and
    must carry the status's own version. Reasons: ``mode_off``;
    ``run_date_unusable``; ``invalid:<code>`` for a refused baseline (Level
    A refusal from the status, or a Level A/B refusal from the cell
    loader); ``no_cell_baseline`` with ``cause`` = the loader's reason
    (``no_artifact``, ``no_level_b``, ``missing_cells_file:<name>``,
    ``unknown_season:<key>``, ``unreadable``) or ``version_mismatch`` when
    the two reads straddled a rebuild.
    """
    if not is_test_mode(status):
        return Unavailable(MODE_OFF, None, None)
    season = _season_of(date_used)
    if season is None:
        return Unavailable(RUN_DATE_UNUSABLE, None, None)
    target, key = season
    if status.get("valid") is not True:
        cause = status.get("reason") or "unknown"
        if cause == "no_artifact":
            return Unavailable(NO_CELL_BASELINE, cause, key)
        return Unavailable(f"invalid:{cause}", None, key)
    cells, reason = baseline_store.cell_baseline_or_reason(key)
    if cells is None:
        if reason == MODE_OFF:
            return Unavailable(MODE_OFF, None, None)
        if reason and reason.startswith("invalid:"):
            return Unavailable(reason, None, key)
        return Unavailable(NO_CELL_BASELINE, reason, key)
    if cells.version != status.get("version"):
        return Unavailable(NO_CELL_BASELINE, VERSION_MISMATCH, key)
    return AnomalyContext(status=status, cells=cells, date_used=target, season_key=key)


def assess(ndci, lat, lng, date_ms, context: AnomalyContext, *,
           visible: tuple) -> dict[str, np.ndarray]:
    """Assess measured cells against the context's season. Vectorised, pure.

    Inputs are equal-length arrays of the stored values (NDCI float32 is
    widened, never rounded); ``visible`` is the cells' stored (red, green,
    blue) DN (``visible_dn``) -- required, because no cell is scored
    without the low-signal screen. Returns arrays of the same length:
      * ``reason``: uint8, 0 = assessable, else ``REASON_CODE`` (one per cell);
      * ``level``: uint8 ``baseline.LEVEL_CODES`` (0 none, 1 normal, 2 watch,
        3 high), non-zero only where assessable;
      * ``robust_z``: float64, NaN unless assessable;
      * ``median_ndci``, ``mad``: float64 baseline statistics of the cell's
        key, NaN when the season file has no such key;
      * ``n_dates``: int64 date count of that key, -1 when it has none;
      * ``red``, ``green``, ``blue``: float64 stored visible DN.
    """
    red, green, blue = (np.asarray(band, dtype=np.float64) for band in visible)
    cells = context.cells
    ndci = np.asarray(ndci, dtype=np.float64)
    lat = np.asarray(lat, dtype=np.float64)
    lng = np.asarray(lng, dtype=np.float64)
    day = np.asarray(date_ms, dtype=np.int64) // _MS_PER_DAY

    index = cells.index_of(lat, lng)
    has_key = index >= 0
    take = np.where(has_key, index, 0)
    if cells.lat.size:
        median = np.where(has_key, cells.median[take].astype(np.float64), np.nan)
        mad = np.where(has_key, cells.mad[take].astype(np.float64), np.nan)
        n_dates = np.where(has_key, cells.n[take].astype(np.int64), -1)
    else:
        median = np.full(ndci.shape, np.nan)
        mad = np.full(ndci.shape, np.nan)
        n_dates = np.full(ndci.shape, -1, dtype=np.int64)

    # detection decides the level and the baseline-side reason; a missing
    # key reaches it as a NaN median, i.e. its own `no_baseline`.
    _z32, level, logic_reason = bridge.baseline_logic.assess_cells(
        ndci, median, mad, np.where(n_dates >= 0, n_dates, np.nan).astype(np.float64),
        min_dates=cells.min_independent_dates,
    )

    used_day = (context.date_used - _EPOCH).days
    end_day = (date.fromisoformat(cells.history_end) - _EPOCH).days
    age = used_day - day

    reason = np.zeros(ndci.shape, dtype=np.uint8)
    pending = np.ones(ndci.shape, dtype=bool)
    for name, failed in (
        (INVALID, (logic_reason == _LOGIC_REASON["invalid_ndci"])
         | is_degenerate_ndci(ndci) | (age < 0)),
        (LOW_SIGNAL, is_low_signal(red, green, blue)),
        (TOO_OLD, age > bridge.SIGNAL_ANOMALY_MAX_OBSERVATION_AGE_DAYS),
        (NOT_AFTER_HISTORY, day <= end_day),
        (NO_BASELINE, logic_reason == _LOGIC_REASON["no_baseline"]),
        (INSUFFICIENT_DATES, logic_reason == _LOGIC_REASON["insufficient_independent_dates"]),
        (ZERO_MAD, logic_reason == _LOGIC_REASON["zero_mad"]),
    ):
        hit = pending & failed
        reason[hit] = REASON_CODE[name]
        pending &= ~failed
    # Every remaining cell passed assess_cells (reason code 0, level set).
    assessable = pending

    robust_z = np.full(ndci.shape, np.nan, dtype=np.float64)
    with np.errstate(invalid="ignore", divide="ignore"):
        # The float64 expression assess_cells classified (same operands,
        # same order); its float32 z output is this value cast.
        robust_z[assessable] = (
            (ndci[assessable] - median[assessable])
            / (bridge.SIGNAL_ANOMALY_MAD_SCALE * mad[assessable])
        )
    return {
        "reason": reason,
        "level": np.where(assessable, level, 0).astype(np.uint8),
        "robust_z": robust_z,
        "median_ndci": median,
        "mad": mad,
        "n_dates": n_dates,
        "red": red,
        "green": green,
        "blue": blue,
    }


def describe(result: dict[str, np.ndarray], i: int) -> dict[str, Any]:
    """Cell ``i`` of an ``assess`` result as plain JSON values.

    ``{"robust_z", "median_ndci", "mad", "n_dates", "level", "reason",
    "visible_bands_dn"}``: the baseline statistics of the cell's key
    whenever it has one (also when another rule makes the cell
    unassessable), z and level only when assessable, the reason only when
    not, and the stored visible DN the screen judged.
    """
    code = int(result["reason"][i])
    n_dates = int(result["n_dates"][i])

    def number(name: str) -> float | None:
        value = float(result[name][i])
        return value if np.isfinite(value) else None

    return {
        "robust_z": number("robust_z") if code == 0 else None,
        "median_ndci": number("median_ndci"),
        "mad": number("mad"),
        "n_dates": n_dates if n_dates >= 0 else None,
        "level": _LEVEL[int(result["level"][i])] if code == 0 else None,
        "reason": None if code == 0 else REASON_ORDER[code - 1],
        "visible_bands_dn": visible_bands_dict(
            result["red"][i], result["green"][i], result["blue"][i]),
    }


def counts(result: dict[str, np.ndarray]) -> dict[str, int | float | None]:
    """The ``counts`` block, in ``COUNT_KEYS`` order; plain JSON numbers.

    ``assessable`` + the seven reason counts == ``measured``; ``watch`` and
    ``high`` count assessable cells only. ``flagged_share`` is
    ``(watch + high) / assessable`` -- how often the criterion fires in THIS
    scan -- and None when nothing is assessable (never a made-up 0).
    """
    reason = result["reason"]
    level = result["level"]
    tally = {name: int(np.count_nonzero(reason == REASON_CODE[name])) for name in REASON_ORDER}
    out = {
        "measured": int(reason.size),
        "assessable": int(np.count_nonzero(reason == 0)),
        **tally,
        "watch": int(np.count_nonzero((reason == 0) & (level == 2))),
        "high": int(np.count_nonzero((reason == 0) & (level == 3))),
    }
    out["flagged_share"] = (
        (out["watch"] + out["high"]) / out["assessable"] if out["assessable"] else None
    )
    return {key: out[key] for key in COUNT_KEYS}


def _stored_index(cells: dict, found: dict) -> int | None:
    """The stored index of the cell an ``inspect_cell`` reading reports.

    ``inspect_cell`` returns the stored values widened exactly (float64 of
    float32/float64), so the cell is found by exact equality of its own
    coordinate and date among measured cells; the last match, as the
    click lookup and the renderer take the last cell of a pixel.
    """
    lat = np.asarray(cells["lat"], dtype=np.float64)
    lng = np.asarray(cells["lng"], dtype=np.float64)
    dates = np.asarray(cells[bridge.RASTER_DATE_BAND])
    measured = bridge.valid_cell_mask(dates) & np.isfinite(np.asarray(cells["ndci"], dtype=np.float64))
    hits = np.flatnonzero(
        measured & (lat == found["cell_lat"]) & (lng == found["cell_lng"])
        & (dates == found["date_ms"])
    )
    return int(hits[-1]) if hits.size else None


def pixel_anomaly(found: dict, context: AnomalyContext, cells: dict) -> dict | None:
    """The ``anomaly`` block of ``/raster-scan/pixel`` for an ``inspect_cell`` result.

    ``cells`` is the blob ``found`` was read from. None unless ``found`` is a
    ``reading`` AND the blob stores the visible bands (an unscreened cell is
    never scored, the same rule that makes highlights answer 409). Assessed
    by the same ``assess`` call the highlights use, on the stored values of
    the very cell the click reports, so a pin and a click on its square give
    the same anomaly -- including ``reason: "low_signal"``.
    """
    if found.get("state") != "reading":
        return None
    visible = visible_dn(cells)
    index = _stored_index(cells, found)
    if visible is None or index is None:
        return None
    pick = np.array([index])
    result = assess(
        np.asarray(cells["ndci"], dtype=np.float64)[pick],
        np.asarray(cells["lat"], dtype=np.float64)[pick],
        np.asarray(cells["lng"], dtype=np.float64)[pick],
        np.asarray(cells[bridge.RASTER_DATE_BAND]).astype(np.int64)[pick],
        context,
        visible=tuple(band[pick] for band in visible),
    )
    return {
        **describe(result, 0),
        "baseline_version": context.cells.version,
        "season_key": context.season_key,
    }
