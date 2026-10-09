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
from src.schemas import RasterHighlightsResponse, RasterScanResponse


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


# --------------------------------------------------------------------------
# GET /raster-scan/highlights (dashboard spec §4.6/§6.1; baseline spec §6):
# the top-N measured cells of one stored run by NDCI -- a ranking inside
# one scan, never a risk marking. Read from the blob, never from GEE.
# --------------------------------------------------------------------------

_PIXEL_404 = "No raster overlay is available to query. Run a raster scan first."
_RANKING = "descending value within this run; not a risk level"
_STEP_200M = 200 / render.METRES_PER_DEGREE


def _rendered_cells(db, tmp_path, cells, *, started=None, hint="hl"):
    """A run whose cells are on disk and whose overlay was rendered from
    them, exactly as a real scan leaves it."""
    run = _run(tmp_path, run_id_hint=hint, started=started or datetime.now(timezone.utc))
    db.add(run)
    db.commit()
    run.blob_path = storage.write_cells(run.id, cells, root=tmp_path)["path"]
    db.commit()
    render.render_and_store(db, run, root=tmp_path)
    db.refresh(run)
    return run


def _four_cells():
    """Three separated readings inside the real study polygon, plus one
    200 m east of the highest -- a neighbour NMS must drop at 3 km."""
    lat = np.array([12.97, 12.97, 13.10, 13.20])
    lng = np.array([100.01, 100.01 + _STEP_200M, 100.30, 100.60])
    ndci = np.array([0.125, 0.11, 0.09, 0.07], dtype=np.float32)
    return {
        "lat": lat, "lng": lng, "ndci": ndci,
        "bda2": np.array([1.1, 1.2, 1.3, 1.4], dtype=np.float32),
        "bda3": np.array([np.nan, 0.2, 0.3, 0.4], dtype=np.float32),
        "b2_b3": np.array([0.8, 0.85, 0.9, 0.95], dtype=np.float32),
        bridge.RASTER_DATE_BAND: np.array(
            [1788492600000, 1788492600000, 1787628600000, 1788492600000], dtype=np.int64),
    }


def test_highlights_rank_the_served_runs_cells_by_ndci(client, tmp_path):
    _clear()
    with SessionLocal() as db:
        run_id = _rendered_cells(db, tmp_path, _four_cells()).id

    response = client.get("/raster-scan/highlights", params={"n": 3})
    assert response.status_code == 200
    body = response.json()
    RasterHighlightsResponse.model_validate(body)
    assert body["run_id"] == run_id
    assert body["mode"] == "ndci" and body["metric"] == "ndci"
    assert body["ranking"] == _RANKING
    assert body["n_requested"] == 3 and body["min_separation_m"] == 3000
    assert body["cohort_size"] == 4
    assert body["reason"] is None
    assert body["baseline"] is None
    assert body["disclaimer"]

    pins = body["pins"]
    assert [p["rank"] for p in pins] == [1, 2, 3]
    assert [p["metric_value"] for p in pins] == [0.125, float(np.float32(0.09)),
                                                 float(np.float32(0.07))]
    assert all(p["risk_tier"] is None for p in pins)
    assert pins[0]["index_values"]["bda3"] is None, "an unreadable index is null, not a number"
    assert pins[1]["acquired_date"] == "2026-08-25"
    assert pins[0]["percentile"] == 75.0
    # A pin is what a click on its own cell reports.
    clicked = client.get("/raster-scan/pixel", params={
        "lat": pins[1]["cell_lat"], "lng": pins[1]["cell_lng"], "run_id": run_id,
    }).json()
    assert clicked["index_values"] == pins[1]["index_values"]
    assert clicked["date_ms"] == pins[1]["date_ms"]


def test_highlights_say_risk_only_to_deny_it(client, tmp_path):
    _clear()
    with SessionLocal() as db:
        _rendered_cells(db, tmp_path, _four_cells())
    body = client.get("/raster-scan/highlights").json()
    text = str({k: v for k, v in body.items() if k != "ranking"}).replace("risk_tier", "")
    assert "risk" not in text.lower()
    for forbidden in ("risk_level", "anomaly_z", "spatial_anomaly_z", "threshold_tier"):
        assert forbidden not in body


