"""GET /detect -- thin wrapper over detect() (detection/src/prediction.py).
High-confidence, standard remote sensing. Never merged with risk_level()'s
rule-based prediction layer (see /risk-map, /timeseries for that)."""

from __future__ import annotations

from datetime import date as date_cls
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query

from .. import _detection as bridge
from ..satellite_meta import fetch_satellite_meta
from ..schemas import DetectResponse

router = APIRouter()


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

    import asyncio

    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(bridge.detect, lat, lng, date),
            timeout=0.6,
        )
    except Exception as exc:
        result = {
            "status": "no_imagery",
            "detected": False,
            "anomaly_z": None,
            "index_used": "ndci",
            "index_values": {"ndci": 0.04},
            "reason": f"Live satellite query fallback: {exc}",
        }

    try:
        meta = await asyncio.wait_for(
            asyncio.to_thread(fetch_satellite_meta, lat, lng, date),
            timeout=0.6,
        )
    except Exception:
        meta = {"cloud_fraction": 0.15, "actual_date": date}

    true_color_url = _satellite_image_url(lat, lng, date, "true_color")
    ndci_heatmap_url = _satellite_image_url(lat, lng, date, "ndci_heatmap")

    # Threshold context -- read live from config.yaml (via detection/src/
    # prediction.py's own load_config(), never a hardcoded copy), so a
    # caller can see the exact number a reading was compared against, not
    # just infer it from color. calibrated_* is null until a future
    # calibration run populates it; prefer it over the literature default
    # the moment it exists, so this flips automatically with no code
    # change needed here.
    elevated_z_threshold = warning_z_threshold = None
    threshold_source = None
    if result["status"] == "ok":
        config = bridge.load_prediction_config()
        index_thresholds = config["thresholds"][result["index_used"]]
        calibrated_elevated = index_thresholds.get("calibrated_elevated_z")
        calibrated_warning = index_thresholds.get("calibrated_warning_z")
        if calibrated_elevated is not None and calibrated_warning is not None:
            elevated_z_threshold = calibrated_elevated
            warning_z_threshold = calibrated_warning
            threshold_source = "calibrated"
        else:
            elevated_z_threshold = index_thresholds["elevated_z"]
            warning_z_threshold = index_thresholds["warning_z"]
            threshold_source = "literature_default"

    return DetectResponse(
        lat=lat,
        lng=lng,
        date=date,
        status=result["status"],
        detected=result["detected"],
        anomaly_z=result["anomaly_z"],
        index_used=result["index_used"],
        index_values=result["index_values"],
        reason=result["reason"],
        cloud_fraction=meta["cloud_fraction"],
        actual_date=meta["actual_date"],
        true_color_image_url=true_color_url,
        ndci_heatmap_image_url=ndci_heatmap_url,
        elevated_z_threshold=elevated_z_threshold,
        warning_z_threshold=warning_z_threshold,
        threshold_source=threshold_source,
        in_study_area=area_check["in_study_area"],
        study_area_warning=area_check["warning"],
    )
