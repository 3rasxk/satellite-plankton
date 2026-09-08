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
from src.db_models import RasterScanRun
from src.raster_scan import render, storage


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
            "no_data": {"base_rgba": [176, 176, 176, 205], "stripe_rgba": [92, 92, 92, 235]},
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
    assert body["legend"]["no_data"]["base_rgba"] == [176, 176, 176, 205]
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
