"""Pure-logic tests for src/config.py: the DATABASE_URL fallback switch
and the as_aware_utc helper.

`src/config.py` reads DATABASE_URL from the environment at *import* time
(module-level code, not inside a function) -- see its own docstring.
`src.config` is already imported (and cached in sys.modules) by the time
any test in this session runs, pinned to whatever DATABASE_URL
conftest.py set before collection -- monkeypatching os.environ afterwards
in this same process would not change anything already read. Each
fallback/passthrough variant is therefore exercised in a fresh
subprocess with its own controlled environment, per the brief's own
suggested approach; `as_aware_utc` is a pure function and is tested
directly, in-process."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.config import as_aware_utc

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_EXPECTED_FALLBACK_URL = f"sqlite:///{_BACKEND_DIR / 'data' / 'app.db'}"

_PROBE_SRC = (
    "import sys; sys.path.insert(0, {backend_dir!r})\n"
    "from src import config\n"
    "print(config.DATABASE_URL)\n"
    "print(config.USING_SQLITE_FALLBACK)\n"
).format(backend_dir=str(_BACKEND_DIR))


def _run_config_probe(database_url) -> tuple[str, bool]:
    """Runs `src/config.py`'s module-level DATABASE_URL logic in a fresh
    subprocess (same interpreter pytest itself is running under, so all
    of backend/venv's installed deps are available) with a controlled
    environment, and returns (DATABASE_URL, USING_SQLITE_FALLBACK)."""
    env = dict(os.environ)
    if database_url is None:
        env.pop("DATABASE_URL", None)
    else:
        env["DATABASE_URL"] = database_url

    result = subprocess.run(
        [sys.executable, "-c", _PROBE_SRC],
        capture_output=True,
        text=True,
        env=env,
        check=True,
        cwd=str(_BACKEND_DIR),
    )
    lines = result.stdout.strip().splitlines()
    assert len(lines) == 2, f"unexpected probe output: {result.stdout!r} / stderr: {result.stderr!r}"
    return lines[0], lines[1] == "True"


def test_unset_database_url_falls_back_to_sqlite():
    url, using_fallback = _run_config_probe(None)
    assert url == _EXPECTED_FALLBACK_URL
    assert using_fallback is True


def test_empty_string_database_url_falls_back_to_sqlite():
    url, using_fallback = _run_config_probe("")
    assert url == _EXPECTED_FALLBACK_URL
    assert using_fallback is True


def test_whitespace_only_database_url_falls_back_to_sqlite():
    url, using_fallback = _run_config_probe("   ")
    assert url == _EXPECTED_FALLBACK_URL
    assert using_fallback is True


def test_real_postgres_url_passes_through_unchanged():
    real_url = "postgresql+psycopg2://postgres:secret@db.example.supabase.co:5432/postgres"
    url, using_fallback = _run_config_probe(real_url)
    assert url == real_url
    assert using_fallback is False


def test_as_aware_utc_attaches_utc_to_naive_datetime():
    naive = datetime(2024, 3, 15, 12, 0, 0)
    result = as_aware_utc(naive)
    assert result.tzinfo is timezone.utc
    assert result.replace(tzinfo=None) == naive


def test_as_aware_utc_passes_through_aware_datetime_unchanged():
    ict = timezone(timedelta(hours=7))
    aware = datetime(2024, 3, 15, 12, 0, 0, tzinfo=ict)
    result = as_aware_utc(aware)
    assert result is aware  # untouched, not re-normalized to UTC
    assert result.tzinfo is ict


def test_as_aware_utc_none_returns_none():
    assert as_aware_utc(None) is None


def test_scheduler_is_enabled_by_default_and_can_be_disabled_for_tests():
    probe = (
        "import sys; sys.path.insert(0, {backend_dir!r})\n"
        "from src.config import SCHEDULER_ENABLED\n"
        "print(SCHEDULER_ENABLED)\n"
    ).format(backend_dir=str(_BACKEND_DIR))

    def run(value):
        env = dict(os.environ)
        if value is None:
            env.pop("SCHEDULER_ENABLED", None)
        else:
            env["SCHEDULER_ENABLED"] = value
        return subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            env=env,
            check=True,
            cwd=str(_BACKEND_DIR),
        ).stdout.strip()

    assert run(None) == "True"
    assert run("false") == "False"
    assert run("0") == "False"


def test_raster_scan_config_defaults():
    from src import config

    assert config.RASTER_SCAN_SCALE_M == 200
    assert config.RASTER_SCAN_POLL_INTERVAL_HOURS == 1  # latest-scene policy; was 3
    assert config.RASTER_SCAN_COOLDOWN_HOURS == 20
    assert config.RASTER_SCAN_POLL_LOOKBACK_DAYS == 10


def test_regional_scan_tables_created(client):
    from sqlalchemy import inspect

    from src.db import engine

    tables = inspect(engine).get_table_names()
    assert "regional_scan_runs" in tables
    assert "regional_scan_points" in tables
    assert "regional_scan_clusters" in tables
