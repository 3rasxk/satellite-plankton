"""Raster polling and retention jobs are scheduled without startup execution."""

from src.config import RASTER_SCAN_POLL_INTERVAL_HOURS
from src.scheduler import create_scheduler


def test_raster_jobs_are_registered_without_immediate_fire():
    scheduler = create_scheduler()
    try:
        poll = scheduler.get_job("poll_raster_scan")
        retention = scheduler.get_job("expire_raster_scans")
        refresh = scheduler.get_job("refresh_grid")
        assert poll.trigger.interval.total_seconds() == RASTER_SCAN_POLL_INTERVAL_HOURS * 3600
        assert retention.trigger.interval.total_seconds() == 24 * 3600
        assert poll.max_instances == retention.max_instances == 1
        assert hasattr(refresh, "next_run_time")
        assert not hasattr(poll, "next_run_time")
        assert not hasattr(retention, "next_run_time")
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)
