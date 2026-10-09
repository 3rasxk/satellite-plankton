"""Build the TEST seasonal baseline artefact for the monitored grid (and the study polygon's cells).

    cd backend && EE_PROJECT_ID=... ./venv/bin/python ../scripts/build_test_baseline.py
    cd backend && ./venv/bin/python ../scripts/build_test_baseline.py --dry-run
    cd backend && EE_PROJECT_ID=... ./venv/bin/python ../scripts/build_test_baseline.py --level AB --replace

Data source: Sentinel-2 L2A surface reflectance via Google Earth Engine, one
NDCI history row per clear-sky scene per site, from
``data-pipeline/src/history.py`` (reached through the backend bridge, never
imported directly). The sites are ``backend/src/grid.py::MONITORED_GRID``.

What it does: fetches every site's history over ``[--start, --end)``, counts
distinct acquisition dates per site and per 3-month seasonal window, REFUSES
(``BuilderRefused``, exit code 2, nothing written) if any site/season holds
fewer than ``signal_anomaly.MIN_INDEPENDENT_DATES`` dates, otherwise replays
each site's history against itself (``baseline.self_check``) and writes
``backend/data/baselines/<version>/{manifest.json,sites.json}``
(``backend/src/baseline_store.py``). ``--dry-run`` fetches and prints counts,
and writes nothing. A version that already exists under ``--root`` (the same
build date and preprocessing signature) is REFUSED before anything is fetched
(``ArtifactExists``, exit code 2) unless ``--replace`` is given: a version
name must never silently identify different content.

Level B (``--level AB``, or ``--level B`` to add it to today's existing
Level A artefact, which needs ``--replace``): per-cell NDCI median / MAD /
date count over the study polygon at the production raster's scale
(``RASTER_SCAN_SCALE_M``), one file per season window (target month M =
1..12, months ``season_months(M)``), fetched in sequence from
``data-pipeline/src/baseline_raster.py`` (~30 s each live). History is
``[--start, --cell-end)``; ``--cell-end`` defaults to today - 15 days so the
baseline never contains a scene the served raster can still show, and the
manifest's ``level_b.history_end`` (the day before ``--cell-end``) is the
leakage cutoff: a cell is only ever assessed when acquired strictly later.
The whole build is REFUSED (exit 2, nothing written) at the first season in
which fewer than 90 % of the cells have n >= ``MIN_INDEPENDENT_DATES``, or
whose cells are off the production pixel grid or share a grid key.

Limitations (the output of this script is not a bloom claim):
  * TEST baseline: not calibrated against recorded bloom events. The
    self-check rates it prints describe how often the robust-z statistic flags
    the baseline's OWN past; they are not a detection accuracy or a false-alarm
    rate against anything observed in the water.
  * Rows are point-buffer means (~30 m disc) over clear-sky water pixels on
    cloud-free days only. Absence of a row is not evidence of an absent bloom,
    and a small or dispersed bloom can be missed. Turbid river-mouth water can
    raise NDCI with no bloom present.
  * A distinct acquisition date is counted once however many tiles cover the
    site that day.
  * A Level B cell is one sampled native pixel per day at the raster scale,
    not an area mean, and is only as clear-sky as that pixel was; river-mouth
    and shallow cells have wide, sediment-driven NDCI distributions.
"""

from __future__ import annotations

import argparse
import math
import subprocess
import sys
import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parents[1]
_BACKEND_DIR = _REPO_ROOT / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from src import _detection, _study_area, config  # noqa: E402
from src.baseline_store import (  # noqa: E402
    BASELINE_ROOT,
    MANIFEST_NAME,
    SITES_NAME,
    ArtifactExists,
    read_artifact,
    write_artifact,
)
from src.grid import MONITORED_GRID  # noqa: E402

DEFAULT_SITES = MONITORED_GRID

LEVELS = ("A", "B", "AB")
# Level B history ends (exclusive) this many days before the build date: one
# day more than the 14-day observation-age ceiling, so no scene the served
# raster can still show is part of the baseline it is compared with.
LEVEL_B_HISTORY_LAG_DAYS = 15
CELL_ARRAYS = ("lat", "lng", "median", "mad", "n")

