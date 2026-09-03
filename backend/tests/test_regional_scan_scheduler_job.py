"""Proves the regional-scan poll job is registered on the real scheduler
with the right interval and, critically, WITHOUT firing at startup
(spec §8) -- unlike refresh_grid, which deliberately does fire
immediately (next_run_time=now())."""

from __future__ import annotations

from src.config import REGIONAL_SCAN_POLL_INTERVAL_HOURS
from src.scheduler import create_scheduler


def test_poll_regional_scan_job_registered_without_immediate_fire():
    scheduler = create_scheduler()
    try:
        job = scheduler.get_job("poll_regional_scan")
        assert job is not None
        assert job.trigger.interval.total_seconds() == REGIONAL_SCAN_POLL_INTERVAL_HOURS * 3600
        assert job.max_instances == 1

        refresh_grid_job = scheduler.get_job("refresh_grid")
        # refresh_grid fires immediately at startup; poll_regional_scan
        # must not. poll_regional_scan deliberately has no next_run_time
        # override, so the attribute doesn't exist until the scheduler
        # starts (apscheduler 3.11.3 behavior, confirmed empirically) --
        # refresh_grid does have one (next_run_time=now()), so it exists
        # immediately. This is the real, precise distinction "does not
        # fire at startup" rests on.
        assert hasattr(refresh_grid_job, "next_run_time")
        assert not hasattr(job, "next_run_time")
    finally:
        # The scheduler is deliberately never started in this test (starting
        # it would let refresh_grid's next_run_time=now() job actually fire,
        # a live GEE call) -- shutdown() raises SchedulerNotRunningError on a
        # scheduler that was never started, so only call it if running.
        if scheduler.running:
            scheduler.shutdown(wait=False)
