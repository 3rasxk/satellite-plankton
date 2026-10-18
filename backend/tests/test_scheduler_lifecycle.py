"""Scheduler lifecycle regressions; all jobs are local and GEE-free."""

from __future__ import annotations

from datetime import datetime, timezone
from threading import Event

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi.testclient import TestClient

from src import main as main_module


def _without_database_startup(monkeypatch) -> None:
    monkeypatch.setattr(main_module, "init_db", lambda: None)
    monkeypatch.setattr(main_module, "ensure_monitored_sites", lambda: None)


def test_lifespan_does_not_create_a_scheduler_when_it_is_disabled(monkeypatch):
    """A direct TestClient must stay offline in the ordinary test process."""
    _without_database_startup(monkeypatch)
    monkeypatch.setattr(main_module, "SCHEDULER_ENABLED", False, raising=False)

    def forbidden_scheduler():
        raise AssertionError("disabled lifespan created the real scheduler")

    monkeypatch.setattr(main_module, "create_scheduler", forbidden_scheduler)

    with TestClient(main_module.app):
        pass


def test_lifespan_waits_for_a_running_job_before_teardown_returns(monkeypatch):
    """Regression for pytest exiting while an executor thread remains alive."""
    _without_database_startup(monkeypatch)
    monkeypatch.setattr(main_module, "SCHEDULER_ENABLED", True, raising=False)

    started = Event()
    release = Event()
    finished = Event()
    shutdown_wait_values = []

    def blocking_job() -> None:
        started.set()
        release.wait()
        finished.set()

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        blocking_job,
        "date",
        run_date=datetime.now(timezone.utc),
        id="controlled_blocking_job",
    )
    monkeypatch.setattr(main_module, "create_scheduler", lambda: scheduler)
    original_shutdown = scheduler.shutdown

    def tracked_shutdown(wait=True):
        assert started.is_set(), "shutdown began before the controlled job started"
        assert not finished.is_set(), "controlled job was no longer active at shutdown"
        shutdown_wait_values.append(wait)
        release.set()
        return original_shutdown(wait=wait)

    monkeypatch.setattr(scheduler, "shutdown", tracked_shutdown)

    try:
        with TestClient(main_module.app):
            assert started.wait(timeout=1), "controlled job never started"

        assert shutdown_wait_values == [True]
        assert finished.is_set(), (
            "lifespan returned while APScheduler still owned a running worker"
        )
    finally:
        release.set()
        assert finished.wait(timeout=1), "controlled worker did not exit during cleanup"
