"""
Validation-event index readings and disabled threshold calibration.

Data source: canonical data/validation/events.csv, Sentinel-2 spectral
indices, and independent MODIS chlor_a climatology context through the
existing namespaced data-pipeline bridge. MODIS concentrations are not a
valid baseline for any of the spectral indices. No anomaly statistic is
computed, and every event and held-out unit is unevaluable.

Read data/validation/CALIBRATION_NOTES.md for event grouping, species,
historical evidentiary weight, date precision and cell-count handling.
Real coordinates remain unmodified; th_001 alone retains its documented
regional-proxy attempt. A real Sentinel-2 reading exists for th_010 after
the water-mask fix, but it supplies no valid z-score or hit/miss result.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Literal

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
from climatology import build_climatology  # noqa: E402
from indices import compute_all_indices  # noqa: E402

EVENTS_CSV = _REPO_ROOT / "data" / "validation" / "events.csv"
CONFIG_PATH = _THIS_DIR / "config.yaml"

ZScoreStatus = Literal["not_computed_no_valid_baseline"]
Z_SCORE_STATUS: ZScoreStatus = "not_computed_no_valid_baseline"
Z_SCORE_REASON = "Not computed — no valid baseline exists for the spectral indices."

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
# Generalized real satellite-reading attempt -- used for every matchable
# row (a real lat/lng in events.csv), i.e. the 7 rows added 2026-08-22.
# Not hand-written per event: one function, called the same way for every
# coordinate-bearing row, so no event's search window or buffer is
# individually tuned to force a match.
# --------------------------------------------------------------------------

# Uniform cloud-search margin applied on top of every event's own recorded
# date window (never hand-picked per event). Matches the 25-day window
# originally used for th_001's regional-proxy attempt, so an event with an
# exact single-day date gets exactly the same search generosity th_001 got.
SEARCH_WINDOW_CLOUD_MARGIN_DAYS = 25


def event_search_window(row: dict, prec: dict) -> tuple[str, int]:
    """(target_date, search_window_days) for get_sentinel2_bands, derived
    only from the event's own recorded date precision
    (CALIBRATION_NOTES.md §4) -- never hand-tuned per event to force a
    match.

    - exact_day (a single recorded date): that date itself, +/-
      SEARCH_WINDOW_CLOUD_MARGIN_DAYS.
    - any date range (exact_day_range / month_range / multi_month_range):
      the midpoint of date_start..date_end, with a search radius wide
      enough to cover the *entire* recorded range plus the same cloud
      margin on top -- so a source-recorded month-wide window (e.g.
      th_004) gets a wider search only because the source itself is less
      precise about the date, exactly the CALIBRATION_NOTES.md §4
      precision-tier tradeoff (wider window = more chance of a cloud-free
      scene, weaker claim that the scene coincides with peak bloom).
    """
    date = (row.get("date") or "").strip()
    start = (row.get("date_start") or "").strip()
    end = (row.get("date_end") or "").strip()

    if date and not start and not end:
        return date, SEARCH_WINDOW_CLOUD_MARGIN_DAYS

    from datetime import datetime as _dt

    d1 = _dt.strptime(start, "%Y-%m-%d")
    d2 = _dt.strptime(end, "%Y-%m-%d")
    midpoint = d1 + (d2 - d1) / 2
    half_width_days = max((d2 - d1).days // 2, 0)
    search_window_days = half_width_days + SEARCH_WINDOW_CLOUD_MARGIN_DAYS
    return midpoint.strftime("%Y-%m-%d"), search_window_days


def attempt_satellite_reading(
    lat: float, lng: float, target_date: str, search_window_days: int, config: dict
) -> dict:
    """Read indices and independent MODIS chlor_a climatology context.

    Both sources are attempted independently to retain partial availability.
    The chlor_a baseline is in mg/m^3 and cannot standardize these indices.
    z_scores is always None; z_score_status records that no valid baseline
    exists, even if both data sources returned real measurements.
    GEEAuthError propagates without fabrication.
    """
    result: dict = {
        "sentinel2_status": None,
        "sentinel2_error": None,
        "index_values": None,
        "cloud_fraction": None,
        "actual_date": None,
        "climatology_status": None,
        "climatology": None,
        "z_scores": None,
        "z_score_status": Z_SCORE_STATUS,
    }

    try:
        bands = get_sentinel2_bands(lat, lng, target_date, search_window_days=search_window_days)
        result["sentinel2_status"] = "ok"
        result["cloud_fraction"] = bands.get("cloud_fraction")
        result["actual_date"] = bands.get("actual_date")
        result["index_values"] = compute_all_indices(bands)
    except NoCloudFreeImageryError as exc:
        result["sentinel2_status"] = "no_imagery"
        result["sentinel2_error"] = str(exc)
    except NoWaterPixelsError as exc:
        result["sentinel2_status"] = "no_water_pixels"
        result["sentinel2_error"] = str(exc)

    clim = build_climatology(lat, lng, target_date, window_days=config["climatology"]["window_days"])
    if clim is None:
        result["climatology_status"] = "no_data"
    else:
        result["climatology_status"] = "ok"
        result["climatology"] = clim


    return result


# --------------------------------------------------------------------------
# th_001 regional-proxy attempt -- th_001 still has no coordinate of its
# own (location_name='upper Gulf of Thailand', a study-area-scale
# description, not a named site), so it alone still uses the
# multi-candidate-point regional-proxy approach below rather than
# `attempt_satellite_reading` (which needs one lat/lng, not a list of
# candidates). run() retains real index values and the independent MODIS
# context, with anomaly scoring explicitly disabled for this path too.
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
# disabled until a valid statistic and baseline exist.
# --------------------------------------------------------------------------


def build_loo_iterations(events: list[dict], config: dict) -> list[dict]:
    """Build the 11 leave-one-out iterations: 9 independent single
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
    """Disabled: no sensitivity counts can be computed without a valid statistic.

    Keep the callable shape for future calibration work. Ignore supplied
    pairs, which may contain legacy invalid scores, and report no counts.
    """
    return [
        {
            "cutoff": cutoff,
            "n_flagged": None,
            "flagged_ids": None,
            "z_score_status": Z_SCORE_STATUS,
            "reason": Z_SCORE_REASON,
        }
        for cutoff in z_grid
    ]


