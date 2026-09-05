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

HEADLINE FINDING, updated 2026-08-22 (see git commit d9811d7 and
data/validation/CALIBRATION_NOTES.md for the prior state): the human
maintainer has since sourced and confirmed real coordinates (from public
references, Wikipedia/Wikidata) for 7 of the 14 rows -- th_003, th_004,
th_006, th_008, th_010, th_012, th_014 -- with `location_precision`
changed from `named_site` to `coordinates`. The other 7
(th_001, th_002, th_005, th_007, th_009, th_011, th_013) remain
deliberately unmatched -- no coordinate is invented for a place name, per
CLAUDE.md and docs/DETECTION_PLAN.md §3.

This module now attempts a REAL Sentinel-2 + MODIS-climatology reading
for every one of those 7 coordinate-bearing rows (`attempt_satellite_reading`,
called generically for any matchable row -- not hand-written per event),
in addition to th_001's original regional-proxy attempt (kept, unchanged
in kind, since th_001 still has no coordinate of its own).

RESULT (live-tested 2026-08-22, revised 2026-09-05 after the water-mask
fix; see reports/event_table.md for the full per-event detail): 1 of
these 7 coordinate-bearing events produces a real matched
(index_value, z-score) pair -- th_010, which was previously counted a
failure because of the JRC water-mask defect (LIMITATIONS.md 5), not
because of anything about the site. The other six fail for six
DIFFERENT, DOCUMENTED reasons, not one blanket "no data":
  - th_003 (2009-03), th_008 (2010-07), th_012 (1981-02), th_014
    (1983-05): all predate Sentinel-2's launch (2015-06-23) -- there is
    structurally no Sentinel-2 scene to find, not a cloud/quality
    rejection. (Also: th_012/th_014 predate MODIS-Aqua's 2002 start, but
    MODIS climatology is a day-of-year pool across all archive years, so
    it is attempted anyway and can still return real numbers for the
    *seasonal* baseline even when the specific historical year cannot.)
  - th_004 (2016-01, Cha-am Coast): within the Sentinel-2 era but zero
    scenes were returned for the entire recorded month at this point --
    an early-era tiling/coverage gap for this specific location, not a
    cloud rejection.
  - th_006 (2019-08-27, Koh Loy): Sentinel-2 scenes exist (20 candidates
    in the searched window, confirmed by direct GEE query) but every one
    was cloud-rejected -- genuine, heavy monsoon-season cloud cover.
th_010 (2020-02-11..20, Ang Sila) was in that failure list until
2026-09-05, recorded as failing the JRC land/water mask at every radius
from 30 to 250 m and described as "a real site characteristic". That was
the water-mask defect in LIMITATIONS.md 5, not the site: JRC has no data
over open ocean and the mask read that as land. With the mask fixed it
returns real bands, and it is the one matched pair this run has. Its
coordinate was never moved to force a fit (CLAUDE.md: never
invent/adjust a coordinate to fit the pipeline).

MODIS climatology, attempted independently of the Sentinel-2 outcome for
every matchable row (a Sentinel-2 failure does not skip the climatology
attempt, so a partial result is visible rather than collapsed into one
boolean), DID succeed for th_004 (n=1, unreliable), th_010 (n=6,
reliable) and th_014 (n=10, reliable) even where Sentinel-2 failed --
this is reported per-event as a genuinely partial, not all-or-nothing,
result.