# Fields kept per history row in sites.json. Anything else a fetcher returns
# (tags such as location_id, which the consumer attaches itself) is dropped.
ROW_FIELDS = ("acquisition_date", "ndci", "cloud_fraction", "scene_id")

_COUNT_KEYS = ("assessed", "watch", "high", "no_assessment")

FetchHistory = Callable[[float, float, str, str], list[dict]]
# (polygon, months, start, end, scale_m) -> (structured grid, distinct dates);
# see data-pipeline/src/baseline_raster.py::_fetch_cell_stats.
FetchCells = Callable[[tuple, tuple, str, str, int], tuple[np.ndarray, list[str]]]
Log = Callable[[str], None]


class BuilderRefused(Exception):
    """The history is too thin to declare a baseline; nothing was written."""


# --------------------------------------------------------------------------
# Counting
# --------------------------------------------------------------------------


def _usable_date(row: dict) -> date | None:
    """The row's date if the statistic could use the row, else None.

    Usable means a parseable ISO date and a finite numeric NDCI, the same
    rows ``signal_anomaly`` can draw a daily value from.
    """
    ndci = row.get("ndci")
    if isinstance(ndci, bool) or not isinstance(ndci, (int, float)) or not math.isfinite(ndci):
        return None
    try:
        return date.fromisoformat(str(row.get("acquisition_date")))
    except ValueError:
        return None


def site_stats(rows: list[dict]) -> dict:
    """Distinct-date counts for one site's rows.

    ``min_season_dates`` is the smallest, over the 12 target months, of the
    number of DISTINCT acquisition dates falling in ``season_months(month)``;
    ``weakest_season`` is the ``season_key`` where that minimum occurs (the
    earliest month on a tie). Several rows on one date count once.
    """
    logic = _detection.baseline_logic
    dates = {d for d in map(_usable_date, rows) if d is not None}
    per_month = Counter(d.month for d in dates)
    season_counts = {
        month: sum(per_month[m] for m in logic.season_months(month)) for month in range(1, 13)
    }
    weakest = min(season_counts, key=lambda month: (season_counts[month], month))
    return {
        "n_dates": len(dates),
        "min_season_dates": season_counts[weakest],
        "weakest_season": logic.season_key(weakest),
        "first": min(dates).isoformat() if dates else None,
        "last": max(dates).isoformat() if dates else None,
    }


def shortfalls(stats_by_site: dict[str, dict]) -> list[str]:
    """One message per site whose weakest season is under the activation floor."""
    floor = _detection.SIGNAL_ANOMALY_MIN_INDEPENDENT_DATES
    return [
        f"{site_id}: {stats['weakest_season']} has {stats['min_season_dates']} < {floor} "
        "independent dates"
        for site_id, stats in stats_by_site.items()
        if stats["min_season_dates"] < floor
    ]


# --------------------------------------------------------------------------
# Fetching and assembling
# --------------------------------------------------------------------------


def collect_history(
    sites: list[dict], *, start: str, end: str, fetch_history: FetchHistory
) -> dict[str, list[dict]]:
    """Fetch every site's rows over ``[start, end)``, trimmed and date-sorted."""
    rows_by_location: dict[str, list[dict]] = {}
    for site in sites:
        site_id = site["site_id"]
        if site_id in rows_by_location:
            raise BuilderRefused(f"{site_id}: listed more than once")
        rows = fetch_history(site["lat"], site["lng"], start, end)
        slim = [{field: row.get(field) for field in ROW_FIELDS} for row in rows]
        slim.sort(key=lambda r: (str(r["acquisition_date"]), str(r["scene_id"] or "")))
        rows_by_location[site_id] = slim
    return rows_by_location


def _add_counts(into: dict, counts: dict) -> None:
    for key in _COUNT_KEYS:
        into[key] += counts[key]
    for reason, n in counts["reasons"].items():
        into["reasons"][reason] = into["reasons"].get(reason, 0) + n


