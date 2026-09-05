"""Tests for /summary's separation of "not checked yet" from "no usable data".

These are two different facts about a site and must never be reported as
one number (CLAUDE.md's truth boundary: absence of data is reported as
absence, and a loading state is not a finding):

  not_checked_yet -- the scheduler has not reached this site; there is no
                     cache row at all. Says nothing about the water.
  no_usable_data  -- the scheduler did read this site and the read
                     produced no usable value (no_imagery /
                     no_water_pixels / error). A real
                     finding about a real attempt.

Same convention as the rest of this suite: real FastAPI TestClient, real
isolated SQLite DB (conftest.py), no live GEE call anywhere in this file.
"""

from __future__ import annotations

from sqlalchemy import delete, select

from src.db import SessionLocal
from src.db_models import DetectionCache, MonitoredSite


def _clear_cache() -> None:
    db = SessionLocal()
    try:
        db.execute(delete(DetectionCache))
        db.commit()
    finally:
        db.close()


def _site_ids() -> list[str]:
    db = SessionLocal()
    try:
        return [s.site_id for s in db.execute(select(MonitoredSite)).scalars().all()]
    finally:
        db.close()


def _add_cache(**fields) -> None:
    db = SessionLocal()
    try:
        db.add(DetectionCache(**fields))
        db.commit()
    finally:
        db.close()


def test_summary_counts_unread_sites_as_not_checked_yet_not_as_no_usable_data(client):
    """A fresh grid is entirely 'not checked yet' -- not 'no usable data',
    and emphatically not 'normal'."""
    _clear_cache()
    total = len(_site_ids())
    assert total > 0, "fixture precondition: the monitored grid is seeded"

    counts = client.get("/summary").json()["risk_level_counts"]

    assert counts["not_checked_yet"] == total
    assert counts["no_usable_data"] == 0
    assert counts["normal"] == 0
    assert counts["elevated"] == 0
    assert counts["watch"] == 0
    assert counts["warning"] == 0


def test_summary_keeps_the_two_states_distinct_and_never_calls_a_failed_read_normal(client):
    """One real reading + two failed reads + the rest untouched.

    The failed reads must land in no_usable_data, not in not_checked_yet
    (they were attempted) and not in `normal` (nothing was read from that
    water) -- the latter is what the pre-split code did, via
    `cache.level or "normal"`.
    """
    _clear_cache()
    site_ids = _site_ids()
    total = len(site_ids)
    assert total >= 3, "fixture precondition: at least 3 monitored sites"

    _add_cache(
        site_id=site_ids[0], target_date="2026-09-03", status="ok", detected=None,
        spatial_anomaly_z=None, index_used="ndci", level=None, triggered_rules=[],
        index_values={"ndci": 0.2},
        confidence_label="indicative, rule-based -- not a validated forecast",
    )
    # Failed reads: real attempts, no usable value, and crucially level=None
    # -- exactly the shape that used to be miscounted as 'normal'.
    _add_cache(
        site_id=site_ids[1], target_date="2026-09-03", status="no_imagery",
        detected=False, level=None,
    )
    _add_cache(
        site_id=site_ids[2], target_date="2026-09-03", status="error",
        detected=None, level=None, error="forced for test",
    )

    counts = client.get("/summary").json()["risk_level_counts"]

    assert counts["not_evaluated"] == 1, "real indices do not establish a risk level"
    assert counts["watch"] == 0
    assert counts["no_usable_data"] == 2, "both failed reads counted as attempted-but-unusable"
    assert counts["not_checked_yet"] == total - 3, "the untouched sites stay a loading state"
    assert counts["normal"] == 0, "a failed read must never be reported as a normal site"

    # The three buckets partition the grid exactly -- no site double-counted,
    # none dropped, nothing invented to fill a gap.
    assert (
        counts["normal"] + counts["elevated"] + counts["watch"] + counts["warning"]
        + counts["no_usable_data"] + counts["not_checked_yet"] + counts["not_evaluated"]
    ) == total


def test_summary_no_usable_data_sites_still_contribute_freshness_and_staleness(client):
    """A failed attempt is still an attempt: it has a real fetched_at and
    can be stale, so it must keep feeding those fields."""
    _clear_cache()
    site_ids = _site_ids()

    _add_cache(
        site_id=site_ids[0], target_date="2026-09-03", status="error",
        detected=None, level=None, stale=True, error="forced for test",
    )

    body = client.get("/summary").json()

    assert body["risk_level_counts"]["no_usable_data"] == 1
    assert body["stale_site_count"] == 1
    assert body["newest_fetched_at"] is not None
    assert body["oldest_fetched_at"] is not None