Together with th_001 (still 0/0, unchanged), the honest match count is
1 of 14 events with a full (index_value, z-score) pair: th_010, which
began producing one on 2026-09-05 after the JRC water-mask defect that
had been blocking it was fixed (LIMITATIONS.md 5). One pair is not a
calibration set -- `sweep_thresholds` and `leave_one_out` below run
against it and report per-event, but no cutoff is derived from it, and
th_010's own qualifiers (n=1, karenia_sp rather than the Noctiluca the
B2/B3 feature targets, and a reading that exists only via the ETOPO1
fallback over a turbid near-shore buffer) are recorded in LIMITATIONS.md
1 so it is never read as evidence in either direction.
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
    """Real Sentinel-2 index reading + real MODIS climatology anomaly at
    one (lat, lng, target_date). Used for every matchable events.csv row
    and for th_001's regional-proxy points alike.

    The Sentinel-2 attempt and the MODIS climatology attempt are made
    INDEPENDENTLY -- one failing does not skip the other -- so a genuinely
    partial result (e.g. a real climatology baseline but no usable
    Sentinel-2 scene) is visible in the report rather than collapsed into
    one boolean "matched"/"not matched" flag. z-scores are only computed,
    for every compared index, when BOTH halves succeeded.

    Returns:
        {'sentinel2_status': 'ok' | 'no_imagery' | 'no_water_pixels',
         'sentinel2_error': str | None,
         'index_values': dict | None, 'cloud_fraction': float | None,
         'actual_date': str | None,
         'climatology_status': 'ok' | 'no_data', 'climatology': dict | None,
         'z_scores': dict | None}  # per compared index, or None

    Raises:
        GEEAuthError: propagated, never caught (CLAUDE.md "never
        catch-and-fabricate").
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

    if result["index_values"] is not None and result["climatology"] is not None:
        # Every compared index (config.yaml indices.compare) plus the
        # secondary discrimination feature, all scored against the same
        # MODIS chlor_a climatology -- same math already used for th_001
        # in the prior phase, generalized here across indices rather than
        # computed for the primary index alone, so index_comparison.md
        # can show a real per-index comparison wherever a real reading
        # exists.
        index_names = list(
            dict.fromkeys(config["indices"]["compare"] + [config["indices"]["secondary_discrimination"]])
        )
        result["z_scores"] = {
            name: z_score(result["index_values"][name], result["climatology"]) for name in index_names
        }

    return result


# --------------------------------------------------------------------------
# th_001 regional-proxy attempt -- th_001 still has no coordinate of its
# own (location_name='upper Gulf of Thailand', a study-area-scale
# description, not a named site), so it alone still uses the
# multi-candidate-point regional-proxy approach below rather than
# `attempt_satellite_reading` (which needs one lat/lng, not a list of
# candidates). `run()` computes th_001's index values/z-scores across all
# compared indices the same way `attempt_satellite_reading` does for
# every other matchable row, just inline, since the source data
# (`th001_proxy['sentinel2']['bands']` / `['modis_climatology']`) comes
# from a different shape (best-of-N candidate points, not one point). See
# module docstring for why this is not a precedent for the other 6
# still-unmatched rows.
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


def leave_one_out(rows: list[dict], config: dict, matched_pairs: list[dict]) -> list[dict]:
    """Run the 12-iteration leave-one-out protocol.

    Cluster partial-match rule (data/validation/CALIBRATION_NOTES.md, new
    section appended 2026-08-22, alongside this run): th_005/th_006/th_007
    and th_009/th_010 are the same physical bloom observed at multiple
    sites (CALIBRATION_NOTES.md §1). Now that only ONE member of each
    cluster has a real coordinate (th_006 and th_010 respectively), a
    cluster is reported CAUGHT if ANY of its matchable members' real
    z-score crosses the primary index's cutoff -- not decided
    independently per member, and not required to be unanimous either.
    Reasoning: the cluster-mates are evidence about the SAME underlying
    event, not independent trials -- if the satellite would have flagged
    the bloom at th_006's pixel, that is evidence the system would have
    caught "the Aug 2019 Chonburi episode," even though th_005/th_007
    themselves have no coordinate to check directly. Requiring every
    member to independently cross the cutoff would effectively be
    scoring "did every observation site happen to have a coordinate AND
    cross the cutoff," a much stricter and less meaningful claim than
    "was this physical event detectable." A cluster member lacking a real
    z-score (no coordinate, or a coordinate but no usable satellite
    reading) is simply excluded from the OR -- it never counts as an
    independent miss on its own. `caught=None` only when EVERY member of
    the unit lacks a real z-score (nothing to evaluate at all).

    Returns:
        [{'label': str, 'held_out_ids': [...], 'caught': bool | None,
          'reason': str}, ...]
    """
    rows_by_id = {r["event_id"]: r for r in rows}
    matched_by_id = {p["event_id"]: p for p in matched_pairs}
    iterations = build_loo_iterations(rows, config)
    cutoff = config["thresholds"][config["indices"]["primary"]]["elevated_z"]

    results = []
    for it in iterations:
        held_out_ids = it["held_out_ids"]
        member_notes = []
        for eid in held_out_ids:
            if eid in matched_by_id:
                member_notes.append(f"{eid}: real z={matched_by_id[eid]['z']:.3f}")
                continue
            r = rows_by_id.get(eid, {})
            if not r.get("matchable"):
                member_notes.append(f"{eid}: no coordinate in events.csv")
            elif r.get("sentinel2_status") not in (None, "ok"):
                member_notes.append(
                    f"{eid}: coordinate present, no usable Sentinel-2 reading "
                    f"({r['sentinel2_status']})"
                )
            elif r.get("climatology_status") == "no_data":
                member_notes.append(
                    f"{eid}: coordinate present, Sentinel-2 reading obtained but no "
                    "MODIS climatology available for this location/date (archive gap)"
                )
            else:
                member_notes.append(f"{eid}: coordinate present, no real z-score obtained")

        available = [eid for eid in held_out_ids if eid in matched_by_id]
        member_detail = " | ".join(member_notes)

        if not available:
            results.append(
                {
                    **it,
                    "caught": None,
                    "reason": (
                        "No real satellite reading available for any member of this "
                        f"held-out unit. {member_detail}"
                    ),
                }
            )
            continue

        # Cluster partial-match rule (see docstring above): OR across
        # whichever matchable members produced a real z-score. For a
        # single-event iteration this is just that one event's own result.
        caught = any(matched_by_id[eid]["z"] >= cutoff for eid in available)
        cluster_note = (
            " Cluster rule: caught if ANY matchable member's z crosses the cutoff "
            "(same physical event, not independent trials)."
            if len(held_out_ids) > 1
            else ""
        )
        results.append(
            {
                **it,
                "caught": caught,
                "reason": (
                    f"Evaluated against default (uncalibrated) cutoff z>={cutoff}. "
                    f"{member_detail}.{cluster_note}"
                ),
            }
        )
    return results


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
    primary_index = config["indices"]["primary"]

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
            entry["z_scores"] = reading["z_scores"]

            if reading["z_scores"] is not None:
                z = reading["z_scores"][primary_index]["z"]
                if z is not None:
                    matched_pairs.append({"event_id": row["event_id"], "z": z})
                    cutoff = config["thresholds"][primary_index]["elevated_z"]
                    entry["flagged"] = z >= cutoff

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
                    clim = th001_proxy["modis_climatology"]["climatology"]
                    entry["climatology_status"] = "ok"
                    index_names = list(
                        dict.fromkeys(
                            config["indices"]["compare"] + [config["indices"]["secondary_discrimination"]]
                        )
                    )
                    entry["z_scores"] = {name: z_score(idx[name], clim) for name in index_names}
                    z = entry["z_scores"][primary_index]["z"]
                    if z is not None:
                        matched_pairs.append({"event_id": "th_001", "z": z})
                        cutoff = config["thresholds"][primary_index]["elevated_z"]
                        entry["flagged"] = z >= cutoff
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
