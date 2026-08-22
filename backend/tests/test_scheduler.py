"""Automated test of scheduler.py's failure-marking behavior (the prior
build report proved this manually via live monkeypatching; this is that
same scenario saved as a real, repeatable test). A refresh that raises
must mark the cache row `stale=True` with `error` set, while leaving
every substantive field (status, anomaly_z, index_used, level,
fetched_at, ...) exactly as it was from the prior successful refresh --
a failed refresh must never look like a fresh one, and must never
silently discard/alter the last known-good reading."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select

from src import scheduler as scheduler_module
from src.config import as_aware_utc
from src.db import SessionLocal
from src.db_models import DetectionCache, MonitoredSite
from src.scheduler import refresh_one_site

_TEST_SITE_ID = "pytest_scheduler_failure_site"


def _good_cache_fields(fetched_at: datetime) -> dict:
    """A complete, internally-consistent "prior successful refresh" row
    -- every field DetectionCache carries, all non-None where the real
    scheduler would set them for status='ok'."""
    return dict(
        target_date="2024-03-01",
        status="ok",
        detected=False,
        anomaly_z=-0.42,
        index_used="ndci",
        index_values={"ndci": 0.02, "2bda": 0.03, "3bda": 0.04, "b2_b3_ratio": 0.91},
        reason=None,
        level="normal",
        triggered_rules=[],
        confidence_label="rule-based, indicative -- not a validated forecast",
        sst_anomaly=0.1,
        trend_14d_rising=False,
        rainfall_mm=2.5,
        cloud_fraction=0.05,
        actual_date="2024-02-28",
        fetched_at=fetched_at,
        stale=False,
        error=None,
    )


def test_scheduler_marks_stale_on_failure_without_touching_substantive_fields(client, monkeypatch):
    db = SessionLocal()
    try:
        # Arrange: a dedicated test site (not part of MONITORED_GRID, so
        # it can't collide with other tests reading /risk-map or
        # /summary) with a prior *successful* cache row.
        site = db.get(MonitoredSite, _TEST_SITE_ID)
        if site is None:
            site = MonitoredSite(
                site_id=_TEST_SITE_ID, name="pytest scheduler test site", lat=13.0, lng=100.5
            )
            db.add(site)
            db.commit()
            db.refresh(site)

        original_fetched_at = datetime(2024, 3, 1, 6, 0, 0, tzinfo=timezone.utc)
        good_fields = _good_cache_fields(original_fetched_at)
        db.add(DetectionCache(site_id=_TEST_SITE_ID, **good_fields))
        db.commit()

        # Act: monkeypatch risk_level -- the first thing refresh_one_site
        # calls -- to raise, exactly as it would on a real GEE auth
        # failure mid-refresh, then call the scheduler's per-site refresh
        # function directly (the same function the interval job calls
        # for every site in refresh_grid()).
        def _raise(*_a, **_k):
            raise scheduler_module.bridge.GEEAuthError("forced for test -- scheduler failure")

        monkeypatch.setattr(scheduler_module.bridge, "risk_level", _raise)

        refresh_one_site(db, site, "2024-03-02")

        # Assert: row is marked stale with an error recorded...
        db.expire_all()
        refreshed = db.execute(
            select(DetectionCache).where(DetectionCache.site_id == _TEST_SITE_ID)
        ).scalar_one()

        assert refreshed.stale is True
        assert refreshed.error is not None
        assert "GEEAuthError" in refreshed.error
        assert "forced for test -- scheduler failure" in refreshed.error

        # ...but every substantive field from the prior successful
        # refresh is unchanged -- not silently reset, not silently faked
        # to look like a fresh reading.
        for field, expected in good_fields.items():
            if field in ("stale", "error", "fetched_at"):
                continue
            actual = getattr(refreshed, field)
            assert actual == expected, f"field {field!r} changed on failed refresh: {actual!r} != {expected!r}"

        # fetched_at -- the timestamp of the *last successful* reading --
        # must also be untouched: a failed refresh does not get to claim
        # a new fetch time for data it doesn't have.
        assert as_aware_utc(refreshed.fetched_at) == original_fetched_at

    finally:
        db.execute(delete(DetectionCache).where(DetectionCache.site_id == _TEST_SITE_ID))
        db.execute(delete(MonitoredSite).where(MonitoredSite.site_id == _TEST_SITE_ID))
        db.commit()
        db.close()


def test_scheduler_inserts_stale_placeholder_when_no_prior_row_exists(client, monkeypatch):
    """If the very first scheduled run for a site fails, refresh_one_site
    must still insert a row (status='error', stale=True) -- otherwise
    /risk-map's 'no_data_yet' branch would be stuck forever (see
    scheduler.py's module docstring)."""
    db = SessionLocal()
    try:
        site = MonitoredSite(
            site_id=_TEST_SITE_ID, name="pytest scheduler test site (no prior row)", lat=13.0, lng=100.5
        )
        db.add(site)
        db.commit()
        db.refresh(site)

        def _raise(*_a, **_k):
            raise scheduler_module.bridge.GEEAuthError("forced for test -- first-ever refresh fails")

        monkeypatch.setattr(scheduler_module.bridge, "risk_level", _raise)

        refresh_one_site(db, site, "2024-03-02")

        db.expire_all()
        refreshed = db.execute(
            select(DetectionCache).where(DetectionCache.site_id == _TEST_SITE_ID)
        ).scalar_one()

        assert refreshed.status == "error"
        assert refreshed.stale is True
        assert refreshed.error is not None
        assert "GEEAuthError" in refreshed.error

    finally:
        db.execute(delete(DetectionCache).where(DetectionCache.site_id == _TEST_SITE_ID))
        db.execute(delete(MonitoredSite).where(MonitoredSite.site_id == _TEST_SITE_ID))
        db.commit()
        db.close()
