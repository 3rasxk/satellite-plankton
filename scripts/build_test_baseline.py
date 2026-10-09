"""Build the TEST seasonal baseline artefact for the monitored grid.

    cd backend && EE_PROJECT_ID=... ./venv/bin/python ../scripts/build_test_baseline.py
    cd backend && ./venv/bin/python ../scripts/build_test_baseline.py --dry-run

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
and writes nothing.

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
"""

from __future__ import annotations

import argparse
import math
import subprocess
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

_REPO_ROOT = Path(__file__).resolve().parents[1]
_BACKEND_DIR = _REPO_ROOT / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from src import _detection  # noqa: E402
from src.baseline_store import BASELINE_ROOT, read_artifact, write_artifact  # noqa: E402
from src.grid import MONITORED_GRID  # noqa: E402

DEFAULT_SITES = MONITORED_GRID

# Fields kept per history row in sites.json. Anything else a fetcher returns
# (tags such as location_id, which the consumer attaches itself) is dropped.
ROW_FIELDS = ("acquisition_date", "ndci", "cloud_fraction", "scene_id")

_COUNT_KEYS = ("assessed", "watch", "high", "no_assessment")

FetchHistory = Callable[[float, float, str, str], list[dict]]


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
) -> Path:
    """Fetch, check the floor, self-check, and write the artefact.

    Raises ``BuilderRefused`` before anything is written (the output root is
    not even created) if there are no sites or any site/season holds fewer
    than ``MIN_INDEPENDENT_DATES`` distinct dates. Returns the artefact
    directory.
    """
    if not sites:
        raise BuilderRefused("no sites to build a baseline for")

    logic = _detection.baseline_logic
    rows_by_location = collect_history(sites, start=start, end=end, fetch_history=fetch_history)
    stats = {site_id: site_stats(rows) for site_id, rows in rows_by_location.items()}

    problems = shortfalls(stats)
    if problems:
        raise BuilderRefused("; ".join(problems))

    params = _detection.preprocessing_params()
    signature = logic.preprocessing_signature(params)

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
        baseline_version=logic.version_for(built_on, signature),
        built_at=built_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        history_start=min(info["first"] for info in locations.values()),
        history_end=max(info["last"] for info in locations.values()),
        preprocessing_signature=signature,
        preprocessing_params=params,
        locations=locations,
        self_check=aggregate_self_check(per_location_check),
        builder_git_sha=git_sha,
    )
    return write_artifact(root, manifest, rows_by_location)


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


def main(
    argv: list[str] | None = None,
    *,
    fetch_history: FetchHistory | None = None,
    sites: list[dict] | None = None,
    today: date | None = None,
) -> int:
    """CLI entry point; returns the process exit code (0 built, 2 refused).

    ``fetch_history``, ``sites`` and ``today`` are test seams; the defaults
    are live Earth Engine, ``MONITORED_GRID`` and the current UTC date.
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
        help="end of history, EXCLUSIVE like Earth Engine filterDate (default: tomorrow, UTC)",
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
    args = parser.parse_args(argv)

    today = today or datetime.now(timezone.utc).date()
    end = args.end or (today + timedelta(days=1)).isoformat()
    if args.start >= end:
        parser.error(f"--start {args.start} must be before --end {end}")
    sites = DEFAULT_SITES if sites is None else sites
    fetch = fetch_history if fetch_history is not None else _detection.get_ndci_history

    def announced(lat: float, lng: float, start: str, stop: str) -> list[dict]:
        print(f"fetching NDCI history at ({lat}, {lng}) for {start} .. {stop}", file=sys.stderr, flush=True)
        return fetch(lat, lng, start, stop)

    try:
        if args.dry_run:
            rows_by_location = collect_history(
                sites, start=args.start, end=end, fetch_history=announced
            )
            stats = {site_id: site_stats(rows) for site_id, rows in rows_by_location.items()}
            print(f"Dry run: history {args.start} .. {end} (end exclusive); nothing written.")
            _print_counts(stats)
            problems = shortfalls(stats)
            if problems:
                print("A real build would be refused: " + "; ".join(problems))
                return 2
            return 0

        path = build(
            sites,
            start=args.start,
            end=end,
            built_on=today,
            fetch_history=announced,
            git_sha=current_git_sha(),
            root=args.root,
        )
    except BuilderRefused as exc:
        print(f"REFUSED, nothing written: {exc}", file=sys.stderr)
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
