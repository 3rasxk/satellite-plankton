"""Database-aware first-success raster bootstrap; all imagery is synthetic."""

from datetime import datetime, timezone

import numpy as np
import pytest
from sqlalchemy import delete, select

from src.db import SessionLocal
from src.db_models import RasterScanRun
from src.raster_scan import scan as scan_module
from src.raster_scan import storage


def _arrays(date_ms=1787196600000):
    return {
        "lat": np.array([13.0], dtype=np.float64),
        "lng": np.array([100.5], dtype=np.float64),
        "ndci": np.array([0.05], dtype=np.float32),
        "bda2": np.array([1.2], dtype=np.float32),
        "bda3": np.array([0.3], dtype=np.float32),
        "b2_b3": np.array([0.8], dtype=np.float32),
        scan_module.bridge.RASTER_DATE_BAND: np.array([date_ms], dtype=np.int64),
        "scale_m": 200,
        "cell_count": 1,
        "grid_shape": (1, 1),
        "scene_timestamps_ms": (date_ms,),
    }


def _composite(target_date, max_age, scene_id, date_ms):
    from datetime import date, timedelta

    target = date.fromisoformat(target_date)
    return {
        "image": object(), "region": object(), "scene_ids": (scene_id,),
        "scene_timestamps_ms": (date_ms,), "target_date": target_date,
        "window_start": (target - timedelta(days=max_age)).isoformat(),
        "window_end": (target + timedelta(days=1)).isoformat(),
        "max_scene_age_days": max_age,
        "band_order": scan_module.bridge.RASTER_BAND_ORDER,
    }


def _clear_and_redirect(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "RASTER_BLOB_ROOT", tmp_path)
    with SessionLocal() as db:
        db.execute(delete(RasterScanRun))
        db.commit()


def test_first_success_pages_beyond_14_days_and_uses_the_newest_usable_window(
    client, tmp_path, monkeypatch,
):
    _clear_and_redirect(tmp_path, monkeypatch)
    calls = []
    selected_ms = 1787196600000

    def build(_polygon, target_date, max_scene_age_days=None):
        calls.append(target_date)
        return _composite(target_date, max_scene_age_days, f"scene-{target_date}", selected_ms)

    def download(composite, scale_m):
        if composite["target_date"] == "2026-09-06":
            raise scan_module.bridge.NoWaterPixelsError("newest window fully masked")
        return _arrays(selected_ms)

    monkeypatch.setattr(scan_module.bridge, "build_index_composite", build)
    monkeypatch.setattr(scan_module.bridge, "download_composite_arrays", download)

    with SessionLocal() as db:
        run = scan_module.run_raster_scan(db, "2026-09-06")

    assert run.status == "ok"
    assert calls == ["2026-09-06", "2026-08-22"]
    assert run.source_metadata["bootstrap_mode"] is True
    assert run.source_metadata["selected_window"]["window_start"] == "2026-08-08"
    assert run.source_metadata["search_range"] == {
        "window_start": "2026-08-08", "window_end": "2026-09-07",
    }
    assert run.source_metadata["scene_ids"] == ["scene-2026-08-22"]
    assert run.source_metadata["acquisition_dates"] == ["2026-08-20"]
    assert all(window["window_end"] <= "2026-09-07"
               for window in run.source_metadata["searched_windows"])


def test_successful_run_metadata_disables_bootstrap_even_after_retention(
    client, tmp_path, monkeypatch,
):
    _clear_and_redirect(tmp_path, monkeypatch)
    with SessionLocal() as db:
        db.add(RasterScanRun(
            started_at=datetime.now(timezone.utc), completed_at=datetime.now(timezone.utc),
            status="ok", date_used="2026-09-01", scale_m=200, retention_days=30,
            blob_path=None, blob_deleted_at=datetime.now(timezone.utc),
        ))
        db.commit()

    calls = []
    date_ms = 1788492600000

    def build(_polygon, target_date, **kwargs):
        calls.append(kwargs)
        return _composite(target_date, 14, "recent-scene", date_ms)

    monkeypatch.setattr(scan_module.bridge, "build_index_composite", build)
    monkeypatch.setattr(scan_module.bridge, "download_composite_arrays", lambda *_a, **_k: _arrays(date_ms))

    with SessionLocal() as db:
        run = scan_module.run_raster_scan(db, "2026-09-06")

    assert run.status == "ok"
    assert calls == [{"max_scene_age_days": 14}]
    assert run.source_metadata["bootstrap_mode"] is False
    assert run.source_metadata["selected_window"]["max_scene_age_days"] == 14