def aggregate_self_check(per_location: dict[str, dict]) -> dict:
    """Sum per-site self-checks per season key and in total.

    Per-site detail stays under ``per_location``. The sums are plain counts:
    a rate computed from them weights every assessed row equally, so a site
    with a longer history counts for more.
    """
    logic = _detection.baseline_logic

    def empty() -> dict:
        return {"assessed": 0, "watch": 0, "high": 0, "no_assessment": 0, "reasons": {}}

    by_season = {logic.season_key(month): empty() for month in range(1, 13)}
    total = empty()
    for check in per_location.values():
        for key, counts in check["by_season"].items():
            _add_counts(by_season[key], counts)
        _add_counts(total, check["total"])
    for counts in (*by_season.values(), total):
        counts["reasons"] = dict(sorted(counts["reasons"].items()))
    return {"by_season": by_season, "total": total, "per_location": per_location}


# --------------------------------------------------------------------------
# Level B: per-cell seasons
# --------------------------------------------------------------------------


def default_cell_end(today: date) -> str:
    """Exclusive end of the Level B history: ``today - LEVEL_B_HISTORY_LAG_DAYS``."""
    return (today - timedelta(days=LEVEL_B_HISTORY_LAG_DAYS)).isoformat()


def cell_season_check(month: int, cells: dict, scale_m: int) -> tuple[dict, str | None]:
    """The manifest entry for one season, and why it must be refused (or None).

    Refused when the season has no cell, when fewer than
    ``LEVEL_B_MIN_CELL_SHARE`` of its cells reach ``MIN_INDEPENDENT_DATES``,
    when its cells are off the production pixel grid (their keys would not
    match a raster cell's), or when two cells share a grid key.
    """
    logic = _detection.baseline_logic
    key = logic.season_key(month)
    floor = _detection.SIGNAL_ANOMALY_MIN_INDEPENDENT_DATES
    summary = logic.cell_season_summary(cells["n"], cells["mad"], floor=floor)
    stats = {
        "file": logic.cells_file_name(month),
        "months": list(logic.season_months(month)),
        **summary,
        "n_dates": cells["n_dates"],
        "first_date": cells["first_date"],
        "last_date": cells["last_date"],
    }
    share = logic.LEVEL_B_MIN_CELL_SHARE
    if summary["cells"] == 0:
        return stats, (
            f"{key}: no cell has a clear-sky observation "
            f"({cells['n_dates']} acquisition dates in the window)"
        )
    if not logic.cell_share_ok(summary["cells_n_ge_floor"], summary["cells"], share):
        return stats, (
            f"{key}: {summary['share_n_ge_floor']:.1%} of {summary['cells']} cells have "
            f"n >= {floor} independent dates (< {share:.0%} required)"
        )
    offset = logic.grid_offset_cells(cells["lat"], cells["lng"], scale_m)
    tolerance = logic.CELL_GRID_TOLERANCE_CELLS
    if offset > tolerance:
        return stats, (
            f"{key}: cells sit up to {offset:.3f} cells off the {scale_m} m production pixel "
            f"grid (tolerance {tolerance}); their keys would not match the raster's cells"
        )
    rows, cols = logic.cell_keys(cells["lat"], cells["lng"], scale_m)
    distinct = len(set(zip(rows.tolist(), cols.tolist())))
    if distinct != summary["cells"]:
        return stats, f"{key}: {summary['cells'] - distinct} cells share a grid key at {scale_m} m"
    return stats, None


