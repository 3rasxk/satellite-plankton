"""GET /detect -- thin wrapper over detect() (detection/src/prediction.py).
Returns measured spectral indices; no valid anomaly baseline exists yet.
Never merged with risk_level()'s rule-based prediction layer."""

from __future__ import annotations

import asyncio
from datetime import date as date_cls
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query
from starlette.concurrency import run_in_threadpool

from .. import _detection as bridge
from .. import scientific_status, site_anomaly
from ..schemas import DetectResponse

router = APIRouter()


def _signal_anomaly(lat: float, lng: float, date: str, result: dict) -> tuple[dict | None, dict | None]:
    """``(signal_anomaly, baseline block)`` for this live reading; both None with the mode off.

    One baseline snapshot. The reading is assessed only against the history
    of the baseline site recorded at exactly this lat/lng (anywhere else:
    ``site_not_in_baseline``). Blocking (file reads, the assessment), so the
    caller runs it in a threadpool.
    """
    status, active = scientific_status.baseline_snapshot()
    assessment = site_anomaly.assess_reading(
        status, active,
        location_id=site_anomaly.location_at(active, lat, lng),
        lat=lat, lng=lng, detection=result, target_date=date,
    )
    return assessment, site_anomaly.baseline_block(status)


def _satellite_image_url(lat: float, lng: float, date: str, image_type: str) -> str:
    """Build a /satellite-image URL from this response's own lat/lng/date
    -- no extra GEE call here, just URL construction (per backend-api.md's
    brief: "cheap to add, no extra GEE call inside /detect itself")."""
    qs = urlencode({"lat": lat, "lng": lng, "date": date, "image_type": image_type})
    return f"/satellite-image?{qs}"


@router.get("/detect", response_model=DetectResponse, tags=["detection"])
async def get_detect(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    date: str = Query(..., description="YYYY-MM-DD"),
) -> DetectResponse:
    try:
        date_cls.fromisoformat(date)
    except ValueError:
        raise HTTPException(status_code=422, detail="date must be YYYY-MM-DD")

    # Study-area check -- pure, no GEE call, runs regardless of what
    # happens below. Never blocks or short-circuits the request (an
    # out-of-area point is still a real query, just flagged, per the
    # human's "don't silently accept" requirement, not a "don't accept").
    area_check = bridge.check_point_in_study_area(lat, lng)

    # Real, live GEE calls -- detect() measured 4-26s depending on
    # cloud-search cost (see docs/superpowers/specs/
    # 2026-08-31-regional-scan-design.md §2's measurement of the same
    # underlying pipeline). No timeout here: a prior version of this
    # endpoint wrapped both calls in `asyncio.wait_for` with a 0.6s
    # timeout and, on ANY exception (including a real GEEAuthError),
    # substituted a fabricated result (index_values={"ndci": 0.04},
    # cloud_fraction=0.15) -- a direct violation of CLAUDE.md's "never
    # catch-and-fabricate" rule, since the real call almost always takes
    # longer than 0.6s. detect() already reports real "no data"
    # conditions (no_imagery/no_water_pixels) as honest status fields,
    # not exceptions -- the only exception it can raise is GEEAuthError,
    # which is caught here only to translate it into a clear 503 (never to hide it or
    # substitute a fake reading), matching src/_detection.py's own
    # documented contract for this bridge.
    try:
        result = await asyncio.to_thread(bridge.detect, lat, lng, date)
    except bridge.GEEAuthError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Google Earth Engine is not authenticated -- the pipeline is unusable: {exc}",
        )

    # Null unless status == 'ok' -- a second live render for a scene that
    # already had no usable numeric reading would fail the same way (see
    # DetectResponse.true_color_image_url's own docstring), so don't hand
    # the frontend a URL guaranteed to 404.
    actual_date = result.get("actual_date")
    has_scene = result["status"] == "ok" and actual_date is not None
    true_color_url = _satellite_image_url(lat, lng, actual_date, "true_color") if has_scene else None
    ndci_heatmap_url = _satellite_image_url(lat, lng, actual_date, "ndci_heatmap") if has_scene else None

    signal_anomaly, baseline = await run_in_threadpool(_signal_anomaly, lat, lng, date, result)

    return DetectResponse(
        lat=lat,
        lng=lng,
        date=date,
        status=result["status"],
        detected=None,
        spatial_anomaly_z=None,
        signal_anomaly_level=signal_anomaly["level"] if signal_anomaly is not None else None,
        signal_anomaly=signal_anomaly,
        baseline=baseline,
        index_used=result["index_used"],
        index_values=result["index_values"],
        reason=result["reason"],
        # Same scene as index_values/actual_date: detect() returns it, so
        # no second Sentinel-2 read can pair it with a newer acquisition.
        cloud_fraction=result.get("cloud_fraction"),
        actual_date=actual_date,
        true_color_image_url=true_color_url,
        ndci_heatmap_image_url=ndci_heatmap_url,
        elevated_z_threshold=None,
        warning_z_threshold=None,
        threshold_source=None,
        in_study_area=area_check["in_study_area"],
        study_area_warning=area_check["warning"],
    )
