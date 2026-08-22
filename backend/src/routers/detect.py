"""GET /detect -- thin wrapper over detect() (detection/src/prediction.py).
High-confidence, standard remote sensing. Never merged with risk_level()'s
rule-based prediction layer (see /risk-map, /timeseries for that)."""

from __future__ import annotations

from datetime import date as date_cls

from fastapi import APIRouter, HTTPException, Query

from .. import _detection as bridge
from ..satellite_meta import fetch_satellite_meta
from ..schemas import DetectResponse

router = APIRouter()


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
    )
