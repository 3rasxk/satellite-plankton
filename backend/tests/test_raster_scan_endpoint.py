"""`/raster-scan` -- serves the newest overlay that still exists on disk.

No live GEE, no rendering: these exercise what the endpoint does with
rows and files that are already there.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from sqlalchemy import delete

from src import _study_area
from src import _detection as bridge
from src.db import SessionLocal
from src.db_models import RasterScanRun, SceneAssessmentRow, ScenePollStatus
from src import config
from src.raster_scan import render, storage
from src.schemas import RasterScanResponse


# Distinguishes "the caller said nothing" from "the caller said None".
# scene_dates=None is the state of every row written before that column
# existed, and a test has to be able to ask for exactly that.
_UNSET = object()


def _run(tmp_path, *, run_id_hint: str, started: datetime, overlay_ok: bool = True,
         bounds=None, exists: bool = True, stats=None, scene_dates=_UNSET) -> RasterScanRun:
    png = tmp_path / f"{run_id_hint}.png"
    if exists:
        png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    asset = {"path": str(png), "bytes": 72}
    # The coverage stats render.py records on the asset. Defaulted to a
    # realistic quarter-of-the-polygon reading rather than left out, so
    # every test in this file exercises the shape a real run produces;
    # `stats={}` is how a test asks for the pre-coverage shape instead.
    asset.update({
        "measured_pixels": 2500,
        "inside_polygon_pixels": 10000,
        "measured_fraction": 0.25,
    } if stats is None else stats)
    overlay = {
        "status": "ok" if overlay_ok else "error",
        "bounds": {"leaflet_bounds": bounds or [[12.5, 99.9], [13.6, 101.0]]},
        "assets": {"ndci": asset},
        "legend": {
            "value": {"ramp_hex": ["#0A1929"], "domain": [-0.05, 0.15],
                      "swatches": [{"value": -0.05, "hex": "#0a1929"}]},
            "no_data": {"rgba": [0, 0, 0, 0], "meaning": "transparent no usable measurement"},
        },
    }
    return RasterScanRun(
        started_at=started, completed_at=started, status="ok", date_used="2026-09-06",
        scale_m=200, retention_days=30, cell_count=1234, scene_count=3,
        oldest_scene_date="2026-08-23", newest_scene_date="2026-09-02",
        scene_dates=scene_dates if scene_dates is not _UNSET else [
            {"date": "2026-09-02", "cells": 1000, "share": 1000 / 1234},
            {"date": "2026-08-23", "cells": 234, "share": 234 / 1234},
        ],
        overlay=overlay,
    )


def _clear():
    with SessionLocal() as db:
        db.execute(delete(RasterScanRun))
        db.commit()


def _rendered_reading(db, tmp_path, *, started, value, date_ms):
    """A real stored cell and the PNG rendered from it, unique to its run."""
    run = _run(tmp_path, run_id_hint=str(date_ms), started=started)
    db.add(run)
    db.commit()
    cells = {
        "lat": np.array([12.97]),
        "lng": np.array([100.01]),
        **{band: np.array([value], dtype=np.float32) for band in bridge.RASTER_INDEX_BANDS},
        **{band: np.array([channel], dtype=np.float32) for band, channel in zip(
            bridge.RASTER_TRUE_COLOR_BANDS, (900, 600, 300)
        )},
        bridge.RASTER_DATE_BAND: np.array([date_ms], dtype=np.int64),
    }
    run.blob_path = storage.write_cells(run.id, cells, root=tmp_path)["path"]
    db.commit()
    render.render_and_store(db, run, root=tmp_path)
    db.refresh(run)
    return run


def test_metadata_binds_image_and_pixel_to_its_run_when_a_new_scan_finishes(client, tmp_path):
    _clear()
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        old = _rendered_reading(db, tmp_path, started=now - timedelta(hours=1),
                                value=0.125, date_ms=1787628600000)
        old_id = old.id

    displayed = client.get("/raster-scan").json()
    old_image = client.get(displayed["overlay_url"]).content

    # B completes after A's metadata reached the browser, before its next
    # image request or click. Every value still has to describe A.
    with SessionLocal() as db:
        newer = _rendered_reading(db, tmp_path, started=now,
                                  value=-0.03125, date_ms=1788492600000)
        newer_id = newer.id

    latest = client.get("/raster-scan").json()
    assert latest["run_id"] == newer_id
    assert client.get(displayed["overlay_url"]).content == old_image
    pixel = client.get("/raster-scan/pixel", params={
        "lat": 12.97, "lng": 100.01, "run_id": old_id,
    }).json()
    assert pixel["run_id"] == old_id
    assert pixel["index_values"]["ndci"] == 0.125
    assert pixel["acquired_date"] == "2026-08-25"
    assert displayed["overlay_url"] == f"/raster-scan/overlay.png?run_id={old_id}"
    assert displayed["true_color_url"] == f"/raster-scan/true-color.png?run_id={old_id}"
    assert client.get(displayed["true_color_url"]).status_code == 200
    assert latest["overlay_url"] == f"/raster-scan/overlay.png?run_id={newer_id}"
    assert displayed["overlay_url"] != latest["overlay_url"]

    # Callers that omit run_id retain the existing newest-render behavior.
    assert client.get("/raster-scan/overlay.png").content != old_image
    latest_pixel = client.get("/raster-scan/pixel", params={"lat": 12.97, "lng": 100.01}).json()
    assert latest_pixel["run_id"] == newer_id
    assert latest_pixel["index_values"]["ndci"] == -0.03125


@pytest.mark.parametrize("unavailable", ["missing", "expired", "failed"])
@pytest.mark.parametrize("endpoint", ["overlay.png", "pixel"])
def test_explicit_unavailable_run_never_substitutes_a_usable_run(
    client, tmp_path, unavailable, endpoint,
):
    _clear()
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        good = _rendered_reading(db, tmp_path, started=now, value=0.125,
                                 date_ms=1788492600000)
        if unavailable == "missing":
            requested_id = good.id + 1000
        else:
            unusable = _run(tmp_path, run_id_hint=unavailable, started=now - timedelta(days=1),
                            exists=unavailable != "expired", overlay_ok=unavailable != "failed")
            db.add(unusable)
            db.commit()
            requested_id = unusable.id

    params = {"lat": 12.97, "lng": 100.01}
    assert client.get(f"/raster-scan/{endpoint}", params=params).status_code == 200
    response = client.get(f"/raster-scan/{endpoint}", params={**params, "run_id": requested_id})
    assert response.status_code == 404


@pytest.mark.parametrize("run_id", [0, -1, "invalid", "1.5", str(2**63)])
@pytest.mark.parametrize("endpoint", ["overlay.png", "pixel"])
def test_explicit_run_id_must_be_a_valid_database_id(client, endpoint, run_id):
    response = client.get(f"/raster-scan/{endpoint}", params={
        "lat": 12.97, "lng": 100.01, "run_id": run_id,
    })
    assert response.status_code == 422


def test_no_scan_yet_says_so_instead_of_serving_a_blank_overlay(client):
    _clear()
    body = client.get("/raster-scan").json()
    assert body["run_id"] is None
    assert body["bounds"] is None
    assert body["overlay_url"] is None
    assert body["true_color_url"] is None
    assert "No raster overlay" in body["reason"]
    assert client.get("/raster-scan/overlay.png").status_code == 404


def test_the_served_overlay_is_the_newest_one_with_a_file_on_disk(client, tmp_path):
    _clear()
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        old = _run(tmp_path, run_id_hint="old", started=now - timedelta(hours=5))
        # Newer, but its render failed -- it must not hide the older picture.
        broken = _run(tmp_path, run_id_hint="broken", started=now, overlay_ok=False)
        db.add_all([old, broken])
        db.commit()
        old_id, broken_id = old.id, broken.id

    body = client.get("/raster-scan").json()
    assert body["run_id"] == old_id, "a failed newer run hid the last good overlay"
    assert body["stale_run_id"] == broken_id, "the newer attempt was not reported"
    assert client.get("/raster-scan/overlay.png").status_code == 200


def test_a_run_whose_blob_was_expired_is_not_served(client, tmp_path):
    """Retention deletes the PNG but keeps the row. The row must not
    advertise a picture that is gone."""
    _clear()
    with SessionLocal() as db:
        db.add(_run(tmp_path, run_id_hint="expired",
                    started=datetime.now(timezone.utc), exists=False))
        db.commit()
    body = client.get("/raster-scan").json()
    assert body["run_id"] is None
    assert client.get("/raster-scan/overlay.png").status_code == 404


def test_bounds_and_legend_travel_with_the_metadata(client, tmp_path):
    _clear()
    with SessionLocal() as db:
        db.add(_run(tmp_path, run_id_hint="ok", started=datetime.now(timezone.utc)))
        db.commit()
    body = client.get("/raster-scan").json()
    assert body["bounds"] == [[12.5, 99.9], [13.6, 101.0]]
    assert body["legend"]["value"]["swatches"][0]["hex"] == "#0a1929"
    assert body["legend"]["no_data"]["rgba"] == [0, 0, 0, 0]
    assert body["scale_m"] == 200
    assert body["oldest_scene_date"] == "2026-08-23"
    assert body["newest_scene_date"] == "2026-09-02"
    assert body["disclaimer"]


def test_the_response_never_carries_a_risk_level_or_anomaly_score(client, tmp_path):
    """Same truth boundary as every other endpoint: readings only."""
    _clear()
    with SessionLocal() as db:
        db.add(_run(tmp_path, run_id_hint="ok2", started=datetime.now(timezone.utc)))
        db.commit()
    body = client.get("/raster-scan").json()
    for forbidden in ("risk_level", "anomaly_z", "spatial_anomaly_z", "threshold_tier"):
        assert forbidden not in body, f"{forbidden} must not appear on a raster response"


def test_the_per_day_breakdown_is_served_alongside_the_span(client, tmp_path):
    """The span says 23 Aug to 2 Sep for every one of these rasters. Only
    the breakdown says that four fifths of it is a single day, so the
    banner cannot state that unless the endpoint serves it."""
    _clear()
    with SessionLocal() as db:
        db.add(_run(tmp_path, run_id_hint="days", started=datetime.now(timezone.utc)))
        db.commit()

    body = client.get("/raster-scan").json()
    assert [entry["date"] for entry in body["scene_dates"]] == ["2026-09-02", "2026-08-23"]
    assert [entry["cells"] for entry in body["scene_dates"]] == [1000, 234]
    assert sum(entry["cells"] for entry in body["scene_dates"]) == body["cell_count"]
    assert abs(sum(entry["share"] for entry in body["scene_dates"]) - 1.0) < 1e-12
    # A day count is not a scene count -- several tiles can share a day.
    assert len(body["scene_dates"]) <= body["scene_count"]


def test_a_run_taken_before_the_breakdown_existed_serves_null_not_an_even_split(client, tmp_path):
    """Null reads as "not recorded". Anything else -- an empty list, an
    even split across the span -- would be this project inventing a
    distribution it never measured."""
    _clear()
    with SessionLocal() as db:
        db.add(_run(tmp_path, run_id_hint="olddays",
                    started=datetime.now(timezone.utc), scene_dates=None))
        db.commit()
    # scene_dates=None reaches the column as SQL NULL, which is the state
    # of every row written before the column existed.
    assert client.get("/raster-scan").json()["scene_dates"] is None


def test_coverage_is_served_and_its_denominator_is_the_polygon(client, tmp_path):
    """Coverage is the share of the STUDY POLYGON with a reading -- land
    inside the boundary included in the denominator, because the polygon
    is a boundary and not a water mask. Serving it lets the banner state
    what is measured and, more importantly, what is not."""
    _clear()
    with SessionLocal() as db:
        db.add(_run(tmp_path, run_id_hint="cov", started=datetime.now(timezone.utc), stats={
            "measured_pixels": 2571,
            "inside_polygon_pixels": 10000,
            "measured_fraction": 0.2571,
        }))
        db.commit()

    coverage = client.get("/raster-scan").json()["coverage"]
    assert coverage["measured_pixels"] == 2571
    assert coverage["polygon_pixels"] == 10000
    assert coverage["measured_fraction"] == 0.2571
    # The served fraction is the renderer's own, not a re-derivation --
    # but it must still agree with the counts it is served beside.
    assert coverage["measured_fraction"] == (
        coverage["measured_pixels"] / coverage["polygon_pixels"]
    )


def test_an_older_render_keeps_its_real_fraction_and_reports_no_pixel_count(client, tmp_path):
    """`measured_pixels` was added after some overlays were drawn. Those
    overlays still recorded a real fraction, so the fraction is served and
    the count is left null -- never back-calculated from a rounded
    percentage, which would put a number on screen that the picture's own
    metadata does not contain."""
    _clear()
    with SessionLocal() as db:
        db.add(_run(tmp_path, run_id_hint="oldcov",
                    started=datetime.now(timezone.utc), stats={
                        "inside_polygon_pixels": 10000,
                        "measured_fraction": 0.2571,
                    }))
        db.commit()

    coverage = client.get("/raster-scan").json()["coverage"]
    assert coverage["measured_fraction"] == 0.2571
    assert coverage["polygon_pixels"] == 10000
    assert coverage["measured_pixels"] is None


def test_an_overlay_with_no_coverage_stats_reports_none(client, tmp_path):
    """No stats at all means no coverage claim."""
    _clear()
    with SessionLocal() as db:
        db.add(_run(tmp_path, run_id_hint="nocov",
                    started=datetime.now(timezone.utc), stats={}))
        db.commit()
    assert client.get("/raster-scan").json()["coverage"] is None


def test_overlay_bounds_cover_the_whole_study_polygon(client, tmp_path):
    """A stretched overlay misplaces every pixel and nothing visibly
    fails, so the bounds are checked against the polygon numerically."""
    lats = [p[0] for p in _study_area.STUDY_AREA_POLYGON_LATLNG]
    lngs = [p[1] for p in _study_area.STUDY_AREA_POLYGON_LATLNG]
    expected = [[min(lats), min(lngs)], [max(lats), max(lngs)]]

    _clear()
    with SessionLocal() as db:
        db.add(_run(tmp_path, run_id_hint="poly",
                    started=datetime.now(timezone.utc), bounds=expected))
        db.commit()

    body = client.get("/raster-scan").json()
    (south, west), (north, east) = body["bounds"]
    assert (south, west) == (min(lats), min(lngs))
    assert (north, east) == (max(lats), max(lngs))
    for lat, lng in _study_area.STUDY_AREA_POLYGON_LATLNG:
        assert south <= lat <= north, f"polygon vertex {lat} outside the overlay bounds"
        assert west <= lng <= east, f"polygon vertex {lng} outside the overlay bounds"


def test_pixel_handler_is_sync_so_blob_read_runs_in_threadpool():
    import inspect
    from src.routers import raster_scan as raster_scan_router

    assert not inspect.iscoroutinefunction(raster_scan_router.get_raster_pixel)


@pytest.mark.parametrize("asset_kind", ["missing_file", "no_path_key", "existing_file"])
def test_true_color_url_only_when_the_png_exists_on_disk(client, tmp_path, asset_kind):
    _clear()
    run = _run(tmp_path, run_id_hint="tc", started=datetime.now(timezone.utc))
    tc_png = tmp_path / "tc_true_color.png"
    if asset_kind == "existing_file":
        tc_png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
        tc_asset = {"path": str(tc_png)}
    elif asset_kind == "missing_file":
        tc_asset = {"path": str(tc_png)}
    else:
        tc_asset = {"bytes": 72}
    overlay = dict(run.overlay)
    overlay["assets"] = {**overlay["assets"], "true_color": tc_asset}
    run.overlay = overlay
    with SessionLocal() as db:
        db.add(run)
        db.commit()
        run_id = run.id

    body = client.get("/raster-scan").json()
    assert body["run_id"] == run_id
    if asset_kind == "existing_file":
        assert body["true_color_url"] == f"/raster-scan/true-color.png?run_id={run_id}"
    else:
        assert body["true_color_url"] is None


# --------------------------------------------------------------------------
# Latest-scene fields (spec 2026-10-09 §7): the newest assessed acquisition,
# the last used date and the poll's health, served beside the raster so a
# viewer can tell "not used, showing earlier data" from "nothing newer".
# --------------------------------------------------------------------------

# Every field /raster-scan served before the latest-scene fields existed.
_PRE_EXISTING_KEYS = {
    "disclaimer", "run_id", "status", "date_used", "scale_m", "cell_count", "scene_count",
    "oldest_scene_date", "newest_scene_date", "scene_dates", "source_metadata", "completed_at",
    "coverage", "bounds", "legend", "overlay_url", "true_color_url", "stale_run_id", "reason",
}
_NEW_KEYS = {"latest_scene", "last_used_scene_date", "poll"}


def _clear_scenes():
    with SessionLocal() as db:
        db.execute(delete(SceneAssessmentRow))
        db.execute(delete(ScenePollStatus))
        db.commit()


@pytest.fixture(autouse=True)
def _leave_no_scene_rows_behind():
    """This module's scene rows must not leak into later test files that
    share the session database (the trigger tests expect empty tables)."""
    yield
    _clear_scenes()


def _assessment(date, *, decision="passed", cloud=0.1, water=5000, reason=None,
                assessed_at=None, used_in_run_id=None) -> SceneAssessmentRow:
    return SceneAssessmentRow(
        acquisition_date=date, decision=decision, cloud_fraction=cloud, water_pixels=water,
        reason=reason, used_in_run_id=used_in_run_id,
        assessed_at=assessed_at or datetime(2026, 10, 9, 6, 0, tzinfo=timezone.utc),
    )


def _served_run(tmp_path, hint="scene") -> int:
    """Store one servable run and return its id."""
    with SessionLocal() as db:
        run = _run(tmp_path, run_id_hint=hint, started=datetime.now(timezone.utc))
        db.add(run)
        db.commit()
        return run.id


def test_empty_scene_tables_serve_null_for_all_three_fields(client, tmp_path):
    _clear()
    _clear_scenes()
    _served_run(tmp_path)
    body = client.get("/raster-scan").json()
    assert body["latest_scene"] is None
    assert body["last_used_scene_date"] is None
    assert body["poll"] is None


def test_scene_fields_are_served_even_when_no_overlay_exists(client):
    """The case where they matter most: no picture, yet the poll may be
    failing -- the viewer must still be told."""
    _clear()
    _clear_scenes()
    with SessionLocal() as db:
        db.add(_assessment("2026-10-08", decision="rejected_cloud", cloud=0.83,
                           reason="cloud 83 % > 50 %"))
        db.add(ScenePollStatus(id=1, last_error="boom", last_error_kind="gee_auth",
                               last_error_at=datetime(2026, 10, 9, 5, 0, tzinfo=timezone.utc)))
        db.commit()
    body = client.get("/raster-scan").json()
    assert body["run_id"] is None
    assert body["latest_scene"]["acquisition_date"] == "2026-10-08"
    assert body["latest_scene"]["used_in_served_run"] is False
    assert body["poll"]["last_error_kind"] == "gee_auth"


def test_existing_fields_are_unchanged_on_a_served_run(client, tmp_path):
    """The new fields are additive: the pre-existing key set and values
    are exactly what they were, with or without scene rows."""
    _clear()
    _clear_scenes()
    run_id = _served_run(tmp_path, "pin")

    def check(body):
        assert set(body) == _PRE_EXISTING_KEYS | _NEW_KEYS
        assert body["run_id"] == run_id
        assert body["status"] == "ok"
        assert body["date_used"] == "2026-09-06"
        assert body["scale_m"] == 200
        assert body["cell_count"] == 1234
        assert body["scene_count"] == 3
        assert body["oldest_scene_date"] == "2026-08-23"
        assert body["newest_scene_date"] == "2026-09-02"
        assert [e["date"] for e in body["scene_dates"]] == ["2026-09-02", "2026-08-23"]
        assert body["coverage"] == {
            "measured_fraction": 0.25, "measured_pixels": 2500, "polygon_pixels": 10000}
        assert body["bounds"] == [[12.5, 99.9], [13.6, 101.0]]
        assert body["overlay_url"] == f"/raster-scan/overlay.png?run_id={run_id}"
        assert body["true_color_url"] is None
        assert body["stale_run_id"] is None
        assert body["reason"] is None
        assert body["disclaimer"]

    check(client.get("/raster-scan").json())
    with SessionLocal() as db:
        db.add(_assessment("2026-10-08", decision="rejected_cloud", cloud=0.83))
        db.add(ScenePollStatus(id=1, last_poll_ok_at=datetime(2026, 10, 9, 5, tzinfo=timezone.utc)))
        db.commit()
    check(client.get("/raster-scan").json())


def test_newest_rejected_row_is_echoed_with_the_threshold_and_older_used_date(
    client, tmp_path, monkeypatch,
):
    _clear()
    _clear_scenes()
    run_id = _served_run(tmp_path)
    monkeypatch.setattr(bridge, "scene_thresholds", lambda: (0.5, 1000))
    with SessionLocal() as db:
        db.add(_assessment("2026-10-05", cloud=0.12, used_in_run_id=run_id))
        db.add(_assessment("2026-10-08", decision="rejected_cloud", cloud=0.83, water=7777,
                           reason="cloud fraction 0.83 > 0.5",
                           assessed_at=datetime(2026, 10, 9, 6, 30, 15, tzinfo=timezone.utc)))
        db.commit()

    body = client.get("/raster-scan").json()
    assert body["latest_scene"] == {
        "acquisition_date": "2026-10-08",
        "decision": "rejected_cloud",
        "cloud_fraction": 0.83,
        "threshold_cloud_fraction": 0.5,
        "min_water_pixels": 1000,
        "reason": "cloud fraction 0.83 > 0.5",
        "used_in_run_id": None,
        "assessed_at": "2026-10-09T06:30:15+00:00",
        "settled": False,
        "used_in_served_run": False,
        "reassessed_after_use": False,
    }
    assert body["last_used_scene_date"] == "2026-10-05"


def test_the_threshold_comes_from_the_live_configuration(client, tmp_path, monkeypatch):
    _clear()
    _clear_scenes()
    _served_run(tmp_path)
    monkeypatch.setenv("RASTER_SCENE_MAX_CLOUD_FRACTION", "0.35")
    monkeypatch.setenv("RASTER_SCENE_MIN_WATER_PIXELS", "250")
    with SessionLocal() as db:
        db.add(_assessment("2026-10-08"))
        db.commit()
    latest = client.get("/raster-scan").json()["latest_scene"]
    assert latest["threshold_cloud_fraction"] == 0.35
    assert latest["min_water_pixels"] == 250


def test_an_invalid_threshold_setting_does_not_break_the_endpoint(client, tmp_path, monkeypatch):
    """scene_thresholds() raises on a bad env value. The row is still
    served; the thresholds are null rather than a guess or a 500."""
    _clear()
    _clear_scenes()
    run_id = _served_run(tmp_path)
    monkeypatch.setenv("RASTER_SCENE_MAX_CLOUD_FRACTION", "banana")
    with SessionLocal() as db:
        db.add(_assessment("2026-10-08", cloud=0.2))
        db.commit()
    response = client.get("/raster-scan")
    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == run_id
    assert body["latest_scene"]["acquisition_date"] == "2026-10-08"
    assert body["latest_scene"]["cloud_fraction"] == 0.2
    assert body["latest_scene"]["threshold_cloud_fraction"] is None
    assert body["latest_scene"]["min_water_pixels"] is None


def test_latest_scene_is_the_greatest_acquisition_date_not_the_last_assessed(client, tmp_path):
    _clear()
    _clear_scenes()
    _served_run(tmp_path)
    with SessionLocal() as db:
        # Inserted newest-date first and assessed earliest; ordering must
        # follow the acquisition date.
        db.add(_assessment("2026-10-08", assessed_at=datetime(2026, 10, 8, 20, tzinfo=timezone.utc)))
        db.add(_assessment("2026-10-02", assessed_at=datetime(2026, 10, 9, 8, tzinfo=timezone.utc)))
        db.commit()
    assert client.get("/raster-scan").json()["latest_scene"]["acquisition_date"] == "2026-10-08"


def test_used_in_served_run_is_true_only_for_the_run_actually_served(client, tmp_path):
    _clear()
    _clear_scenes()
    run_id = _served_run(tmp_path)
    with SessionLocal() as db:
        db.add(_assessment("2026-10-08", used_in_run_id=run_id))
        db.commit()
    latest = client.get("/raster-scan").json()["latest_scene"]
    assert latest["used_in_run_id"] == run_id
    assert latest["used_in_served_run"] is True
    assert latest["reassessed_after_use"] is False

    with SessionLocal() as db:
        row = db.get(SceneAssessmentRow, "2026-10-08")
        row.used_in_run_id = run_id + 999  # used by some other (not served) run
        db.commit()
    latest = client.get("/raster-scan").json()["latest_scene"]
    assert latest["used_in_run_id"] == run_id + 999
    assert latest["used_in_served_run"] is False
    assert latest["reassessed_after_use"] is False

    with SessionLocal() as db:
        db.get(SceneAssessmentRow, "2026-10-08").used_in_run_id = None
        db.commit()
    latest = client.get("/raster-scan").json()["latest_scene"]
    assert latest["used_in_run_id"] is None
    assert latest["used_in_served_run"] is False


@pytest.mark.parametrize("decision", ["rejected_cloud", "rejected_no_water"])
def test_a_used_date_reassessed_as_not_passing_is_flagged(client, tmp_path, decision):
    """The scan happened and its id is kept, but the date no longer
    passes. The response must let a viewer say exactly that."""
    _clear()
    _clear_scenes()
    run_id = _served_run(tmp_path)
    with SessionLocal() as db:
        db.add(_assessment("2026-10-08", decision=decision, cloud=0.9, used_in_run_id=run_id))
        db.commit()
    body = client.get("/raster-scan").json()
    latest = body["latest_scene"]
    assert latest["decision"] == decision
    assert latest["used_in_run_id"] == run_id
    assert latest["used_in_served_run"] is True
    assert latest["reassessed_after_use"] is True
    assert body["last_used_scene_date"] == "2026-10-08"


def test_a_passing_unused_or_used_date_is_not_flagged_as_reassessed(client, tmp_path):
    _clear()
    _clear_scenes()
    run_id = _served_run(tmp_path)
    with SessionLocal() as db:
        db.add(_assessment("2026-10-08", decision="passed"))
        db.commit()
    assert client.get("/raster-scan").json()["latest_scene"]["reassessed_after_use"] is False
    with SessionLocal() as db:
        db.get(SceneAssessmentRow, "2026-10-08").used_in_run_id = run_id
        db.commit()
    assert client.get("/raster-scan").json()["latest_scene"]["reassessed_after_use"] is False


def test_last_used_scene_date_ignores_newer_unused_rows(client, tmp_path):
    _clear()
    _clear_scenes()
    run_id = _served_run(tmp_path)
    with SessionLocal() as db:
        db.add(_assessment("2026-10-01", used_in_run_id=run_id - 1 if run_id > 1 else 1))
        db.add(_assessment("2026-10-04", used_in_run_id=run_id))
        db.add(_assessment("2026-10-07"))
        db.add(_assessment("2026-10-08", decision="rejected_cloud", cloud=0.9))
        db.commit()
    body = client.get("/raster-scan").json()
    assert body["last_used_scene_date"] == "2026-10-04"
    assert body["latest_scene"]["acquisition_date"] == "2026-10-08"


@pytest.mark.parametrize("assessed_at, settled", [
    # 2026-10-08 00:00 UTC + 36 h = 2026-10-09 12:00 UTC
    (datetime(2026, 10, 9, 11, 59, 59, tzinfo=timezone.utc), False),
    (datetime(2026, 10, 9, 12, 0, 0, tzinfo=timezone.utc), True),
    (datetime(2026, 10, 10, 3, 0, 0, tzinfo=timezone.utc), True),
    (datetime(2026, 10, 8, 9, 0, 0, tzinfo=timezone.utc), False),
])
def test_settled_follows_the_36_hour_rule_on_assessed_at(client, tmp_path, assessed_at, settled):
    _clear()
    _clear_scenes()
    _served_run(tmp_path)
    with SessionLocal() as db:
        db.add(_assessment("2026-10-08", assessed_at=assessed_at))
        db.commit()
    assert client.get("/raster-scan").json()["latest_scene"]["settled"] is settled


def test_timestamps_are_iso_utc_strings_even_though_sqlite_returns_naive(client, tmp_path):
    _clear()
    _clear_scenes()
    _served_run(tmp_path)
    with SessionLocal() as db:
        db.add(_assessment("2026-10-08", assessed_at=datetime(2026, 10, 9, 6, 0, tzinfo=timezone.utc)))
        db.add(ScenePollStatus(
            id=1,
            last_poll_started_at=datetime(2026, 10, 9, 7, 0, tzinfo=timezone.utc),
            last_poll_ok_at=datetime(2026, 10, 9, 7, 0, 5, tzinfo=timezone.utc),
        ))
        db.commit()
    body = client.get("/raster-scan").json()
    assert body["latest_scene"]["assessed_at"] == "2026-10-09T06:00:00+00:00"
    assert body["poll"]["last_poll_started_at"] == "2026-10-09T07:00:00+00:00"
    assert body["poll"]["last_poll_ok_at"] == "2026-10-09T07:00:05+00:00"


def test_poll_block_maps_every_status_column_including_the_error(client, tmp_path):
    _clear()
    _clear_scenes()
    _served_run(tmp_path)
    with SessionLocal() as db:
        db.add(ScenePollStatus(
            id=1,
            last_poll_started_at=datetime(2026, 10, 9, 8, 0, tzinfo=timezone.utc),
            last_poll_ok_at=datetime(2026, 10, 9, 4, 0, tzinfo=timezone.utc),
            last_error="Earth Engine credentials expired",
            last_error_at=datetime(2026, 10, 9, 8, 0, 2, tzinfo=timezone.utc),
            last_error_kind="gee_auth",
        ))
        db.commit()
    assert client.get("/raster-scan").json()["poll"] == {
        "last_poll_started_at": "2026-10-09T08:00:00+00:00",
        "last_poll_ok_at": "2026-10-09T04:00:00+00:00",
        "last_error": "Earth Engine credentials expired",
        "last_error_at": "2026-10-09T08:00:02+00:00",
        "last_error_kind": "gee_auth",
    }


def test_poll_block_serves_nulls_for_a_poll_that_never_finished_or_failed(client, tmp_path):
    _clear()
    _clear_scenes()
    _served_run(tmp_path)
    with SessionLocal() as db:
        db.add(ScenePollStatus(
            id=1, last_poll_started_at=datetime(2026, 10, 9, 8, 0, tzinfo=timezone.utc)))
        db.commit()
    assert client.get("/raster-scan").json()["poll"] == {
        "last_poll_started_at": "2026-10-09T08:00:00+00:00",
        "last_poll_ok_at": None,
        "last_error": None,
        "last_error_at": None,
        "last_error_kind": None,
    }


@pytest.mark.parametrize("mode", ["off", "test"])
def test_scene_fields_do_not_depend_on_baseline_mode(client, tmp_path, monkeypatch, mode):
    _clear()
    _clear_scenes()
    run_id = _served_run(tmp_path)
    monkeypatch.setattr(config, "BASELINE_MODE", mode)
    with SessionLocal() as db:
        db.add(_assessment("2026-10-08", used_in_run_id=run_id))
        db.add(ScenePollStatus(id=1, last_poll_ok_at=datetime(2026, 10, 9, 5, tzinfo=timezone.utc)))
        db.commit()
    body = client.get("/raster-scan").json()
    assert body["latest_scene"]["acquisition_date"] == "2026-10-08"
    assert body["last_used_scene_date"] == "2026-10-08"
    assert body["poll"]["last_poll_ok_at"] == "2026-10-09T05:00:00+00:00"


def test_the_served_payload_validates_against_the_response_schema(client, tmp_path):
    _clear()
    _clear_scenes()
    run_id = _served_run(tmp_path)
    with SessionLocal() as db:
        db.add(_assessment("2026-10-08", decision="rejected_cloud", cloud=0.8,
                           used_in_run_id=run_id))
        db.add(ScenePollStatus(id=1, last_error="x", last_error_kind="unexpected"))
        db.commit()
    body = client.get("/raster-scan").json()
    parsed = RasterScanResponse.model_validate(body)
    assert parsed.latest_scene is not None
    assert parsed.latest_scene.reassessed_after_use is True
    assert parsed.poll is not None and parsed.poll.last_error_kind == "unexpected"


def test_the_poll_fields_say_a_stale_poll_is_not_proof_of_no_newer_scene():
    props = RasterScanResponse.model_json_schema()["$defs"]["ScenePollInfo"]["properties"]
    text = props["last_poll_ok_at"]["description"]
    assert "not checked" in text
    assert "never" in text and "no newer scene" in text
    assert "reassessed_after_use" in RasterScanResponse.model_json_schema()[
        "$defs"]["LatestSceneInfo"]["properties"]