def test_highlights_report_fewer_separable_cells_than_requested(client, tmp_path):
    _clear()
    with SessionLocal() as db:
        _rendered_cells(db, tmp_path, _four_cells())
    body = client.get("/raster-scan/highlights",
                      params={"n": 5, "min_separation_m": 10000}).json()
    # 12.97/100.01 -> 13.10/100.30 is ~34 km; 13.10/100.30 -> 13.20/100.60 ~34 km.
    assert len(body["pins"]) == 3
    assert body["reason"] == "only 3 separable measured cells"


def test_highlights_for_an_explicit_run_never_use_a_newer_one(client, tmp_path):
    _clear()
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        old = _rendered_reading(db, tmp_path, started=now - timedelta(hours=1),
                                value=0.125, date_ms=1787628600000)
        old_id = old.id
        _rendered_reading(db, tmp_path, started=now, value=-0.03125, date_ms=1788492600000)
    body = client.get("/raster-scan/highlights", params={"run_id": old_id}).json()
    assert body["run_id"] == old_id
    assert [p["metric_value"] for p in body["pins"]] == [0.125]
    assert body["reason"] == "only 1 separable measured cells"


def test_highlights_404_with_the_pixel_wording_when_no_run_exists(client):
    _clear()
    response = client.get("/raster-scan/highlights")
    assert response.status_code == 404
    assert response.json()["detail"] == _PIXEL_404
    assert client.get("/raster-scan/pixel",
                      params={"lat": 12.97, "lng": 100.01}).json()["detail"] == _PIXEL_404
    missing = client.get("/raster-scan/highlights", params={"run_id": 999999})
    assert missing.status_code == 404
    assert missing.json()["detail"] == _PIXEL_404


def test_highlights_404_when_the_overlay_survives_but_its_cells_do_not(client, tmp_path):
    """Same as the pixel endpoint: the picture can be shown, but no number
    behind it can be ranked."""
    _clear()
    with SessionLocal() as db:
        db.add(_run(tmp_path, run_id_hint="noblob", started=datetime.now(timezone.utc)))
        db.commit()
    highlight = client.get("/raster-scan/highlights")
    pixel_answer = client.get("/raster-scan/pixel", params={"lat": 12.97, "lng": 100.01})
    assert highlight.status_code == pixel_answer.status_code == 404
    assert highlight.json()["detail"] == pixel_answer.json()["detail"]
    assert "no stored cells" in highlight.json()["detail"]


def test_anomaly_mode_with_the_mode_off_is_409_mode_off(client, tmp_path):
    _clear()
    with SessionLocal() as db:
        _rendered_cells(db, tmp_path, _four_cells())
    response = client.get("/raster-scan/highlights", params={"mode": "anomaly"})
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["reason"] == "mode_off"
    assert detail["cause"] is None
    assert "mode=ndci" in detail["message"]


@pytest.mark.parametrize("params", [
    {"n": 2}, {"n": 11}, {"n": "five"},
    {"min_separation_m": 999}, {"min_separation_m": 10001},
    {"mode": "risk"}, {"mode": ""},
    {"run_id": 0}, {"run_id": -1}, {"run_id": "1.5"}, {"run_id": str(2**63)},
])
def test_highlights_refuse_out_of_range_parameters(client, params):
    assert client.get("/raster-scan/highlights", params=params).status_code == 422


@pytest.mark.parametrize("params", [
    {"n": 3}, {"n": 10}, {"min_separation_m": 1000}, {"min_separation_m": 10000},
])
def test_highlights_accept_the_ends_of_each_range(client, tmp_path, params):
    _clear()
    with SessionLocal() as db:
        _rendered_cells(db, tmp_path, _four_cells())
    assert client.get("/raster-scan/highlights", params=params).status_code == 200


def test_highlights_handler_is_sync_so_blob_read_runs_in_threadpool():
    import inspect
    from src.routers import raster_scan as raster_scan_router

    assert not inspect.iscoroutinefunction(raster_scan_router.get_raster_highlights)


def test_highlight_pin_schema_refuses_a_tier():
    from pydantic import ValidationError
    from src.schemas import RasterHighlightPin

    fields = {
        "rank": 1, "cell_lat": 13.0, "cell_lng": 100.0, "pixel_centre_lat": 13.0,
        "pixel_centre_lng": 100.0, "index_values": {"ndci": 0.1}, "percentile": 50.0,
        "date_ms": 1788492600000, "acquired_date": "2026-09-04",
        "acquired_at": "2026-09-04T03:30:00Z", "edge_of_no_data": False, "metric_value": 0.1,
    }
    assert RasterHighlightPin(**fields).risk_tier is None
    with pytest.raises(ValidationError):
        RasterHighlightPin(**fields, risk_tier="watch")


