"""
Manual trigger for one regional scan, without waiting on the poll/
cooldown cycle -- provides a manual-
trigger pattern (docs/superpowers/specs/2026-08-31-regional-scan-design.md
§8). Makes real, live Sentinel-2 reads for every point in the current
study-area polygon (about 9,100 at 5 km). A full run can take hours;
progress is logged every 100 points and the cache updates on completion.

    cd backend && source venv/bin/activate && python scripts/run_regional_scan.py [--date YYYY-MM-DD] [--spacing-km 5]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from src.config import REGIONAL_SCAN_GRID_SPACING_KM, today_str  # noqa: E402
from src.db import SessionLocal, init_db  # noqa: E402
from src.regional_scan.scan import run_scan  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=None, help="YYYY-MM-DD, defaults to today (UTC)")
    parser.add_argument(
        "--spacing-km", type=float, default=REGIONAL_SCAN_GRID_SPACING_KM,
        help=f"grid spacing in km (default {REGIONAL_SCAN_GRID_SPACING_KM})",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    init_db()
    db = SessionLocal()
    try:
        run = run_scan(db, args.date or today_str(), args.spacing_km)
        print(
            f"run {run.id}: status={run.status} total_points={run.total_points} "
            f"ok={run.count_ok} no_imagery={run.count_no_imagery} "
            f"no_water_pixels={run.count_no_water_pixels} "
            f"no_climatology={run.count_no_climatology} error={run.count_error}"
        )
        if run.status == "error":
            sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
