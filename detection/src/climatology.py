"""
MODIS-derived climatology baseline + anomaly z-scores.

Data source: MODIS-Aqua `chlor_a` (2002-present) via `data-pipeline`'s
`get_modis_chlorophyll_history(lat, lng)`, reached through
`detection/src/_data_pipeline.py`. See `data-pipeline/src/modis.py`.
Resolution: ~4.6 km MODIS-Aqua L3SMI grid -- coarse relative to Sentinel-2
(10 m). This module builds the *baseline* (what is normal for this
location at this time of year), not the fine detection -- fine-grained
"is there a signal today" comes from Sentinel-2 indices in `indices.py`.
Never treat a MODIS climatology mean/std computed from a handful of
points (small `n`) as equivalent in confidence to one built from decades
of dense observations -- see `n` in every returned dict and the
`MIN_RELIABLE_N` threshold below.

Limitation: MODIS chlor_a coverage has real gaps from cloud, sun glint,
and unreliable-algorithm exclusion over turbid coastal water (documented
in data-pipeline/src/modis.py's own docstring) -- a day-of-year window
with zero matched observations returns `None`, not a fabricated value.
Live-tested on this project (2026-08-22): an offshore upper-Gulf point
(13.00, 100.70) had a genuine ~2-month data gap spanting late June to
early September 2018 (nearest reading to 2018-07-30 was 31 days away) --
consistent with docs/DETECTION_PLAN.md §8's documented monsoon blind
period, not a bug in this code.
"""

from __future__ import annotations

import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from _data_pipeline import (  # noqa: E402
    day_of_year_climatology,
    get_modis_chlorophyll_history,
)

# Below this many matched observations in the day-of-year window, the
# mean/std is reported but flagged low-confidence -- a handful of points
# from a handful of years is not the same evidentiary weight as a dense
# multi-decade sample. Not a hard cutoff (no observation is discarded),
# just a confidence flag callers (thresholds.py, prediction.py) must
# surface rather than silently trust every n the same.
MIN_RELIABLE_N = 5

DEFAULT_CLIMATOLOGY_WINDOW_DAYS = 7


def build_climatology(
    lat: float,
    lng: float,
    target_date: str,
    window_days: int = DEFAULT_CLIMATOLOGY_WINDOW_DAYS,
) -> dict | None:
    """Per-location, per-day-of-year chlor_a mean/std, MODIS 2002-present.

    Pulls the full MODIS chlor_a archive at (lat, lng) (real GEE call,
    every year 2002-present in one series) and reduces it to the
    day-of-year window around `target_date` via data-pipeline's
    `day_of_year_climatology` (reused, not reimplemented -- see
    `_data_pipeline.py`).

    Args:
        lat, lng: WGS84 coordinates.
        target_date: "YYYY-MM-DD" -- day-of-year is what matters, the
            year is ignored for the window match.
        window_days: +/- days around the target day-of-year to pool
            observations from across all archive years.

    Returns:
        {'mean': float, 'std': float, 'n': int, 'reliable': bool} or
        None if the archive has zero observations in that window at this
        location (a real, reportable outcome -- e.g. a monsoon blind
        period, or a location MODIS's algorithm always excludes).

    Raises:
        GEEAuthError: propagated from get_modis_chlorophyll_history if
            GEE is not authenticated -- never caught here.
    """
    history = get_modis_chlorophyll_history(lat, lng)
    clim = day_of_year_climatology(history, "chlor_a", target_date, window_days)
    if clim is None:
        return None
    return {**clim, "reliable": clim["n"] >= MIN_RELIABLE_N}


def z_score(value: float, climatology: dict | None) -> dict:
    """Anomaly z-score of `value` against a climatology dict.

    anomaly = (value - climatology.mean) / climatology.std
    (docs/DETECTION_PLAN.md §2 formula, expressed in standard deviations
    so thresholds are comparable across locations with different baseline
    productivity.)

    Args:
        value: current index/chlorophyll reading.
        climatology: output of `build_climatology`, or None.

    Returns:
        {'z': float | None, 'reason': str | None} -- `z` is None (not a
        fabricated 0.0) when no climatology exists, or when std == 0 (a
        genuinely flat historical series makes any deviation formally
        infinite/undefined -- reported as None with a reason rather than
        as +/-inf, which downstream code could silently sum or compare).
    """
    if climatology is None:
        return {"z": None, "reason": "no_climatology_data_for_this_location_and_window"}
    std = climatology["std"]
    if std == 0:
        return {"z": None, "reason": "zero_historical_variance_z_undefined"}
    z = (value - climatology["mean"]) / std
    return {"z": z, "reason": None}
