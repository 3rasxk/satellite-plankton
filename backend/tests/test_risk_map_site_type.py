"""Tests for `RiskMapProperties.site_type` (backend/src/schemas.py).

Added for a human-audit finding (project orchestrator, 2026-08-19/23): two
of src/grid.py's 6 monitoring-grid sites reuse the exact/near-exact
display name of a validated data/validation/events.csv historical event at
a DIFFERENT coordinate --

  - grid 'chaam': "Cha-am coast, Phetchaburi" (12.75, 100.05)
    vs. validated th_004: "Cha-am Coast, Phetchaburi" (12.794, 99.984)
  - grid 'thachin_mouth': "Tha Chin River mouth, Samut Sakhon" (13.50, 100.35)
    vs. validated th_003/th_008/th_012: same name, (13.513, 100.274)

There is no actual data crossover (SitePanel.jsx only ever fetches
/risk-map-sourced sites; /validation is a separate page/response), but a
reader could still mistake a grid site's "today" reading for the
same-named validated event's own record. `site_type` is the typed,
general fix: every /risk-map feature explicitly carries
`site_type: "monitoring_grid"` so the frontend (SitePanel.jsx's
"Live monitoring site" badge) never has to infer this from a name match,
and the distinction is documented in the OpenAPI schema itself.

These tests use the real FastAPI TestClient + isolated SQLite DB
(conftest.py) -- no GEE call involved, /risk-map always reads from the
scheduler's cache (or reports 'no_data_yet' when there is none).
"""

from __future__ import annotations

from sqlalchemy import delete

from src.db import SessionLocal
from src.db_models import DetectionCache, MonitoredSite

_TEST_SITE_ID = "pytest_site_type_test_site"


def test_risk_map_features_all_carry_monitoring_grid_site_type(client):
    """Every /risk-map feature -- including the real 6-site grid, which
    has no scheduler cache yet in a fresh test DB (the 'no_data_yet'
    branch of risk_map.py's get_risk_map) -- must carry
    site_type == 'monitoring_grid', not omit the field or leave it null."""
    resp = client.get("/risk-map")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["features"]) >= 6  # the real MONITORED_GRID, per grid.py

    for feature in body["features"]:
        assert feature["properties"]["site_type"] == "monitoring_grid"


def test_risk_map_site_type_present_on_cached_ok_reading_too(client):
    """Same field, same value, on the OTHER branch of get_risk_map -- a
    site that DOES have a DetectionCache row (the 'ok'/cached-reading
    path) -- so the two code paths that build RiskMapProperties can't
    silently diverge on this field."""
    db = SessionLocal()
    try:
        site = db.get(MonitoredSite, _TEST_SITE_ID)
        if site is None:
            site = MonitoredSite(site_id=_TEST_SITE_ID, name="pytest site_type test site", lat=13.1, lng=100.6)
            db.add(site)
            db.commit()

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
                stale=False,
            )
        )
        db.commit()

        resp = client.get("/risk-map")
        assert resp.status_code == 200
        feature = next(
            f for f in resp.json()["features"] if f["properties"]["site_id"] == _TEST_SITE_ID
        )
        assert feature["properties"]["site_type"] == "monitoring_grid"
    finally:
        db.execute(delete(DetectionCache).where(DetectionCache.site_id == _TEST_SITE_ID))
        db.execute(delete(MonitoredSite).where(MonitoredSite.site_id == _TEST_SITE_ID))
        db.commit()
        db.close()


def test_risk_map_site_type_not_confused_with_validation_events():
    """Sanity check on the underlying data, confirming the collision this
    field exists to disambiguate is real: grid.py's 'chaam' and
    'thachin_mouth' site names match validated events.csv location names
    at a DIFFERENT coordinate. If this assertion ever fails because the
    coordinates now match, the site_type badge is no longer covering a
    real ambiguity for that pair (though it remains a harmless, general
    safeguard either way)."""
    from src.grid import MONITORED_GRID

    chaam = next(s for s in MONITORED_GRID if s["site_id"] == "chaam")
    thachin = next(s for s in MONITORED_GRID if s["site_id"] == "thachin_mouth")

    # Validated events.csv coordinates (data/validation/events.csv, th_004
    # and th_003/th_008/th_012) -- human-sourced, confirmed real
    # coordinates, deliberately hardcoded here as the known-collision
    # baseline this test guards, not read from the CSV itself.
    th_004_coord = (12.794, 99.984)
    th_003_coord = (13.513, 100.274)

    assert (chaam["lat"], chaam["lng"]) != th_004_coord
    assert (thachin["lat"], thachin["lng"]) != th_003_coord
