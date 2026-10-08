"""Tests for the satellite-image feature added on top of the finished
backend (GET /satellite-image, /detect's true_color_image_url/
ndci_heatmap_image_url fields, /risk-map's per-feature image URLs +
GET /risk-map/{site_id}/image, and scheduler.py's per-cycle image
caching for the 6-site monitored grid).

Same convention as the rest of this suite: real FastAPI TestClient, real
isolated SQLite DB (conftest.py), GEE mocked at the `bridge` boundary for
the bulk of these tests. Two tests at the bottom (`test_live_*`) are
deliberately NOT mocked. They run only with `--live-gee`, make a real GEE
call, and prove actual PNG bytes and the same-scene guarantee through the
HTTP layer. Everything in the ordinary suite is network-free.
"""

from __future__ import annotations

import urllib.error

import pytest
from sqlalchemy import delete, select

from src import _detection as bridge
from src import scheduler as scheduler_module
from src.db import SessionLocal
from src.db_models import DetectionCache, MonitoredSite
from src.routers import detect as detect_router
from src.routers import satellite_image as satellite_image_router
from src.scheduler import _refresh_images, refresh_one_site

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _fake_image_result(actual_date: str = "2024-03-14", cloud_fraction: float = 0.05) -> dict:
    return {
        "image_bytes": _PNG_MAGIC + b"fake-png-bytes-for-test",
        "image_format": "png",
        "actual_date": actual_date,
        "cloud_fraction": cloud_fraction,
    }


# ---------------------------------------------------------------------------
# GET /satellite-image -- mocked GEE boundary
# ---------------------------------------------------------------------------