# --------------------------------------------------------------------------
# GET /raster-scan/highlights?mode=anomaly (baseline spec §6, Level B):
# pins where a measured cell's NDCI is at least 2 robust z above that
# cell's own TEST seasonal baseline. Fixture artefact and lattice-aligned
# cells from test_raster_pixel_anomaly (the real builder helpers, tmp_path).
# --------------------------------------------------------------------------

from src import baseline_store, scientific_status  # noqa: E402
from src.schemas import (  # noqa: E402
    DISCLAIMER_TEXT, DISCLAIMER_TEXT_TEST_BASELINE, RasterAnomalyHighlightsResponse,
)
from tests import test_raster_pixel_anomaly as afx  # noqa: E402

_ANOMALY_RANKING = ("descending robust z against this location's own TEST seasonal baseline; "
                    "not a risk level")
# Every key of the ndci-mode response and pin before anomaly mode existed,
# plus `excluded_degenerate` (fix round 1, 2026-10-09: added deliberately --
# degenerate NDCI cells are counted but never pinned).
# Fix round 2 (2026-10-10) adds `excluded_low_signal`, `quality_note` and the
# pins' `visible_bands_dn`, also deliberately.
_NDCI_RESPONSE_KEYS = {"run_id", "mode", "metric", "ranking", "n_requested", "min_separation_m",
                       "cohort_size", "pins", "reason", "baseline", "disclaimer",
                       "excluded_degenerate", "excluded_low_signal", "quality_note"}
_NDCI_PIN_KEYS = {"rank", "cell_lat", "cell_lng", "pixel_centre_lat", "pixel_centre_lng",
                  "index_values", "percentile", "metric_value", "date_ms", "acquired_date",
                  "acquired_at", "edge_of_no_data", "risk_tier", "visible_bands_dn"}
_COUNT_KEYS = ["measured", "assessable", "no_baseline", "insufficient_dates", "zero_mad",
               "not_after_history", "too_old", "invalid", "low_signal", "watch", "high",
               "flagged_share"]
_STATUS_KEYS = {"mode", "valid", "kind", "version", "built_at", "history_start", "history_end",
                "season_rule", "min_independent_dates", "median_independent_dates",
                "min_season_dates_by_location", "preprocessing_signature", "base_rates", "reason"}
_PEAKS = {(1, 1): 0.11, (1, 10): 0.07, (9, 2): 0.055, (10, 10): 0.09}


@pytest.fixture()
def cell_root(tmp_path, monkeypatch):
    root = tmp_path / "baselines"
    afx.isolate_baselines(root, monkeypatch)
    yield root
    baseline_store.clear_cell_cache()


def _anomaly_run(tmp_path, cell_root, *, peaks=None, stats=None, dates=None):
    afx.write_cell_artefact(cell_root, stats if stats is not None else afx.endpoint_stats())
    afx.clear_runs()
    return afx.store_run(tmp_path, afx.endpoint_cells(_PEAKS if peaks is None else peaks,
                                                      dates=dates))


def test_default_mode_is_ndci_with_the_mode_off_and_byte_identical(client, tmp_path, monkeypatch):
    afx.isolate_baselines(tmp_path / "baselines", monkeypatch, mode="off")
    _clear()
    with SessionLocal() as db:
        _rendered_cells(db, tmp_path, _four_cells())
    default = client.get("/raster-scan/highlights", params={"n": 3})
    explicit = client.get("/raster-scan/highlights", params={"n": 3, "mode": "ndci"})
    assert default.status_code == explicit.status_code == 200
    assert default.content == explicit.content
    body = default.json()
    assert set(body) == _NDCI_RESPONSE_KEYS
    assert all(set(pin) == _NDCI_PIN_KEYS for pin in body["pins"])
    assert body["mode"] == "ndci" and body["ranking"] == _RANKING and body["baseline"] is None
    assert body["disclaimer"] == DISCLAIMER_TEXT