def leave_one_out(rows: list[dict], config: dict, matched_pairs: list[dict]) -> list[dict]:
    """Report every held-out unit as unevaluable until a valid baseline exists.

    Preserve same-episode grouping and the callable shape, but never accept
    legacy matched_pairs as valid evidence for a caught/missed conclusion.
    """
    return [
        {
            **iteration,
            "caught": None,
            "z_score_status": Z_SCORE_STATUS,
            "reason": f"Cannot be evaluated. {Z_SCORE_REASON}",
        }
        for iteration in build_loo_iterations(rows, config)
    ]


# --------------------------------------------------------------------------
# Orchestration -- run() is what reports/ is generated from.
# --------------------------------------------------------------------------


def run() -> dict:
    """Run the full event-matching + calibration attempt and return every
    intermediate result the report generators need. Makes real GEE calls
    -- for every matchable row (7, as of 2026-08-22) plus th_001's
    regional-proxy attempt -- not a dry/offline function."""
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
            "lat": None,
            "lng": None,
            "target_date": None,
            "search_window_days": None,
            "sentinel2_status": None,
            "sentinel2_error": None,
            "climatology_status": None,
            "cloud_fraction": None,
            "actual_date": None,
            "index_values": None,
            "z_scores": None,
            "z_score_status": Z_SCORE_STATUS,
            "flagged": None,
        }

        if loc["matchable"]:
            # Real coordinate in events.csv (7 rows as of 2026-08-22) --
            # one generic call, same for every one of them.
            lat, lng = float(row["lat"]), float(row["lng"])
            entry["lat"] = lat
            entry["lng"] = lng
            target_date, search_window_days = event_search_window(row, prec)
            entry["target_date"] = target_date
            entry["search_window_days"] = search_window_days

            reading = attempt_satellite_reading(lat, lng, target_date, search_window_days, config)
            entry["sentinel2_status"] = reading["sentinel2_status"]
            entry["sentinel2_error"] = reading["sentinel2_error"]
            entry["climatology_status"] = reading["climatology_status"]
            entry["cloud_fraction"] = reading["cloud_fraction"]
            entry["actual_date"] = reading["actual_date"]
            entry["index_values"] = reading["index_values"]
            entry["z_score_status"] = reading["z_score_status"]


        elif row["event_id"] == "th_001":
            # th_001 has no coordinate of its own -- unchanged
            # multi-candidate-point regional-proxy approach.
            th001_proxy = attempt_th001_regional_proxy(prec["display_date"])
            if th001_proxy["sentinel2"] is not None:
                bands = th001_proxy["sentinel2"]["bands"]
                idx = compute_all_indices(bands)
                entry["index_values"] = idx
                entry["sentinel2_status"] = "ok"
                entry["cloud_fraction"] = bands.get("cloud_fraction")
                entry["actual_date"] = bands.get("actual_date")

                if th001_proxy["modis_climatology"] is not None:
                    entry["climatology_status"] = "ok"
                else:
                    entry["climatology_status"] = "no_data"
            else:
                entry["sentinel2_status"] = "no_imagery"

        rows.append(entry)

    n_matchable = sum(1 for r in rows if r["matchable"])
    n_with_real_reading = sum(1 for r in rows if r["index_values"] is not None)

    loo_results = leave_one_out(rows, config, matched_pairs)
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
