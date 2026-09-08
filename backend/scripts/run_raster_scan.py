"""Run one whole-polygon raster scan from the command line.

    cd backend && ./venv/bin/python scripts/run_raster_scan.py [--date YYYY-MM-DD] [--scale-m 200]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from src.config import RASTER_SCAN_SCALE_M, today_str  # noqa: E402
from src.db import SessionLocal, init_db  # noqa: E402
from src.raster_scan.scan import (  # noqa: E402
    ConcurrentRasterScanError,
    run_raster_scan,
)
from src.raster_scan.storage import apply_retention  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=None, help="YYYY-MM-DD, defaults to today (UTC)")
    parser.add_argument(
        "--scale-m", type=int, default=RASTER_SCAN_SCALE_M,
        help=f"raster sampling interval in metres (default {RASTER_SCAN_SCALE_M})",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="start despite another run marked running; use only when it is known dead",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    init_db()
    with SessionLocal() as db:
        try:
            run = run_raster_scan(
                db,
                args.date or today_str(),
                scale_m=args.scale_m,
                allow_concurrent=args.force,
            )
        except ConcurrentRasterScanError as exc:
            print(f"refusing to start: {exc}", file=sys.stderr)
            raise SystemExit(2) from exc

        print(
            f"run {run.id}: status={run.status} cells={run.cell_count or 0} "
            f"scenes={run.scene_count or 0} "
            f"scene_range={run.oldest_scene_date or '-'}..{run.newest_scene_date or '-'}"
        )
        apply_retention(db)
        if run.status == "error":
            raise SystemExit(1)


if __name__ == "__main__":
    main()