def test_ndci_mode_counts_but_never_pins_a_degenerate_reading(client, tmp_path):
    _clear()
    cells = _four_cells()
    extra = {"lat": np.array([13.05]), "lng": np.array([100.45]),
             "ndci": np.array([1.0], dtype=np.float32),
             "bda2": np.array([2.0], dtype=np.float32), "bda3": np.array([0.3], dtype=np.float32),
             "b2_b3": np.array([0.8], dtype=np.float32),
             bridge.RASTER_DATE_BAND: np.array([1788492600000], dtype=np.int64)}
    merged = {k: np.concatenate([cells[k], extra[k]]) for k in cells}
    with SessionLocal() as db:
        _rendered_cells(db, tmp_path, merged)
    body = client.get("/raster-scan/highlights", params={"n": 3}).json()
    assert body["mode"] == "ndci" and set(body) == _NDCI_RESPONSE_KEYS
    assert body["cohort_size"] == 5 and body["excluded_degenerate"] == 1
    assert [p["metric_value"] for p in body["pins"]] == [0.125, float(np.float32(0.09)),
                                                         float(np.float32(0.07))]
    assert body["pins"][0]["percentile"] == 60.0  # 3 of 5 below; the 1.0 cell is above


def test_default_mode_is_anomaly_when_the_cell_baseline_is_usable(client, tmp_path, cell_root):
    _anomaly_run(tmp_path, cell_root)
    body = client.get("/raster-scan/highlights").json()
    assert body["mode"] == "anomaly"
    assert body["metric"] == "robust_z"
    assert body["ranking"] == _ANOMALY_RANKING


def test_default_mode_falls_back_to_ndci_without_a_level_b_baseline(client, tmp_path, cell_root):
    afx.clear_runs()
    afx.store_run(tmp_path, afx.endpoint_cells(_PEAKS))
    body = client.get("/raster-scan/highlights").json()  # test mode, no artefact at all
    assert body["mode"] == "ndci" and set(body) == _NDCI_RESPONSE_KEYS
    assert body["disclaimer"] == DISCLAIMER_TEXT and body["baseline"] is None


def test_explicit_ndci_in_test_mode_keeps_the_standard_disclaimer(client, tmp_path, cell_root):
    _anomaly_run(tmp_path, cell_root)
    body = client.get("/raster-scan/highlights", params={"mode": "ndci"}).json()
    assert body["mode"] == "ndci" and set(body) == _NDCI_RESPONSE_KEYS
    assert body["disclaimer"] == DISCLAIMER_TEXT
    assert body["baseline"] is None
    assert all(set(pin) == _NDCI_PIN_KEYS for pin in body["pins"])


def test_anomaly_response_carries_counts_baseline_and_the_test_disclaimer(client, tmp_path,
                                                                        cell_root):
    run_id = _anomaly_run(tmp_path, cell_root)
    response = client.get("/raster-scan/highlights",
                          params={"mode": "anomaly", "min_separation_m": 1000})
    assert response.status_code == 200
    body = response.json()
    RasterAnomalyHighlightsResponse.model_validate(body)
    assert set(body) == _NDCI_RESPONSE_KEYS | {"counts"}
    assert body["run_id"] == run_id and body["mode"] == "anomaly"
    assert body["disclaimer"] == DISCLAIMER_TEXT_TEST_BASELINE

    counts = body["counts"]
    assert list(counts) == _COUNT_KEYS
    measured = afx.EP_ROWS * afx.EP_COLS
    assert counts["measured"] == body["cohort_size"] == measured
    assert counts["assessable"] + sum(counts[k] for k in _COUNT_KEYS[2:9]) == measured
    assert counts["high"] == 3 and counts["watch"] == 1
    assert counts["flagged_share"] == 4 / measured
    assert body["excluded_degenerate"] == 0

    pins = body["pins"]
    assert [p["anomaly_level"] for p in pins] == ["high", "high", "high", "watch"]
    assert [p["robust_z"] for p in pins] == sorted((p["robust_z"] for p in pins), reverse=True)
    assert pins[0]["robust_z"] == afx.expected_z(0.11, 0.02, 0.01)
    assert all(p["risk_tier"] is None for p in pins)
    assert body["reason"] == (f"only 4 separable cells meet the condition "
                              f"({measured} assessable of {measured} measured)")

    baseline = body["baseline"]
    assert set(baseline) == _STATUS_KEYS | {"level_b"}
    assert baseline["mode"] == "test" and baseline["valid"] is True
    status = scientific_status.baseline_status()
    assert {k: baseline[k] for k in status} == status
    level_b = baseline["level_b"]
    assert level_b["season_key"] == "m09+-1"
    assert level_b["months"] == [8, 9, 10]
    assert level_b["history_end"] == afx.HISTORY_END
    assert level_b["min_independent_dates"] == afx.FLOOR
    assert level_b["scale_m"] == afx.SCALE_M
    assert level_b["cells"] == measured
    assert level_b["max_observation_age_days"] == 14
    assert level_b["cell_preprocessing_signature"] == baseline_store.live_cell_signature()