def collect_cells(
    *,
    polygon,
    start: str,
    end: str,
    scale_m: int,
    fetch_cells: FetchCells | None,
    stop_on_refusal: bool = True,
    log: Log | None = None,
) -> tuple[dict[int, dict], dict[int, dict], list[str]]:
    """Fetch the twelve season windows in sequence (M = 1..12).

    Returns ``(cells_by_month, stats_by_month, problems)``. With
    ``stop_on_refusal`` the first refused season raises ``BuilderRefused``
    and no later season is fetched; without it (dry run) every season is
    fetched and the problems are returned. ``fetch_cells`` None means the
    live Earth Engine fetch.
    """
    logic = _detection.baseline_logic
    cells_by_month: dict[int, dict] = {}
    stats_by_month: dict[int, dict] = {}
    problems: list[str] = []
    for month in range(1, 13):
        key = logic.season_key(month)
        months = logic.season_months(month)
        if log:
            log(f"Level B {key} (months {list(months)}): per-cell NDCI statistics "
                f"{start} .. {end} (end exclusive) at {scale_m} m")
        began = time.monotonic()
        cells = _detection.build_cell_baseline(polygon, months, start, end, scale_m, _fetch=fetch_cells)
        stats, problem = cell_season_check(month, cells, scale_m)
        if log:
            log(f"  {key}: {stats['cells']} cells, {stats['share_n_ge_floor']:.1%} with n >= floor, "
                f"{stats['n_dates']} dates, {time.monotonic() - began:.0f} s")
        cells_by_month[month] = cells
        stats_by_month[month] = stats
        if problem:
            problems.append(problem)
            if stop_on_refusal:
                raise BuilderRefused(problem)
    return cells_by_month, stats_by_month, problems


def build(
    sites: list[dict],
    *,
    start: str,
    end: str,
    built_on: date,
    fetch_history: FetchHistory,
    git_sha: str | None,
    root: Path,
    built_at: str | None = None,
    replace: bool = False,
    level: str = "A",
    fetch_cells: FetchCells | None = None,
    cell_end: str | None = None,
    polygon=None,
    scale_m: int | None = None,
    log: Log | None = None,
) -> Path:
    """Fetch, check the floors, self-check, and write the artefact.

    ``level`` is ``"A"`` (sites only, the default), ``"AB"`` (sites and the
    twelve Level B seasons, one version) or ``"B"`` (Level B added to
    today's existing Level A artefact of the same version, whose manifest
    and rows are carried over unchanged; needs ``replace``).

    Raises ``BuilderRefused`` before anything is written (the output root is
    not even created) if there are no sites, any site/season holds fewer
    than ``MIN_INDEPENDENT_DATES`` distinct dates, or (Level B) any season
    fails ``cell_season_check``; for ``"B"`` also when there is no Level A
    artefact to add to. Raises ``ArtifactExists`` -- before anything is
    fetched -- when this version already exists under ``root`` and
    ``replace`` is False (always the case for ``"B"`` without it). Level A
    is fetched and checked before any Level B season. Level B history is
    ``[start, cell_end)``, ``cell_end`` defaulting to
    ``default_cell_end(built_on)``; ``polygon``/``scale_m`` default to the
    study polygon and ``config.RASTER_SCAN_SCALE_M`` (what the production
    raster uses). Returns the artefact directory.
    """
    if level not in LEVELS:
        raise ValueError(f"level must be one of {LEVELS}, got {level!r}")
    wants_a = "A" in level
    wants_b = "B" in level

    logic = _detection.baseline_logic
    # The version depends only on the build date and the live preprocessing,
    # so an existing one is refused here, not after a long GEE fetch.
    # write_artifact re-checks at write time.
    signature = logic.preprocessing_signature(_detection.preprocessing_params())
    version = logic.version_for(built_on, signature)
    existing = Path(root) / version
    if wants_a:
        if not sites:
            raise BuilderRefused("no sites to build a baseline for")
        if existing.exists() and not replace:
            raise ArtifactExists(existing)
    else:
        if not ((existing / MANIFEST_NAME).is_file() and (existing / SITES_NAME).is_file()):
            raise BuilderRefused(
                f"--level B adds Level B to today's Level A artefact {version}, which does not "
                f"exist under {root}; build both with --level AB"
            )
        if not replace:
            raise ArtifactExists(existing)

    if wants_b:
        cell_end = cell_end or default_cell_end(built_on)
        polygon = tuple(_study_area.STUDY_AREA_POLYGON_LATLNG if polygon is None else polygon)
        scale_m = config.RASTER_SCAN_SCALE_M if scale_m is None else scale_m
        if start >= cell_end:
            raise ValueError(f"start {start} must be before the Level B end {cell_end}")

    built_at = built_at or datetime.now(timezone.utc).isoformat(timespec="seconds")

    if wants_a:
        rows_by_location = collect_history(sites, start=start, end=end, fetch_history=fetch_history)
        stats = {site_id: site_stats(rows) for site_id, rows in rows_by_location.items()}

        problems = shortfalls(stats)
        if problems:
            raise BuilderRefused("; ".join(problems))

        params = _detection.preprocessing_params()
        per_location_check = {
            site_id: logic.self_check(rows, location_id=site_id, preprocessing_signature=signature)
            for site_id, rows in rows_by_location.items()
        }
        locations = {
            site["site_id"]: {
                "n_dates": stats[site["site_id"]]["n_dates"],
                "min_season_dates": stats[site["site_id"]]["min_season_dates"],
                "first": stats[site["site_id"]]["first"],
                "last": stats[site["site_id"]]["last"],
                "lat": site["lat"],
                "lng": site["lng"],
            }
            for site in sites
        }
        manifest = logic.build_manifest(
            baseline_version=version,
            built_at=built_at,
            history_start=min(info["first"] for info in locations.values()),
            history_end=max(info["last"] for info in locations.values()),
            preprocessing_signature=signature,
            preprocessing_params=params,
            locations=locations,
            self_check=aggregate_self_check(per_location_check),
            builder_git_sha=git_sha,
        )
    else:
        manifest, rows_by_location = read_artifact(existing)
        manifest = {key: value for key, value in manifest.items() if key != "level_b"}

    cells_by_file = None
    if wants_b:
        cells_by_month, stats_by_month, _ = collect_cells(
            polygon=polygon, start=start, end=cell_end, scale_m=scale_m,
            fetch_cells=fetch_cells, stop_on_refusal=True, log=log,
        )
        cell_params = _detection.cell_baseline_params(scale_m=scale_m, polygon_latlng=polygon)
        manifest["level_b"] = logic.build_level_b(
            scale_m=scale_m,
            cell_preprocessing_signature=logic.preprocessing_signature(cell_params),
            cell_preprocessing_params=cell_params,
            built_at=built_at,
            query_start=start,
            query_end_exclusive=cell_end,
            seasons={logic.season_key(m): stats_by_month[m] for m in range(1, 13)},
        )
        cells_by_file = {
            logic.cells_file_name(m): {name: cells_by_month[m][name] for name in CELL_ARRAYS}
            for m in range(1, 13)
        }
    return write_artifact(root, manifest, rows_by_location, replace=replace, cells_by_file=cells_by_file)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def current_git_sha() -> str | None:
    """Short HEAD commit of the repository, or None if git cannot say."""
    try:
        done = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() or None


