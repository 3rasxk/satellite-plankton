"""One Sentinel-2 read per reading: cloud_fraction comes from detect().

detect() already resolves the scene (get_sentinel2_bands) and now returns
that scene's cloud_fraction beside its actual_date and index values.
/detect and the scheduler must use it rather than resolving the scene a
second time: a second read doubles live GEE round trips and can pick a
newer acquisition, pairing one scene's cloud fraction with another scene's
indices. GEE is never touched: the bridge boundary is replaced.
"""

from __future__ import annotations

from sqlalchemy import delete, select

from src import _detection as bridge
from src import scheduler as scheduler_module
from src.db import SessionLocal
from src.db_models import DetectionCache, MonitoredSite
from src.routers import detect as detect_router
from src.scheduler import refresh_one_site

_SITE_ID = "pytest_single_scene_read"


def _detect_result() -> dict:
    return {
        "index_values": {"ndci": 0.04, "2bda": 1.08, "3bda": 0.01, "b2_b3_ratio": 0.9},
        "actual_date": "2024-03-14",
        "cloud_fraction": 0.07,
        "index_used": "ndci",
        "status": "ok",
        "reason": None,
    }


def _forbid_second_read(monkeypatch):
    def _forbidden(*_a, **_k):
        raise AssertionError("a second Sentinel-2 scene read was made")

    monkeypatch.setattr(bridge, "get_sentinel2_bands", _forbidden)


def test_detect_endpoint_takes_cloud_fraction_from_detect(client, monkeypatch):
    _forbid_second_read(monkeypatch)
    monkeypatch.setattr(detect_router.bridge, "detect", lambda *_a, **_k: _detect_result())

    resp = client.get("/detect", params={"lat": 13.2, "lng": 100.9, "date": "2024-03-15"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["cloud_fraction"] == 0.07
    assert body["actual_date"] == "2024-03-14"


def test_detect_endpoint_null_cloud_fraction_when_no_scene(client, monkeypatch):
    _forbid_second_read(monkeypatch)
    result = _detect_result()
    result.update(status="no_imagery", actual_date=None, cloud_fraction=None,
                  index_values=None, reason="no cloud-free scene")
    monkeypatch.setattr(detect_router.bridge, "detect", lambda *_a, **_k: result)

    resp = client.get("/detect", params={"lat": 13.2, "lng": 100.9, "date": "2024-03-15"})

    assert resp.status_code == 200
    assert resp.json()["cloud_fraction"] is None


def test_scheduler_stores_cloud_fraction_from_the_same_detection(monkeypatch):
    _forbid_second_read(monkeypatch)

    def _fake_risk_level(*_a, **_k):
        return {
            "level": None,
            "signal_anomaly_level": None,
            "triggered_rules": [],
            "detection": _detect_result(),
            "trend_14d": {"rising": False},
            "sst_anomaly": None,
            "rainfall": None,
            "confidence_label": "indicative, rule-based -- not a validated forecast",
        }

    monkeypatch.setattr(scheduler_module.bridge, "risk_level", _fake_risk_level)
    monkeypatch.setattr(
        scheduler_module, "_refresh_images",
        lambda *_a, **_k: dict(true_color_png=None, ndci_heatmap_png=None,
                               image_status="skipped", image_error=None),
    )

    db = SessionLocal()
    try:
        site = db.get(MonitoredSite, _SITE_ID)
        if site is None:
            site = MonitoredSite(site_id=_SITE_ID, name="pytest single read", lat=13.1, lng=100.6)
            db.add(site)
            db.commit()
        refresh_one_site(db, site, "2024-03-15")
        db.expire_all()
        row = db.execute(
            select(DetectionCache).where(DetectionCache.site_id == _SITE_ID)
        ).scalar_one()
        assert row.stale is False, row.error
        assert row.cloud_fraction == 0.07
        assert row.actual_date == "2024-03-14"
    finally:
        db.execute(delete(DetectionCache).where(DetectionCache.site_id == _SITE_ID))
        db.execute(delete(MonitoredSite).where(MonitoredSite.site_id == _SITE_ID))
        db.commit()
        db.close()
