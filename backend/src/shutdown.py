"""
Cooperative stop flag for long-running background jobs.

Data source: none -- process-local state only. Limitation: APScheduler
cannot interrupt a job that is already running, so this flag only takes
effect at a job's next checkpoint (between grid sites in
scheduler.refresh_grid, between archive windows in a raster bootstrap,
before a raster poll). A single in-flight GEE request still runs to its
own deadline (data-pipeline auth.py) before the job can notice the flag.

main.py's lifespan sets the flag before scheduler.shutdown(wait=True) and
clears it at startup, as does create_scheduler(), so a test or a
--reload restart never inherits a stale stop request.
"""

from __future__ import annotations

import threading

_STOP_REQUESTED = threading.Event()


def request_stop() -> None:
    """Ask every running job to end at its next checkpoint."""
    _STOP_REQUESTED.set()


def clear_stop() -> None:
    """Reset the flag (startup, or a test cleaning up after itself)."""
    _STOP_REQUESTED.clear()


def stop_requested() -> bool:
    return _STOP_REQUESTED.is_set()
