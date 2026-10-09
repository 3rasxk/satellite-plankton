"""One Sentinel-2 NDCI reading against a monitoring site's TEST baseline history.

Data sources: a detection result (``detect()`` / ``risk_level()["detection"]``
from ``detection/src/prediction.py``: ``status``, ``index_values["ndci"]``,
``actual_date``) and one snapshot of the TEST baseline from
``scientific_status.baseline_snapshot()`` (status dict + ``ActiveBaseline``
rows). The statistic is ``detection/src/baseline.py``'s ``assess_site``
(robust z of the reading against the site's own strictly-earlier history in
the same seasonal window), called through the bridge; nothing is
recomputed here. This module only decides whether that call may be made,
says why when it may not, and decides which cached results a response may
show.

Used by ``src/scheduler.py`` (the 7-site grid, stored on ``DetectionCache``),
``routers/risk_map.py`` (which cached results to show) and ``routers/detect.py``
(the live reading, only at a baseline site's recorded coordinates).

Limitations:
  * Only with ``BASELINE_MODE=test``; with the mode off every function here
    returns "nothing" and no file is read.
  * The TEST baseline is provisional and uncalibrated: a ``watch``/``high``
    level is a statistical anomaly of one site against its own seasonal
    record, not a bloom detection, not a species and not a forecast. A
    ``normal`` level does not mean safe water.
  * The history was made at each site's recorded coordinates; a reading
    anywhere else is not assessed against it.
  * Satellite pixel resolution: small or dispersed blooms can be missed, and
    sediment or shallow bottom can raise NDCI with no bloom present.
"""

from __future__ import annotations

import logging

from . import _detection as bridge
from .baseline_store import ActiveBaseline

logger = logging.getLogger(__name__)

# Reasons this module gives when it does not call assess_site. Everything
# else is assess_site's own reason, passed through unchanged.
SITE_NOT_IN_BASELINE = "site_not_in_baseline"
SITE_COORDINATES_DIFFER = "site_coordinates_differ_from_baseline"
# The same code assess_signal_anomaly uses for an unusable reading.
MISSING_NDCI = "missing_or_invalid_observation"
ASSESSMENT_FAILED = "assessment_failed"
NOT_ASSESSED_AGAINST_ACTIVE = "not_assessed_against_active_baseline"

# Two coordinates name the same place only when they agree to ~0.1 m: the
# history is a point-buffer mean around the recorded point, so a reading a
# few tens of metres away samples other water.
_SAME_POINT_DEG = 1e-6

_ASSESS_KEYS = ("level", "robust_z", "median_ndci", "mad", "independent_date_count", "reason")


def is_test_mode(status: dict) -> bool:
    return status.get("mode") == "test"


def baseline_block(status: dict) -> dict | None:
    """The response's ``baseline`` block: the status in test mode, else None."""
    return dict(status) if is_test_mode(status) else None


def baseline_invalid_reason(status: dict) -> str:
    return f"baseline_invalid:{status.get('reason') or 'unknown'}"


def _no_assessment(reason: str, location_id: str | None) -> dict:
    return {
        "level": None,
        "robust_z": None,
        "median_ndci": None,
        "mad": None,
        "independent_date_count": None,
        "reason": reason,
        "location_id": location_id,
    }


def _same_point(info: dict, lat: float, lng: float) -> bool:
    try:
        return abs(float(info["lat"]) - lat) <= _SAME_POINT_DEG and abs(float(info["lng"]) - lng) <= _SAME_POINT_DEG
    except (KeyError, TypeError, ValueError):
        return False


def location_at(active: ActiveBaseline | None, lat: float, lng: float) -> str | None:
    """The baseline site whose history was made at exactly (lat, lng), or None."""
    if active is None:
        return None
    for site_id, info in active.manifest["locations"].items():
        if site_id in active.rows_by_location and _same_point(info, lat, lng):
            return site_id
    return None


def assess_reading(
    status: dict,
    active: ActiveBaseline | None,
    *,
    location_id: str | None,
    lat: float,
    lng: float,
    detection: dict,
    target_date: str,
) -> dict | None:
    """Assess one reading against ``location_id``'s history; never raises.

    ``(status, active)`` is ONE ``baseline_snapshot()``. Returns None with the
    mode off. Otherwise a dict with ``level`` (normal|watch|high or None),
    ``robust_z``, ``median_ndci``, ``mad``, ``independent_date_count``,
    ``reason`` (why ``level`` is None) and ``location_id``. ``assess_site``
    is called only for a valid baseline, a site in it recorded at
    (lat, lng) when the manifest records coordinates, an ``ok`` detection
    and a present NDCI; its result is returned unchanged.
    """
    if not is_test_mode(status):
        return None
    if active is None:
        return _no_assessment(baseline_invalid_reason(status), location_id)
    if location_id is None or location_id not in active.rows_by_location:
        return _no_assessment(SITE_NOT_IN_BASELINE, location_id)
    info = active.manifest["locations"].get(location_id, {})
    if ("lat" in info or "lng" in info) and not _same_point(info, lat, lng):
        return _no_assessment(SITE_COORDINATES_DIFFER, location_id)
    if detection.get("status") != "ok":
        return _no_assessment(str(detection.get("status")), location_id)
    ndci = (detection.get("index_values") or {}).get("ndci")
    if ndci is None:
        return _no_assessment(MISSING_NDCI, location_id)
    try:
        result = bridge.baseline_logic.assess_site(
            active.rows_by_location[location_id],
            location_id=location_id,
            current_ndci=ndci,
            actual_date=detection.get("actual_date"),
            target_date=target_date,
            preprocessing_signature=active.manifest["preprocessing_signature"],
        )
    except Exception as exc:  # noqa: BLE001 -- a statistic failure must not discard the reading
        logger.error(
            "site anomaly: assessment failed for %s on %s: %s: %s",
            location_id, target_date, type(exc).__name__, exc,
        )
        return _no_assessment(ASSESSMENT_FAILED, location_id)
    return {**{key: result.get(key) for key in _ASSESS_KEYS}, "location_id": location_id}


def cached_fields(status: dict, cache) -> dict:
    """What a response may show from a cached row under the baseline ``status``.

    ``{"level", "robust_z", "reason"}``. All None with the mode off. With an
    invalid baseline, no level and the refusal as the reason. With a valid
    one, the row's stored values only when the row was assessed against
    exactly ``status["version"]``; any other row (older baseline, never
    assessed) shows no level and ``not_assessed_against_active_baseline``.
    """
    if not is_test_mode(status):
        return {"level": None, "robust_z": None, "reason": None}
    if status.get("valid") is not True:
        return {"level": None, "robust_z": None, "reason": baseline_invalid_reason(status)}
    if cache.baseline_version is None or cache.baseline_version != status.get("version"):
        return {"level": None, "robust_z": None, "reason": NOT_ASSESSED_AGAINST_ACTIVE}
    return {
        "level": cache.signal_anomaly_level,
        "robust_z": cache.signal_robust_z,
        "reason": cache.signal_anomaly_reason,
    }
