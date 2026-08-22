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
def get_detect(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    date: str = Query(..., description="YYYY-MM-DD"),
) -> DetectResponse:
    try:
        date_cls.fromisoformat(date)
    except ValueError:
        raise HTTPException(status_code=422, detail="date must be YYYY-MM-DD")

    try:
        result = bridge.detect(lat, lng, date)
    except bridge.GEEAuthError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Google Earth Engine is not authenticated -- the pipeline is "
            f"unusable, not just this one reading: {exc}",
        ) from exc

    # detect()'s own return shape doesn't carry cloud_fraction/actual_date
    # (see src/satellite_meta.py docstring for why and the tradeoff of
    # fetching them with a second call). That second call hits GEE again,
    # so it needs the same GEEAuthError -> 503 guard as the first one --
    # left unguarded, a mid-request auth failure here used to fall through
    # to main.py's generic app-level handler instead of this router's more
    # specific message (found by backend/tests/test_gee_auth_503.py).
    try:
        meta = fetch_satellite_meta(lat, lng, date)
    except bridge.GEEAuthError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Google Earth Engine is not authenticated -- the pipeline is "
            f"unusable, not just this one reading: {exc}",
        ) from exc

    # Image URLs only when the numeric detection itself succeeded --
    # status != 'ok' means no usable Sentinel-2 scene existed for the
    # numeric reading either (no_imagery/no_water_pixels/no_climatology),
    # so a live image render for the same lat/lng/date would fail the
    # same way (same-scene guarantee). Null here, not a URL that's known
    # in advance to 404 -- see schemas.DetectResponse field docs.
    if result["status"] == "ok":
        true_color_url = _satellite_image_url(lat, lng, date, "true_color")
        ndci_heatmap_url = _satellite_image_url(lat, lng, date, "ndci_heatmap")
    else:
        true_color_url = None
        ndci_heatmap_url = None

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
    )