def test_satellite_image_true_color_returns_png_bytes_and_headers(client, monkeypatch):
    monkeypatch.setattr(
        satellite_image_router.bridge, "get_true_color_image", lambda *a, **k: _fake_image_result()
    )

    resp = client.get(
        "/satellite-image",
        params={"lat": 13.45, "lng": 100.65, "date": "2024-03-15", "image_type": "true_color"},
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content == _fake_image_result()["image_bytes"]
    assert resp.headers["x-actual-date"] == "2024-03-14"
    assert resp.headers["x-cloud-fraction"] == "0.05"
    assert resp.headers["x-image-type"] == "true_color"
    assert resp.headers["x-requested-date"] == "2024-03-15"


def test_satellite_image_ndci_heatmap_returns_png_bytes(client, monkeypatch):
    monkeypatch.setattr(
        satellite_image_router.bridge, "get_ndci_heatmap", lambda *a, **k: _fake_image_result()
    )

    resp = client.get(
        "/satellite-image",
        params={"lat": 13.45, "lng": 100.65, "date": "2024-03-15", "image_type": "ndci_heatmap"},
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.headers["x-image-type"] == "ndci_heatmap"


def test_satellite_image_geeautherror_to_503(client, monkeypatch):
    def _raise(*_a, **_k):
        raise bridge.GEEAuthError("forced for test -- satellite-image auth failure")

    monkeypatch.setattr(satellite_image_router.bridge, "get_true_color_image", _raise)

    resp = client.get(
        "/satellite-image",
        params={"lat": 13.45, "lng": 100.65, "date": "2024-03-15", "image_type": "true_color"},
    )
    assert resp.status_code == 503
    assert "not authenticated" in resp.json()["detail"]


def test_satellite_image_no_cloud_free_imagery_to_404(client, monkeypatch):
    def _raise(*_a, **_k):
        raise bridge.NoCloudFreeImageryError("forced -- no scene met the cloud threshold")

    monkeypatch.setattr(satellite_image_router.bridge, "get_true_color_image", _raise)

    resp = client.get(
        "/satellite-image",
        params={"lat": 13.45, "lng": 100.65, "date": "2024-03-15", "image_type": "true_color"},
    )
    assert resp.status_code == 404
    assert "No cloud-free Sentinel-2 imagery" in resp.json()["detail"]


def test_satellite_image_no_water_pixels_to_404(client, monkeypatch):
    def _raise(*_a, **_k):
        raise bridge.NoWaterPixelsError("forced -- all-land buffer")

    monkeypatch.setattr(satellite_image_router.bridge, "get_ndci_heatmap", _raise)

    resp = client.get(
        "/satellite-image",
        params={"lat": 13.45, "lng": 100.65, "date": "2024-03-15", "image_type": "ndci_heatmap"},
    )
    assert resp.status_code == 404
    assert "water pixels" in resp.json()["detail"]


def test_satellite_image_thumbnail_fetch_network_error_to_502(client, monkeypatch):
    def _raise(*_a, **_k):
        raise urllib.error.URLError("forced -- thumbnail fetch network failure")

    monkeypatch.setattr(satellite_image_router.bridge, "get_true_color_image", _raise)

    resp = client.get(
        "/satellite-image",
        params={"lat": 13.45, "lng": 100.65, "date": "2024-03-15", "image_type": "true_color"},
    )
    assert resp.status_code == 502
    assert "thumbnail" in resp.json()["detail"]


def test_satellite_image_bad_date_422(client):
    resp = client.get(
        "/satellite-image",
        params={"lat": 13.45, "lng": 100.65, "date": "not-a-date", "image_type": "true_color"},
    )
    assert resp.status_code == 422


def test_satellite_image_bad_image_type_422(client):
    resp = client.get(
        "/satellite-image",
        params={"lat": 13.45, "lng": 100.65, "date": "2024-03-15", "image_type": "bogus"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# /detect -- true_color_image_url / ndci_heatmap_image_url
# ---------------------------------------------------------------------------


def _valid_detect_result() -> dict:
    return {
        "index_values": {"ndci": 0.01, "2bda": 0.02, "3bda": 0.03, "b2_b3_ratio": 0.9},
        "actual_date": "2024-03-14",
        "index_used": "ndci",
        "status": "ok",
        "reason": None,
    }


def test_detect_includes_image_urls_when_status_ok(client, monkeypatch):
    monkeypatch.setattr(detect_router.bridge, "detect", lambda *a, **k: _valid_detect_result())

    resp = client.get("/detect", params={"lat": 13.2, "lng": 100.9, "date": "2024-03-15"})
    assert resp.status_code == 200
    body = resp.json()

    assert body["true_color_image_url"] == (
        "/satellite-image?lat=13.2&lng=100.9&date=2024-03-14&image_type=true_color"
    )
    assert body["ndci_heatmap_image_url"] == (
        "/satellite-image?lat=13.2&lng=100.9&date=2024-03-14&image_type=ndci_heatmap"
    )
    # No extra GEE call made inside /detect for these URLs -- just string
    # construction from the coordinate and numeric reading's scene date.


def test_detect_image_urls_null_when_status_not_ok(client, monkeypatch):
    result = dict(_valid_detect_result())
    result.update(status="no_imagery", actual_date=None, reason="no cloud-free scene")
    monkeypatch.setattr(detect_router.bridge, "detect", lambda *a, **k: result)

    resp = client.get("/detect", params={"lat": 13.2, "lng": 100.9, "date": "2024-03-15"})
    assert resp.status_code == 200
    body = resp.json()

    assert body["status"] == "no_imagery"
    assert body["true_color_image_url"] is None
    assert body["ndci_heatmap_image_url"] is None


# ---------------------------------------------------------------------------
# GET /risk-map/{site_id}/image + /risk-map's per-feature image URLs
# ---------------------------------------------------------------------------

_TEST_SITE_ID = "pytest_satellite_image_site"


def _make_test_site(db) -> MonitoredSite:
    site = db.get(MonitoredSite, _TEST_SITE_ID)
    if site is None:
        site = MonitoredSite(
            site_id=_TEST_SITE_ID, name="pytest satellite-image test site", lat=13.1, lng=100.6
        )
        db.add(site)
        db.commit()
        db.refresh(site)
    return site


def test_risk_map_image_endpoint_404_unknown_site(client):
    resp = client.get("/risk-map/does_not_exist/image", params={"image_type": "true_color"})
    assert resp.status_code == 404
    assert "Unknown site_id" in resp.json()["detail"]


def test_risk_map_image_endpoint_404_no_cache_row_yet(client):
    db = SessionLocal()
    try:
        _make_test_site(db)
        resp = client.get(f"/risk-map/{_TEST_SITE_ID}/image", params={"image_type": "true_color"})
        assert resp.status_code == 404
        assert "No cached reading yet" in resp.json()["detail"]
    finally:
        db.execute(delete(MonitoredSite).where(MonitoredSite.site_id == _TEST_SITE_ID))
        db.commit()
        db.close()


def test_risk_map_image_endpoint_404_when_image_not_cached_this_cycle(client):
    """Numeric detection succeeded but image_status was
    'skipped_detection_not_ok' (or otherwise no bytes) -- must 404 with a
    reason, never fall back to a placeholder image."""
    db = SessionLocal()
    try:
        _make_test_site(db)
        db.add(
            DetectionCache(
                site_id=_TEST_SITE_ID,
                target_date="2024-03-15",
                status="no_imagery",
                detected=False,
                image_status="skipped_detection_not_ok",
                stale=False,
            )
        )
        db.commit()

        resp = client.get(f"/risk-map/{_TEST_SITE_ID}/image", params={"image_type": "true_color"})
        assert resp.status_code == 404
        assert "skipped_detection_not_ok" in resp.json()["detail"]
    finally:
        db.execute(delete(DetectionCache).where(DetectionCache.site_id == _TEST_SITE_ID))
        db.execute(delete(MonitoredSite).where(MonitoredSite.site_id == _TEST_SITE_ID))
        db.commit()
        db.close()


def test_risk_map_image_endpoint_serves_cached_bytes_and_risk_map_exposes_the_url(client):
    """Full path: a DetectionCache row with real cached PNG bytes ->
    /risk-map's feature carries a non-null image URL -> that URL, fetched,
    returns exactly those bytes with no live GEE call involved."""
    db = SessionLocal()
    try:
        _make_test_site(db)
        png_bytes = _PNG_MAGIC + b"cached-true-color-bytes"
        ndci_bytes = _PNG_MAGIC + b"cached-ndci-bytes"
        db.add(
            DetectionCache(
                site_id=_TEST_SITE_ID,
                target_date="2024-03-15",
                status="ok",
                detected=False,
                spatial_anomaly_z=None,
                index_used="ndci",
                actual_date="2024-03-14",
                cloud_fraction=0.05,
                true_color_png=png_bytes,
                ndci_heatmap_png=ndci_bytes,
                image_status="ok",
                stale=False,
            )
        )
        db.commit()

        risk_map_resp = client.get("/risk-map")
        assert risk_map_resp.status_code == 200
        feature = next(
            f for f in risk_map_resp.json()["features"]
            if f["properties"]["site_id"] == _TEST_SITE_ID
        )
        props = feature["properties"]
        assert props["true_color_image_url"] == f"/risk-map/{_TEST_SITE_ID}/image?image_type=true_color"
        assert props["ndci_heatmap_image_url"] == f"/risk-map/{_TEST_SITE_ID}/image?image_type=ndci_heatmap"

        img_resp = client.get(props["true_color_image_url"])
        assert img_resp.status_code == 200
        assert img_resp.headers["content-type"] == "image/png"
        assert img_resp.content == png_bytes
        assert img_resp.headers["x-actual-date"] == "2024-03-14"
        assert img_resp.headers["x-stale"] == "False"

        ndci_resp = client.get(props["ndci_heatmap_image_url"])
        assert ndci_resp.status_code == 200
        assert ndci_resp.content == ndci_bytes
    finally:
        db.execute(delete(DetectionCache).where(DetectionCache.site_id == _TEST_SITE_ID))
        db.execute(delete(MonitoredSite).where(MonitoredSite.site_id == _TEST_SITE_ID))
        db.commit()
        db.close()


def test_risk_map_feature_has_null_image_urls_when_no_cache_row(client):
    """MONITORED_GRID sites always exist; a site with no DetectionCache
    row at all (fresh DB) must report null image URLs, not a URL that
    would 404 if followed."""
    resp = client.get("/risk-map")
    assert resp.status_code == 200
    for feature in resp.json()["features"]:
        props = feature["properties"]
        if props["status"] == "no_data_yet":
            assert props["true_color_image_url"] is None
            assert props["ndci_heatmap_image_url"] is None


# ---------------------------------------------------------------------------
# scheduler._refresh_images -- unit tests (no HTTP layer)
# ---------------------------------------------------------------------------


def test_refresh_images_skips_when_detection_status_not_ok():
    result = _refresh_images(13.1, 100.6, "2024-03-15", "no_imagery")
    assert result["true_color_png"] is None
    assert result["ndci_heatmap_png"] is None
    assert result["image_status"] == "skipped_detection_not_ok"
    assert result["image_error"] is None


def test_refresh_images_ok_when_render_succeeds(monkeypatch):
    monkeypatch.setattr(scheduler_module.bridge, "get_true_color_image", lambda *a, **k: _fake_image_result())
    monkeypatch.setattr(scheduler_module.bridge, "get_ndci_heatmap", lambda *a, **k: _fake_image_result())

    result = _refresh_images(13.1, 100.6, "2024-03-15", "ok")
    assert result["true_color_png"] == _fake_image_result()["image_bytes"]
    assert result["ndci_heatmap_png"] == _fake_image_result()["image_bytes"]
    assert result["image_status"] == "ok"
    assert result["image_error"] is None


def test_refresh_images_no_cloud_free_imagery_marks_status_without_raising(monkeypatch):
    def _raise(*_a, **_k):
        raise bridge.NoCloudFreeImageryError("forced")

    monkeypatch.setattr(scheduler_module.bridge, "get_true_color_image", _raise)

    result = _refresh_images(13.1, 100.6, "2024-03-15", "ok")
    assert result["true_color_png"] is None
    assert result["image_status"] == "no_imagery"
    assert "forced" in result["image_error"]


def test_refresh_images_no_water_pixels_marks_status_without_raising(monkeypatch):
    def _raise(*_a, **_k):
        raise bridge.NoWaterPixelsError("forced")

    monkeypatch.setattr(scheduler_module.bridge, "get_true_color_image", _raise)

    result = _refresh_images(13.1, 100.6, "2024-03-15", "ok")
    assert result["image_status"] == "no_water_pixels"


def test_refresh_images_generic_fetch_error_does_not_raise():
    """A transient thumbnail-fetch failure must not propagate -- the
    numeric detection already succeeded and refresh_one_site must not
    discard it over an image-only problem."""

    def _raise(*_a, **_k):
        raise urllib.error.URLError("forced -- network hiccup")

    import src.scheduler as sm

    orig = sm.bridge.get_true_color_image
    sm.bridge.get_true_color_image = _raise
    try:
        result = _refresh_images(13.1, 100.6, "2024-03-15", "ok")
    finally:
        sm.bridge.get_true_color_image = orig

    assert result["true_color_png"] is None
    assert result["image_status"] == "fetch_error"
    assert "network hiccup" in result["image_error"]


def test_refresh_images_geeautherror_propagates(monkeypatch):
    """Unlike the data-gap errors above, GEEAuthError must propagate --
    the caller (refresh_one_site) needs to mark the WHOLE site stale, not
    just the images, since it means the GEE session itself is down."""

    def _raise(*_a, **_k):
        raise bridge.GEEAuthError("forced -- session down")

    monkeypatch.setattr(scheduler_module.bridge, "get_true_color_image", _raise)

    try:
        _refresh_images(13.1, 100.6, "2024-03-15", "ok")
        raised = False
    except bridge.GEEAuthError:
        raised = True
    assert raised, "GEEAuthError must propagate out of _refresh_images, not be swallowed"


def test_refresh_one_site_geeautherror_from_images_marks_whole_site_stale(monkeypatch):
    """End-to-end within the scheduler: risk_level() succeeds, but the
    image render then raises GEEAuthError -- refresh_one_site's own
    top-level except must catch it (same as any other GEEAuthError) and
    mark the site stale, not just skip the images."""
    db = SessionLocal()
    try:
        site = _make_test_site(db)

        def _fake_risk_level(*_a, **_k):
            return {
                "level": "normal",
                "triggered_rules": [],
                "detection": {
                    "status": "ok", "actual_date": "2024-03-14",
                    "index_used": "ndci", "index_values": {}, "reason": None,
                },
                "trend_14d": {"rising": False},
                "sst_anomaly": None,
                "rainfall": None,
                "confidence_label": "indicative, rule-based -- not a validated forecast",
            }

        def _raise_auth(*_a, **_k):
            raise bridge.GEEAuthError("forced -- image render hits auth failure")

        monkeypatch.setattr(scheduler_module.bridge, "risk_level", _fake_risk_level)
        monkeypatch.setattr(scheduler_module.bridge, "get_true_color_image", _raise_auth)

        refresh_one_site(db, site, "2024-03-15")

        db.expire_all()
        row = db.execute(
            select(DetectionCache).where(DetectionCache.site_id == _TEST_SITE_ID)
        ).scalar_one()
        assert row.stale is True
        assert row.error is not None
        assert "GEEAuthError" in row.error
    finally:
        db.execute(delete(DetectionCache).where(DetectionCache.site_id == _TEST_SITE_ID))
        db.execute(delete(MonitoredSite).where(MonitoredSite.site_id == _TEST_SITE_ID))
        db.commit()
        db.close()


# ---------------------------------------------------------------------------
# Live GEE tests -- real network calls, not mocked. Requires real GEE auth
# (this project's data-pipeline/.env has EE_PROJECT_ID set). Slower
# (several seconds each) by design -- see module docstring.
# ---------------------------------------------------------------------------

# chaophraya_mouth from src/grid.py -- live-confirmed 'ok' (real index reading)
# at date 2024-03-15 during this project's build.
_LIVE_LAT, _LIVE_LNG, _LIVE_DATE = 13.4500, 100.6500, "2024-03-15"


@pytest.mark.live_gee
def test_live_satellite_image_true_color_returns_real_png(client):
    resp = client.get(
        "/satellite-image",
        params={"lat": _LIVE_LAT, "lng": _LIVE_LNG, "date": _LIVE_DATE, "image_type": "true_color"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content[:8] == _PNG_MAGIC
    assert len(resp.content) > 5000  # a real rendered thumbnail, not an empty/error stub
    assert resp.headers["x-actual-date"]  # real scene date, non-empty


@pytest.mark.live_gee
def test_live_satellite_image_actual_date_matches_detect_same_scene_guarantee(client):
    """The same-scene guarantee (data-pipeline/src/imagery.py), proven
    live through the full HTTP stack: /detect's own actual_date for this
    lat/lng/date must equal /satellite-image's X-Actual-Date header for
    the same lat/lng/date -- both must resolve to the identical Sentinel-2
    scene, not just claim to."""
    detect_resp = client.get(
        "/detect", params={"lat": _LIVE_LAT, "lng": _LIVE_LNG, "date": _LIVE_DATE}
    )
    assert detect_resp.status_code == 200
    detect_body = detect_resp.json()
    assert detect_body["status"] == "ok"
    assert detect_body["true_color_image_url"] is not None

    image_resp = client.get(
        "/satellite-image",
        params={"lat": _LIVE_LAT, "lng": _LIVE_LNG, "date": _LIVE_DATE, "image_type": "true_color"},
    )
    assert image_resp.status_code == 200
    assert image_resp.headers["x-actual-date"] == detect_body["actual_date"]
