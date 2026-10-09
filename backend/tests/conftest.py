"""
Shared pytest fixtures for backend/tests/.

`backend/src/config.py` reads `DATABASE_URL` from the environment at
*import* time (module-level code, not inside a function) -- see its own
docstring. That means the isolated test DB must be picked before
`src.main` (or anything importing `src.config`/`src.db`) is imported
anywhere in this test session, including by this file. This must never
resolve to `backend/data/app.db`, the real dev DB (CLAUDE.md-adjacent
build-report instruction: tests must not write into it).
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

_TEST_DB_DIR = tempfile.mkdtemp(prefix="backend_pytest_")
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_DIR}/test.db"
# A TestClient runs the application's real lifespan. Disable scheduled
# jobs at the application boundary for the entire pytest process so a
# test cannot accidentally reach GEE merely by constructing its own
# client fixture.
os.environ["SCHEDULER_ENABLED"] = "false"
# The TEST baseline gate is opt-in per test (monkeypatch config.BASELINE_MODE);
# never let a developer's backend/.env enable it for the whole suite.
os.environ["BASELINE_MODE"] = "off"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src import main as main_module  # noqa: E402


def pytest_addoption(parser):
    parser.addoption(
        "--live-gee",
        action="store_true",
        default=False,
        help="run tests that contact the real Google Earth Engine service",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "live_gee: contacts the real Google Earth Engine service"
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--live-gee"):
        return
    offline = pytest.mark.skip(reason="requires --live-gee")
    for item in items:
        if "live_gee" in item.keywords:
            item.add_marker(offline)


@pytest.fixture()
def client():
    """TestClient wired to the isolated SQLite file above (never
    backend/data/app.db), with scheduling disabled process-wide so
    merely constructing any TestClient never triggers a live GEE call.
    Triggers real startup (init_db/ensure_monitored_sites) and shutdown
    events each test -- both are idempotent, so re-running is safe."""
    with TestClient(main_module.app) as c:
        yield c