def _iso_date(text: str) -> str:
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an ISO date (YYYY-MM-DD): {text!r}") from None


def _rate(part: int, whole: int) -> str:
    return f"{100.0 * part / whole:.1f}%" if whole else "n/a"


def _print_counts(stats_by_site: dict[str, dict]) -> None:
    floor = _detection.SIGNAL_ANOMALY_MIN_INDEPENDENT_DATES
    for site_id, stats in stats_by_site.items():
        status = "ok" if stats["min_season_dates"] >= floor else "BELOW FLOOR"
        print(
            f"  {site_id}: {stats['n_dates']} distinct dates "
            f"({stats['first'] or '-'} .. {stats['last'] or '-'}); "
            f"weakest season {stats['weakest_season']} = {stats['min_season_dates']} "
            f"(floor {floor}) {status}"
        )


def _print_self_check(manifest: dict) -> None:
    check = manifest["self_check"]
    print("Self-check (each history row assessed against that site's earlier rows only):")
    for site_id, per_site in check["per_location"].items():
        t = per_site["total"]
        print(
            f"  {site_id}: assessed {t['assessed']}, watch {t['watch']} "
            f"({_rate(t['watch'], t['assessed'])}), high {t['high']} "
            f"({_rate(t['high'], t['assessed'])}), no assessment {t['no_assessment']}"
        )
    t = check["total"]
    print(
        f"  ALL: assessed {t['assessed']}, watch {t['watch']} "
        f"({_rate(t['watch'], t['assessed'])}), high {t['high']} "
        f"({_rate(t['high'], t['assessed'])}), no assessment {t['no_assessment']} "
        f"{t['reasons']}"
    )
    print(
        "These rates describe the statistic on the baseline's own past. They are not a "
        "detection accuracy, and the baseline is not calibrated against recorded blooms."
    )