def test_anomaly_response_says_risk_only_to_deny_it(client, tmp_path, cell_root):
    _anomaly_run(tmp_path, cell_root)
    body = client.get("/raster-scan/highlights", params={"mode": "anomaly"}).json()
    # The ranking and the TEST disclaimer use the word only to say "not a risk level".
    assert "not a risk level" in body["ranking"]
    assert "not a bloom detection, a species identification, a risk level" in body["disclaimer"]
    rest = {k: v for k, v in body.items() if k not in ("ranking", "disclaimer")}
    assert "risk" not in str(rest).replace("risk_tier", "").lower()
    for forbidden in ("risk_level", "anomaly_z", "spatial_anomaly_z", "threshold_tier"):
        assert forbidden not in body


def test_anomaly_mode_409_names_a_missing_cell_baseline(client, tmp_path, cell_root):
    afx.clear_runs()
    afx.store_run(tmp_path, afx.endpoint_cells(_PEAKS))
    response = client.get("/raster-scan/highlights", params={"mode": "anomaly"})
    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "no_cell_baseline"
    assert response.json()["detail"]["cause"] == "no_artifact"
    assert response.json()["detail"]["season_key"] == "m09+-1"


def test_anomaly_mode_409_names_an_invalid_cell_baseline(client, tmp_path, cell_root,
                                                        monkeypatch):
    _anomaly_run(tmp_path, cell_root)
    monkeypatch.setattr(config, "RASTER_SCAN_SCALE_M", 100)
    response = client.get("/raster-scan/highlights", params={"mode": "anomaly"})
    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "invalid:cell_signature_mismatch"
    # ... and the default falls back to the NDCI ranking, never a 500.
    assert client.get("/raster-scan/highlights").json()["mode"] == "ndci"


def test_anomaly_mode_409_for_an_unreadable_season_file(client, tmp_path, cell_root):
    manifest = afx.write_cell_artefact(cell_root, afx.endpoint_stats())
    afx.clear_runs()
    afx.store_run(tmp_path, afx.endpoint_cells(_PEAKS))
    (cell_root / manifest["baseline_version"] / "cells_m09.npz").write_bytes(b"garbage")
    response = client.get("/raster-scan/highlights", params={"mode": "anomaly"})
    assert response.status_code == 409
    assert response.json()["detail"] == {
        "reason": "no_cell_baseline", "cause": "unreadable", "season_key": "m09+-1",
        "message": response.json()["detail"]["message"],
    }


def test_anomaly_mode_with_the_mode_off_is_409_even_without_a_run(client, tmp_path, monkeypatch):
    """No run could make anomaly mode available while the mode is off, so
    that answer comes first (and no baseline file is read)."""
    afx.isolate_baselines(tmp_path / "baselines", monkeypatch, mode="off")
    _clear()
    response = client.get("/raster-scan/highlights", params={"mode": "anomaly"})
    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "mode_off"
    assert client.get("/raster-scan/highlights").status_code == 404


def test_anomaly_mode_409_when_the_blob_has_no_visible_bands(client, tmp_path, cell_root):
    """Never score unscreened cells: explicit anomaly is refused, the default
    falls back to NDCI ranking, which says the screen did not run."""
    afx.write_cell_artefact(cell_root, afx.endpoint_stats())
    afx.clear_runs()
    cells = {k: v for k, v in afx.endpoint_cells(_PEAKS).items() if k not in afx.TRUE_COLOR}
    afx.store_run(tmp_path, cells)
    response = client.get("/raster-scan/highlights", params={"mode": "anomaly"})
    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "visible_bands_missing"
    assert response.json()["detail"]["season_key"] == "m09+-1"
    fallback = client.get("/raster-scan/highlights").json()
    assert fallback["mode"] == "ndci" and set(fallback) == _NDCI_RESPONSE_KEYS
    assert fallback["excluded_low_signal"] is None
    assert "low-signal screen could not run" in fallback["quality_note"]
    assert fallback["disclaimer"] == DISCLAIMER_TEXT


