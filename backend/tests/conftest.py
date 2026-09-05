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

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src import main as main_module  # noqa: E402


class _NoopScheduler:
    """Stand-in for APScheduler's BackgroundScheduler. `src/main.py`'s
    `on_startup` calls `.start()`/`.shutdown()` on whatever
    `create_scheduler()` returns; in tests the *real* scheduler must
    never fire `refresh_grid()` (a live GEE call, `next_run_time=now()`)
    just because a TestClient was constructed. GEEAuthError-forcing
    tests patch `bridge.*` directly instead -- this stub only stops the
    unrelated background job from firing during unrelated tests."""

    def start(self) -> None:
        pass

    def shutdown(self, wait: bool = False) -> None:
        pass


@pytest.fixture()
def client(monkeypatch):
    """TestClient wired to the isolated SQLite file above (never
    backend/data/app.db), with the scheduler swapped for a no-op so
    merely constructing the client never triggers a live GEE call.
    Triggers real startup (init_db/ensure_monitored_sites) and shutdown
    events each test -- both are idempotent, so re-running is safe."""
    monkeypatch.setattr(main_module, "create_scheduler", lambda: _NoopScheduler())
    with TestClient(main_module.app) as c:
        yield c
