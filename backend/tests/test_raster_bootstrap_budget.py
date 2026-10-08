"""F8: bootstrap wall-clock budget. Injected clock, synthetic imagery, no GEE."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import delete, select

from src import config as config_module
from src.db import SessionLocal
from src.db_models import RasterScanRun
from src.raster_scan import scan as scan_module
from src.raster_scan import storage

_BACKEND_DIR = Path(__file__).resolve().parent.parent


def _clear(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "RASTER_BLOB_ROOT", tmp_path)
    with SessionLocal() as db:
        db.execute(delete(RasterScanRun))
        db.commit()


def test_budget_default_is_below_the_stale_run_threshold():
    assert 0 < config_module.RASTER_BOOTSTRAP_BUDGET_MINUTES < scan_module.STALE_RUN_HOURS * 60


def test_bootstrap_stops_at_budget_with_an_honest_error_not_ok(client, tmp_path, monkeypatch):
    _clear(tmp_path, monkeypatch)
    monkeypatch.setattr(config_module, "RASTER_BOOTSTRAP_BUDGET_MINUTES", 45)
    clock = {"now": 0.0}
    monkeypatch.setattr(scan_module, "_monotonic", lambda: clock["now"])
    calls = []

    def build(_polygon, target_date, max_scene_age_days=None):
        calls.append(target_date)
        clock["now"] += 20 * 60  # every window costs 20 simulated minutes
        raise scan_module.bridge.NoCloudFreeImageryError("cloudy window")

    monkeypatch.setattr(scan_module.bridge, "build_index_composite", build)

    with SessionLocal() as db:
        run = scan_module.run_raster_scan(db, "2026-09-06")
        running = db.execute(
            select(RasterScanRun).where(RasterScanRun.status == "running")
        ).scalars().all()

    # 0 -> 20 -> 40 min: three windows start under budget; the check before
    # the fourth sees 60 min >= 45 and stops.
    assert len(calls) == 3
    assert run.status == "error"
    assert run.status != "ok"
    assert "budget" in run.reason
    assert "archive" in run.reason
    assert running == []
    assert run.blob_path is None
    metadata = run.source_metadata
    assert metadata["search_stopped"] == "budget"
    assert len(metadata["searched_windows"]) == 3
    # The span actually searched is stated, never the full archive.
    assert metadata["search_range"]["window_start"] > metadata["archive_start_date"]


def test_usable_window_inside_budget_still_succeeds(client, tmp_path, monkeypatch):
    _clear(tmp_path, monkeypatch)
    monkeypatch.setattr(config_module, "RASTER_BOOTSTRAP_BUDGET_MINUTES", 45)
    clock = {"now": 0.0}
    monkeypatch.setattr(scan_module, "_monotonic", lambda: clock["now"])
    from tests.test_raster_scan_bootstrap import _arrays, _composite

    def build(_polygon, target_date, max_scene_age_days=None):
        clock["now"] += 20 * 60
        return _composite(target_date, max_scene_age_days, "scene", 1787196600000)

    monkeypatch.setattr(scan_module.bridge, "build_index_composite", build)
    monkeypatch.setattr(
        scan_module.bridge, "download_composite_arrays", lambda c, scale_m: _arrays()
    )
    with SessionLocal() as db:
        run = scan_module.run_raster_scan(db, "2026-09-06")
    assert run.status == "ok"
    assert "search_stopped" not in run.source_metadata


def test_budget_not_below_stale_threshold_is_refused(client, tmp_path, monkeypatch):
    _clear(tmp_path, monkeypatch)
    monkeypatch.setattr(
        config_module, "RASTER_BOOTSTRAP_BUDGET_MINUTES", scan_module.STALE_RUN_HOURS * 60
    )

    def forbidden(*_args, **_kwargs):
        raise AssertionError("a misconfigured budget must not reach GEE")

    monkeypatch.setattr(scan_module.bridge, "build_index_composite", forbidden)
    with SessionLocal() as db:
        run = scan_module.run_raster_scan(db, "2026-09-06")
    assert run.status == "error"
    assert "RASTER_BOOTSTRAP_BUDGET_MINUTES" in run.reason


def test_budget_is_read_from_config_at_call_time(client, tmp_path, monkeypatch):
    # A change to src.config after scan.py was imported must take effect:
    # the budget is read when a bootstrap runs, not bound at import.
    _clear(tmp_path, monkeypatch)
    monkeypatch.setattr(config_module, "RASTER_BOOTSTRAP_BUDGET_MINUTES", 0)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("a misconfigured budget must not reach GEE")

    monkeypatch.setattr(scan_module.bridge, "build_index_composite", forbidden)
    with SessionLocal() as db:
        run = scan_module.run_raster_scan(db, "2026-09-06")
    assert run.status == "error"
    assert "RASTER_BOOTSTRAP_BUDGET_MINUTES=0" in run.reason


def _probe(env_value):
    env = {k: v for k, v in os.environ.items() if k != "RASTER_BOOTSTRAP_BUDGET_MINUTES"}
    if env_value is not None:
        env["RASTER_BOOTSTRAP_BUDGET_MINUTES"] = env_value
    src = (
        f"import sys; sys.path.insert(0, {str(_BACKEND_DIR)!r})\n"
        "from src import config\n"
        "print(config.RASTER_BOOTSTRAP_BUDGET_MINUTES)\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", src], env=env, capture_output=True, text=True,
        cwd=str(_BACKEND_DIR / "tests"),
    )
    return out


def test_budget_env_var_default_and_override():
    default = _probe(None)
    assert default.returncode == 0, default.stderr
    assert default.stdout.strip() == "45"
    override = _probe("30")
    assert override.returncode == 0, override.stderr
    assert override.stdout.strip() == "30"


def test_non_integer_budget_env_var_raises_a_value_error_naming_it():
    bad = _probe("forty-five")
    assert bad.returncode != 0
    # The exception message itself (last stderr line), not the traceback's
    # echo of the source line, must name the variable and the bad value.
    message = bad.stderr.strip().splitlines()[-1]
    assert message.startswith("ValueError"), message
    assert "RASTER_BOOTSTRAP_BUDGET_MINUTES" in message
    assert "forty-five" in message