def test_failed_bootstrap_does_not_mark_success_and_stops_at_the_archive_start(
    client, tmp_path, monkeypatch,
):
    _clear_and_redirect(tmp_path, monkeypatch)
    calls = []

    def no_scenes(_polygon, target_date, max_scene_age_days=None):
        calls.append((target_date, max_scene_age_days))
        raise scan_module.bridge.NoCloudFreeImageryError("empty bounded window")

    monkeypatch.setattr(scan_module.bridge, "build_index_composite", no_scenes)

    with SessionLocal() as db:
        failed = scan_module.run_raster_scan(db, "2017-03-28")
        successful = db.scalar(select(RasterScanRun).where(RasterScanRun.status == "ok"))

    assert failed.status == "no_data"
    assert failed.source_metadata["bootstrap_mode"] is True
    assert calls == [("2017-03-28", 0)]
    assert successful is None
    assert "archive" in failed.reason.lower()

    with SessionLocal() as db:
        retried = scan_module.run_raster_scan(db, "2017-03-28")
    assert retried.source_metadata["bootstrap_mode"] is True
    assert len(calls) == 2


def test_subsequent_no_data_scan_never_pages_past_the_strict_14_day_window(
    client, tmp_path, monkeypatch,
):
    _clear_and_redirect(tmp_path, monkeypatch)
    with SessionLocal() as db:
        db.add(RasterScanRun(
            started_at=datetime.now(timezone.utc), completed_at=datetime.now(timezone.utc),
            status="ok", date_used="2026-08-01", scale_m=200, retention_days=30,
        ))
        db.commit()

    calls = []
    def no_recent_scenes(_polygon, target_date, max_scene_age_days=None):
        calls.append((target_date, max_scene_age_days))
        raise scan_module.bridge.NoCloudFreeImageryError("nothing recent")

    monkeypatch.setattr(scan_module.bridge, "build_index_composite", no_recent_scenes)
    with SessionLocal() as db:
        run = scan_module.run_raster_scan(db, "2026-09-06")

    assert run.status == "no_data"
    assert run.source_metadata["bootstrap_mode"] is False
    assert calls == [("2026-09-06", 14)]
    assert run.source_metadata["searched_windows"][0]["window_start"] == "2026-08-23"


@pytest.mark.parametrize("failure_type", [scan_module.bridge.GEEAuthError, RuntimeError])
def test_mid_bootstrap_failure_preserves_already_searched_window_provenance(
    client, tmp_path, monkeypatch, failure_type,
):
    _clear_and_redirect(tmp_path, monkeypatch)
    windows = [
        {
            "target_date": "2026-09-06", "max_scene_age_days": 14,
            "window_start": "2026-08-23", "window_end": "2026-09-07",
        },
        {
            "target_date": "2026-08-22", "max_scene_age_days": 14,
            "window_start": "2026-08-08", "window_end": "2026-08-23",
        },
    ]
    monkeypatch.setattr(scan_module.bridge, "iter_bootstrap_windows", lambda _date: windows)
    calls = []

    def build(_polygon, target_date, max_scene_age_days=None):
        calls.append(target_date)
        if len(calls) == 1:
            raise scan_module.bridge.NoCloudFreeImageryError("empty first page")
        raise failure_type("request stopped")

    monkeypatch.setattr(scan_module.bridge, "build_index_composite", build)
    with SessionLocal() as db:
        run = scan_module.run_raster_scan(db, "2026-09-06")

    assert run.status == "error"
    assert [item["result"] for item in run.source_metadata["searched_windows"]] == [
        "no_scenes", "error",
    ]
    assert run.source_metadata["search_range"] == {
        "window_start": "2026-08-08", "window_end": "2026-09-07",
    }