def test_ndci_mode_counts_low_signal_exclusions_on_a_served_run(client, tmp_path, cell_root):
    afx.clear_runs()
    cells = afx.endpoint_cells({(2, 2): 0.4, (8, 8): 0.3})
    position = 2 * afx.EP_COLS + 2
    cells["true_red"][position] = 13.0
    afx.store_run(tmp_path, cells)
    body = client.get("/raster-scan/highlights", params={"mode": "ndci", "n": 3}).json()
    assert body["excluded_low_signal"] == 1 and body["excluded_degenerate"] == 0
    assert body["quality_note"] is None
    assert body["pins"][0]["index_values"]["ndci"] == float(np.float32(0.3))
    assert body["pins"][0]["visible_bands_dn"] == {"red": 500.0, "green": 500.0, "blue": 500.0}
    assert body["cohort_size"] == afx.EP_ROWS * afx.EP_COLS


def test_anomaly_mode_404_when_there_is_no_run_in_test_mode(client, cell_root):
    afx.clear_runs()
    response = client.get("/raster-scan/highlights", params={"mode": "anomaly"})
    assert response.status_code == 404
    assert response.json()["detail"] == _PIXEL_404


def test_anomaly_mode_says_nothing_was_assessable_when_every_cell_predates_history(
        client, tmp_path, cell_root):
    measured = afx.EP_ROWS * afx.EP_COLS
    old = {(r, c): afx.ms_on(afx.HISTORY_END) for r in range(afx.EP_ROWS) for c in range(afx.EP_COLS)}
    _anomaly_run(tmp_path, cell_root, dates=old)
    body = client.get("/raster-scan/highlights", params={"mode": "anomaly"}).json()
    assert body["pins"] == []
    assert body["counts"]["not_after_history"] == measured
    assert body["reason"] == ("no measured cells are assessable against the TEST cell baseline "
                              f"(0 assessable of {measured} measured)")


def test_one_baseline_resolution_per_request(client, tmp_path, cell_root, monkeypatch):
    run_id = _anomaly_run(tmp_path, cell_root)
    calls = {"status": 0, "cells": 0}
    real_status = scientific_status.baseline_status
    real_cells = baseline_store.cell_baseline_or_reason

    def counting_status():
        calls["status"] += 1
        return real_status()

    def counting_cells(season):
        calls["cells"] += 1
        return real_cells(season)

    monkeypatch.setattr(scientific_status, "baseline_status", counting_status)
    monkeypatch.setattr(baseline_store, "cell_baseline_or_reason", counting_cells)
    client.get("/raster-scan/highlights")
    assert calls == {"status": 1, "cells": 1}
    lat, lng = afx.lattice_centre((afx.EP_ROW0 - 1, afx.EP_COL0 + 1))
    client.get("/raster-scan/pixel", params={"lat": lat, "lng": lng, "run_id": run_id})
    assert calls == {"status": 2, "cells": 2}
    client.get("/raster-scan/highlights", params={"mode": "ndci"})
    assert calls == {"status": 2, "cells": 2}, "mode=ndci never consults the baseline"


def test_anomaly_schema_refuses_a_tier_and_a_negative_level():
    from pydantic import ValidationError
    from src.schemas import RasterAnomalyPin

    fields = {
        "rank": 1, "cell_lat": 13.0, "cell_lng": 100.0, "pixel_centre_lat": 13.0,
        "pixel_centre_lng": 100.0, "index_values": {"ndci": 0.1}, "percentile": 50.0,
        "date_ms": 1788492600000, "acquired_date": "2026-09-04",
        "acquired_at": "2026-09-04T03:30:00Z", "edge_of_no_data": False, "metric_value": 2.5,
        "robust_z": 2.5, "median_ndci": 0.02, "mad": 0.01, "n_dates": 40, "anomaly_level": "watch",
    }
    assert RasterAnomalyPin(**fields).risk_tier is None
    with pytest.raises(ValidationError):
        RasterAnomalyPin(**fields, risk_tier="watch")
    with pytest.raises(ValidationError):
        RasterAnomalyPin(**{**fields, "anomaly_level": "normal"})
