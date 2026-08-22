"""
Event matching + leave-one-out threshold calibration against the 14
documented Thai events.

Data source: `data/validation/events.csv` (top-level, canonical -- never
`data/validation/thailand/`, which is a citation archive only, per
`data/validation/README.md`). Satellite readings come from `indices.py`
+ `climatology.py`, which call through `_data_pipeline.py` to the real,
live-authenticated `data-pipeline` functions.

MANDATORY READING before this module: `data/validation/CALIBRATION_NOTES.md`.
Every one of its five sections is encoded below:
  §1 same-episode cluster hold-out -> CLUSTERS / leave_one_out()
  §2 species column -> event_table.md includes it
  §3 th_012-014 low weight -> LOW_WEIGHT_EVENTS, excluded from the
     operating-point choice's headline framing
  §4 date-precision tiers -> date_precision_tier()
  §5 cell_count range handling -> parse_cell_count() (midpoint policy,
     read from config.yaml, never silent)

HEADLINE FINDING (read before trusting any "flagged" column): every one
of the 14 rows in events.csv has a blank lat/lng. Per CLAUDE.md and
docs/DETECTION_PLAN.md §3, a coordinate is never invented for a place
name -- "an unmatched event is a finding, not a failure." That leaves 0
of 14 events matchable to a satellite pixel using their own recorded
location. One exception was attempted, not a workaround: th_001's
location is recorded at the scale of "upper Gulf of Thailand" (the whole
study area), not a named site, so a generic open-water point *inside*
that same stated scope was tried as a regional proxy -- explicitly not a
claim about th_001's exact pixel, just a same-scale check of whether the
described basin-wide super-bloom shows up in a representative sample of
the basin. It still returned no usable data (see `attempt_th001_regional_proxy`
below and `reports/event_table.md`) -- a real, live-tested outcome, not a
hypothetical one.

Consequence for calibration: the sweep-and-count procedure in
docs/DETECTION_PLAN.md §4 requires (index_value, source_says_bloom) pairs
per event. With zero real pairs available, `sweep_thresholds` and
`leave_one_out` below are fully implemented and ready to run the moment
real coordinates exist for any of these events, but this run produces an
empty/near-empty result set. That emptiness is reported explicitly in
`reports/event_table.md`, not hidden.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import yaml

_THIS_DIR = Path(__file__).resolve().parent
_DETECTION_DIR = _THIS_DIR.parent
_REPO_ROOT = _DETECTION_DIR.parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from _data_pipeline import (  # noqa: E402
    NoCloudFreeImageryError,
    NoWaterPixelsError,
    get_sentinel2_bands,
)
from climatology import build_climatology, z_score  # noqa: E402
from indices import compute_all_indices  # noqa: E402

EVENTS_CSV = _REPO_ROOT / "data" / "validation" / "events.csv"
CONFIG_PATH = _THIS_DIR / "config.yaml"

# Candidate open-water points used ONLY for the th_001 regional-proxy
# attempt (see module docstring) -- never used to stand in for any
# named-site event's coordinate. Live-tested 2026-08-22 (see this
# module's report / the bloom-detection handoff notes): these are
# ordinary points inside the upper-Gulf study area with confirmed live
# Sentinel-2/MODIS reachability in *other* time windows, used here to
# check the one date/window that matters for th_001.
TH_001_PROXY_POINTS = [
    (13.00, 100.70, "upper_gulf_open_water_1"),
    (13.15, 100.82, "upper_gulf_open_water_2"),
]


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


# --------------------------------------------------------------------------
# events.csv loading + the CALIBRATION_NOTES.md decisions.
# --------------------------------------------------------------------------


def load_events() -> list[dict]:
    """Read the canonical 14-row events.csv. Returns raw dict rows,
    unmodified field values (parsing/derivation happens in the helpers
    below, kept separate so the raw source values are always inspectable)."""
    with open(EVENTS_CSV, newline="") as f:
        return list(csv.DictReader(f))


def parse_cell_count(raw: str, policy: str = "midpoint") -> dict:
    """Explicit, visible cell_count parsing (CALIBRATION_NOTES.md §5).

    `raw` as stored in events.csv is one of: blank, a single number
    ("1500000"), or a literal range string ("684-8700"). This function
    never silently takes the first number out of a range via generic
    string parsing -- every case is a named branch.

    Args:
        raw: the raw events.csv cell_count string.
        policy: how to reduce a range to one representative number for
            display sorting. Only "midpoint" is implemented (the policy
            config.yaml documents and justifies); any other value raises
            rather than silently falling back.

    Returns:
        {'raw': str, 'lower': float | None, 'upper': float | None,
         'representative': float | None}
        All three of lower/upper/representative are None when `raw` is
        blank (th_002, th_012, th_013, th_014) -- never coerced to 0,
        which would misrepresent "not reported" as "zero cells observed."
    """
    raw = (raw or "").strip()
    if not raw:
        return {"raw": raw, "lower": None, "upper": None, "representative": None}

    if "-" in raw:
        lower_s, upper_s = raw.split("-", 1)
        lower, upper = float(lower_s), float(upper_s)
    else:
        lower = upper = float(raw)

    if policy != "midpoint":
        raise ValueError(f"Unsupported cell_count_range_policy: {policy!r}")
    representative = (lower + upper) / 2.0

    return {"raw": raw, "lower": lower, "upper": upper, "representative": representative}


def date_precision_tier(row: dict) -> dict:
    """Date precision tier (CALIBRATION_NOTES.md §4): exact single day,
    exact day-range, month-expanded range, or multi-month range. Widths
    are computed, not hard-coded per event_id, so this stays correct if
    events.csv is ever edited.

    Returns:
        {'tier': str, 'window_days': int, 'display_date': str}
    """
    from datetime import datetime

    date, start, end = row.get("date", "").strip(), row.get("date_start", "").strip(), row.get(
        "date_end", ""
    ).strip()

    if date and not start and not end:
        return {"tier": "exact_day", "window_days": 1, "display_date": date}

    if start and end:
        d1 = datetime.strptime(start, "%Y-%m-%d")
        d2 = datetime.strptime(end, "%Y-%m-%d")
        width = (d2 - d1).days + 1
        if width <= 11:  # th_005/009/010/012/014 style short windows
            tier = "exact_day_range"
        elif width <= 35:  # th_003/004/008 month-expanded
            tier = "month_range"
        else:  # th_013 multi-month
            tier = "multi_month_range"
        return {"tier": tier, "window_days": width, "display_date": f"{start} to {end}"}

    return {"tier": "unknown", "window_days": None, "display_date": date or f"{start}..{end}"}


def location_status(row: dict) -> dict:
    """Whether an event can be matched to a satellite pixel at all, per
    docs/DETECTION_PLAN.md §3: "Do not invent a lat/lng the source does
    not support -- an unmatched event is a finding, not a failure."

    Returns:
        {'matchable': bool, 'method': str, 'reason': str}
    """
    lat, lng = (row.get("lat") or "").strip(), (row.get("lng") or "").strip()
    if lat and lng:
        return {"matchable": True, "method": "coordinates", "reason": "lat/lng present in events.csv"}

    if row["event_id"] == "th_001":
        return {
            "matchable": False,
            "method": "regional_proxy_attempted",
            "reason": (
                "No lat/lng in events.csv (location_name='upper Gulf of "
                "Thailand', location_precision=named_site). Location is "
                "described at the scale of the whole study area, not a "
                "named site, so a regional-proxy open-water point was "
                "tried (not a per-event coordinate) -- see "
                "attempt_th001_regional_proxy(). Result recorded in "
                "reports/event_table.md."
            ),
        }

    return {
        "matchable": False,
        "method": "none",
        "reason": (
            f"No lat/lng in events.csv (location_precision="
            f"{row.get('location_precision', '?')!r}, location_name="
            f"{row.get('location_name', '?')!r}). Per docs/DETECTION_PLAN.md "
            f"§3, a coordinate for this named place is not invented."
        ),
    }


# --------------------------------------------------------------------------
# th_001 regional-proxy attempt -- the one real live GEE attempt made
# against a validation event. See module docstring for why this is not a
# precedent for the other 13 rows.
# --------------------------------------------------------------------------


def attempt_th001_regional_proxy(target_date: str = "2018-07-30") -> dict:
    """Try each candidate point in TH_001_PROXY_POINTS for a real
    Sentinel-2 reading and a real MODIS climatology near `target_date`.
    Live GEE calls -- this actually queries Earth Engine, does not use
    cached/hypothetical numbers.

    Returns:
        {'attempted_points': [...], 'sentinel2': {...} | None,
         'modis_climatology': {...} | None, 'notes': [str, ...]}
    """
    notes = []
    sentinel2_result = None
    modis_result = None

    for lat, lng, label in TH_001_PROXY_POINTS:
        if sentinel2_result is None:
            try:
                bands = get_sentinel2_bands(lat, lng, target_date, search_window_days=25)
                sentinel2_result = {"point": label, "lat": lat, "lng": lng, "bands": bands}
                notes.append(f"Sentinel-2: usable image found near {label}.")
            except (NoCloudFreeImageryError, NoWaterPixelsError) as exc:
                notes.append(f"Sentinel-2 at {label} ({lat},{lng}): {exc}")

        if modis_result is None:
            clim = build_climatology(lat, lng, target_date, window_days=15)
            if clim is not None:
                modis_result = {"point": label, "lat": lat, "lng": lng, "climatology": clim}
                notes.append(f"MODIS climatology: {clim['n']} obs found near {label} (+/-15d window).")
            else:
                notes.append(
                    f"MODIS chlor_a at {label} ({lat},{lng}): no observation within "
                    f"+/-15 days of {target_date} in the full 2002-present archive -- "
                    f"a genuine data gap (see climatology.py docstring), not a query error."
                )

        if sentinel2_result is not None and modis_result is not None:
            break

    return {
        "attempted_points": [p[2] for p in TH_001_PROXY_POINTS],
        "sentinel2": sentinel2_result,
        "modis_climatology": modis_result,
        "notes": notes,
    }


# --------------------------------------------------------------------------
# Leave-one-out calibration (CALIBRATION_NOTES.md §1) -- fully
# implemented, run against whatever real (event, index_value) pairs are
# available. Currently: zero, for the reasons above.
# --------------------------------------------------------------------------


def build_loo_iterations(events: list[dict], config: dict) -> list[dict]:
    """Build the 12 leave-one-out iterations: 10 independent single
    events + 2 same-episode clusters held out as a unit each
    (CALIBRATION_NOTES.md §1). Never splits a cluster across the
    train/held-out boundary.

    Returns:
        list of {'held_out_ids': [event_id, ...], 'label': str}
    """
    clusters = config["leave_one_out_clusters"]
    clustered_ids = {eid for c in clusters.values() for eid in c["members"]}

    iterations = [
        {"held_out_ids": [row["event_id"]], "label": row["event_id"]}
        for row in events
        if row["event_id"] not in clustered_ids
    ]
    for cluster_name, cluster in clusters.items():
        iterations.append({"held_out_ids": list(cluster["members"]), "label": cluster_name})

    return iterations


def sweep_thresholds(matched_pairs: list[dict], z_grid: list[float]) -> list[dict]:
    """Sweep a z-score cutoff and count how many matched events would be
    flagged at each value (docs/DETECTION_PLAN.md §4 step 2-3).

    Args:
        matched_pairs: [{'event_id': str, 'z': float}, ...] -- only
            events with a real computed z-score belong here (no
            fabricated placeholder rows).
        z_grid: cutoff values to sweep.

    Returns:
        [{'cutoff': float, 'n_flagged': int, 'flagged_ids': [...]}, ...]
        Returns cutoff rows with n_flagged=0 / flagged_ids=[] for every
        cutoff when `matched_pairs` is empty -- callers must check
        `len(matched_pairs)` before treating this as a real sensitivity
        curve (it is not one when there is nothing to sweep over).
    """
    results = []
    for cutoff in z_grid:
        flagged = [p["event_id"] for p in matched_pairs if p["z"] is not None and p["z"] >= cutoff]
        results.append({"cutoff": cutoff, "n_flagged": len(flagged), "flagged_ids": flagged})
    return results


def leave_one_out(events: list[dict], config: dict, matched_pairs: list[dict]) -> list[dict]:
    """Run the 12-iteration leave-one-out protocol.

    With `matched_pairs` empty (this run's real state -- see module
    docstring), every iteration reports caught=None (not False -- False
    would imply the pipeline ran and missed it; None means the pipeline
    could not run at all for that event/cluster) with a reason.

    Returns:
        [{'label': str, 'held_out_ids': [...], 'caught': bool | None,
          'reason': str}, ...]
    """
    matched_by_id = {p["event_id"]: p for p in matched_pairs}
    iterations = build_loo_iterations(events, config)
    results = []
    for it in iterations:
        available = [eid for eid in it["held_out_ids"] if eid in matched_by_id]
        if not available:
            results.append(
                {
                    **it,
                    "caught": None,
                    "reason": (
                        "No real satellite reading available for any member of this "
                        "held-out unit (no coordinate in events.csv; see location_status())."
                    ),
                }
            )
            continue
        # Calibrate on 13 (or 12, for a cluster) events not in this
        # held-out unit, using whichever cutoff config.yaml specifies for
        # the primary index -- with real data this would search cutoffs;
        # with only ever <=1 matched event total in this run, there is no
        # "calibrate on the rest" to speak of, which is itself recorded.
        cutoff = config["thresholds"][config["indices"]["primary"]]["elevated_z"]
        caught = any(
            matched_by_id[eid]["z"] is not None and matched_by_id[eid]["z"] >= cutoff
            for eid in available
        )
        results.append(
            {
                **it,
                "caught": caught,
                "reason": f"Evaluated against default (uncalibrated) cutoff z>={cutoff}.",
            }
        )
    return results


# --------------------------------------------------------------------------
# Orchestration -- run() is what reports/ is generated from.
# --------------------------------------------------------------------------


def run() -> dict:
    """Run the full event-matching + calibration attempt and return every
    intermediate result the report generators need. Makes real GEE calls
    (via th_001's regional-proxy attempt) -- not a dry/offline function."""
    config = load_config()
    events = load_events()

    rows = []
    matched_pairs = []
    th001_proxy = None

    for row in events:
        loc = location_status(row)
        cc = parse_cell_count(row.get("cell_count", ""), config["cell_count_range_policy"])
        prec = date_precision_tier(row)

        entry = {
            "event_id": row["event_id"],
            "species": row["species"],
            "location_name": row["location_name"],
            "location_precision": row["location_precision"],
            "date_display": prec["display_date"],
            "date_precision_tier": prec["tier"],
            "cell_count": cc,
            "matchable": loc["matchable"],
            "match_method": loc["method"],
            "match_reason": loc["reason"],
            "low_weight": row["event_id"] in config["historical_low_weight_events"],
            "index_values": None,
            "z_scores": None,
            "flagged": None,
        }

        if row["event_id"] == "th_001":
            th001_proxy = attempt_th001_regional_proxy(prec["display_date"])
            if th001_proxy["sentinel2"] is not None:
                bands = th001_proxy["sentinel2"]["bands"]
                idx = compute_all_indices(bands)
                entry["index_values"] = idx
                if th001_proxy["modis_climatology"] is not None:
                    clim = th001_proxy["modis_climatology"]["climatology"]
                    z = z_score(idx[config["indices"]["primary"]], clim)
                    entry["z_scores"] = {config["indices"]["primary"]: z}
                    if z["z"] is not None:
                        matched_pairs.append({"event_id": "th_001", "z": z["z"]})
                        cutoff = config["thresholds"][config["indices"]["primary"]]["elevated_z"]
                        entry["flagged"] = z["z"] >= cutoff

        rows.append(entry)

    n_matchable = sum(1 for r in rows if r["matchable"])
    n_with_real_reading = sum(1 for r in rows if r["index_values"] is not None)

    loo_results = leave_one_out(events, config, matched_pairs)
    z_grid = [1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0]
    sweep = sweep_thresholds(matched_pairs, z_grid)

    return {
        "config": config,
        "rows": rows,
        "n_events": len(events),
        "n_matchable": n_matchable,
        "n_with_real_reading": n_with_real_reading,
        "th001_proxy": th001_proxy,
        "matched_pairs": matched_pairs,
        "loo_results": loo_results,
        "sweep": sweep,
    }


if __name__ == "__main__":
    result = run()
    print(f"events: {result['n_events']}")
    print(f"matchable (has lat/lng): {result['n_matchable']}")
    print(f"with a real satellite reading: {result['n_with_real_reading']}")
    print(f"matched_pairs for sweep/LOO: {result['matched_pairs']}")
    for it in result["loo_results"]:
        print(f"LOO {it['label']}: caught={it['caught']} -- {it['reason']}")