def _fmt(value, spec: str) -> str:
    return "-" if value is None else format(value, spec)


def _print_cell_stats(stats_by_month: dict[int, dict]) -> None:
    logic = _detection.baseline_logic
    share = logic.LEVEL_B_MIN_CELL_SHARE
    for month, stats in stats_by_month.items():
        ok = logic.cell_share_ok(stats["cells_n_ge_floor"], stats["cells"], share)
        print(
            f"  {logic.season_key(month)} (months {stats['months']}): {stats['cells']} cells, "
            f"{stats['share_n_ge_floor']:.1%} with n >= "
            f"{_detection.SIGNAL_ANOMALY_MIN_INDEPENDENT_DATES} "
            f"({'ok' if ok else 'BELOW FLOOR'}, need {share:.0%}); n median "
            f"{_fmt(stats['n_median'], '.0f')} [{_fmt(stats['n_min'], 'd')}..{_fmt(stats['n_max'], 'd')}]; "
            f"MAD p05/p50/p95 {_fmt(stats['mad_p05'], '.4f')}/{_fmt(stats['mad_p50'], '.4f')}/"
            f"{_fmt(stats['mad_p95'], '.4f')}; {stats['n_dates']} acquisition dates "
            f"({stats['first_date'] or '-'} .. {stats['last_date'] or '-'})"
        )


def _print_level_b(level_b: dict) -> None:
    logic = _detection.baseline_logic
    print(
        f"Level B (per-cell) TEST baseline at {level_b['scale_m']} m: history "
        f"{level_b['history_start']} .. {level_b['history_end']} -- only cells acquired after "
        f"{level_b['history_end']} may be assessed; cell signature "
        f"{level_b['cell_preprocessing_signature']}"
    )
    _print_cell_stats({
        month: level_b["seasons"][logic.season_key(month)] for month in range(1, 13)
    })


def main(
    argv: list[str] | None = None,
    *,
    fetch_history: FetchHistory | None = None,
    fetch_cells: FetchCells | None = None,
    sites: list[dict] | None = None,
    today: date | None = None,
) -> int:
    """CLI entry point; returns the process exit code (0 built, 2 refused --
    too little history, a Level B season under the cell floor, no Level A
    artefact for ``--level B``, or the version already exists without
    ``--replace``).

    ``fetch_history``, ``fetch_cells``, ``sites`` and ``today`` are test
    seams; the defaults are live Earth Engine, ``MONITORED_GRID`` and the
    current UTC date.
    """
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--start",
        type=_iso_date,
        default=_detection.SENTINEL2_SR_ARCHIVE_START_DATE,
        help="first date of history, inclusive (default: start of the Sentinel-2 SR archive)",
    )
    parser.add_argument(
        "--end",
        type=_iso_date,
        default=None,
        help="end of the Level A (site) history, EXCLUSIVE like Earth Engine filterDate "
        "(default: tomorrow, UTC)",
    )
    parser.add_argument(
        "--level",
        choices=LEVELS,
        default="A",
        help="A: the monitored sites (default); AB: sites and the per-cell seasons of the "
        "study polygon, one version; B: add the per-cell seasons to today's existing "
        "Level A artefact (needs --replace)",
    )
    parser.add_argument(
        "--cell-end",
        type=_iso_date,
        default=None,
        help=f"end of the Level B (cell) history, EXCLUSIVE (default: today - "
        f"{LEVEL_B_HISTORY_LAG_DAYS} days, UTC); the day before it is level_b.history_end",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=BASELINE_ROOT,
        help=f"directory holding baseline versions (default: {BASELINE_ROOT})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="fetch and print counts, write nothing",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="overwrite an existing artefact of the same version (same build date and "
        "preprocessing signature); without it such a build is refused",
    )
    args = parser.parse_args(argv)

    today = today or datetime.now(timezone.utc).date()
    end = args.end or (today + timedelta(days=1)).isoformat()
    cell_end = args.cell_end or default_cell_end(today)
    wants_a = "A" in args.level
    wants_b = "B" in args.level
    if wants_a and args.start >= end:
        parser.error(f"--start {args.start} must be before --end {end}")
    if wants_b and args.start >= cell_end:
        parser.error(f"--start {args.start} must be before --cell-end {cell_end}")
    sites = DEFAULT_SITES if sites is None else sites
    fetch = fetch_history if fetch_history is not None else _detection.get_ndci_history
    polygon = tuple(_study_area.STUDY_AREA_POLYGON_LATLNG)
    scale_m = config.RASTER_SCAN_SCALE_M

    def announced(lat: float, lng: float, start: str, stop: str) -> list[dict]:
        print(f"fetching NDCI history at ({lat}, {lng}) for {start} .. {stop}", file=sys.stderr, flush=True)
        return fetch(lat, lng, start, stop)

    def log(message: str) -> None:
        print(message, file=sys.stderr, flush=True)

    try:
        if args.dry_run:
            code = 0
            if wants_a:
                rows_by_location = collect_history(
                    sites, start=args.start, end=end, fetch_history=announced
                )
                stats = {site_id: site_stats(rows) for site_id, rows in rows_by_location.items()}
                print(f"Dry run: history {args.start} .. {end} (end exclusive); nothing written.")
                _print_counts(stats)
                problems = shortfalls(stats)
                if problems:
                    print("A real build would be refused: " + "; ".join(problems))
                    code = 2
            if wants_b:
                _, cell_stats, cell_problems = collect_cells(
                    polygon=polygon, start=args.start, end=cell_end, scale_m=scale_m,
                    fetch_cells=fetch_cells, stop_on_refusal=False, log=log,
                )
                print(
                    f"Dry run Level B: cell history {args.start} .. {cell_end} (end exclusive) at "
                    f"{scale_m} m; nothing written."
                )
                _print_cell_stats(cell_stats)
                if cell_problems:
                    print("A real build would be refused: " + "; ".join(cell_problems))
                    code = 2
            return code

        path = build(
            sites,
            start=args.start,
            end=end,
            built_on=today,
            fetch_history=announced,
            git_sha=current_git_sha(),
            root=args.root,
            replace=args.replace,
            level=args.level,
            fetch_cells=fetch_cells,
            cell_end=cell_end,
            polygon=polygon,
            scale_m=scale_m,
            log=log,
        )
    except BuilderRefused as exc:
        print(f"REFUSED, nothing written: {exc}", file=sys.stderr)
        return 2
    except ArtifactExists as exc:
        if args.level == "B":
            print(
                f"REFUSED, nothing written: --level B rewrites baseline version {exc.path.name} "
                f"at {exc.path} (its Level A part carried over unchanged, Level B added or "
                "replaced). A version must identify one content; re-run with --replace to do it.",
                file=sys.stderr,
            )
            return 2
        print(
            f"REFUSED, nothing written: baseline version {exc.path.name} already exists "
            f"at {exc.path}. A version must identify one content; re-run with --replace "
            "to overwrite it.",
            file=sys.stderr,
        )
        return 2

    manifest, rows_by_location = read_artifact(path)
    print(f"Wrote TEST baseline {manifest['baseline_version']} to {path}")
    print(
        f"history {manifest['history_start']} .. {manifest['history_end']}; "
        f"declared minimum_independent_dates = "
        f"{manifest['signal_anomaly']['minimum_independent_dates']}; "
        f"git {manifest['builder_git_sha'] or 'unknown'}"
    )
    _print_counts({site_id: site_stats(rows) for site_id, rows in rows_by_location.items()})
    _print_self_check(manifest)
    if "level_b" in manifest:
        _print_level_b(manifest["level_b"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
