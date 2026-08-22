"""GET /timeseries -- MODIS chlor_a history + per-point anomaly z-score,
for the site panel / anomaly strip (docs/FRONTEND_PLAN.md §4).

Uses get_modis_chlorophyll_history (the only *bulk* historical series
detection/data-pipeline expose -- Sentinel-2 bands are a per-date point
query, so a per-day Sentinel-2 pull across months of history would mean
one live GEE call per day requested, which is impractical). See
schemas.TimeseriesPoint's docstring-equivalent field descriptions for why
cloud_fraction/actual_date are explicitly null here rather than omitted."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from .. import _detection as bridge
from ..schemas import TimeseriesPoint, TimeseriesResponse

router = APIRouter()

_CLIMATOLOGY_WINDOW_DAYS = 7


@router.get("/timeseries", response_model=TimeseriesResponse, tags=["detection"])
def get_timeseries(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
) -> TimeseriesResponse:
    try:
        history = bridge.get_modis_chlorophyll_history(lat, lng)
    except bridge.GEEAuthError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Google Earth Engine is not authenticated: {exc}",
        ) from exc

    points: list[TimeseriesPoint] = []
    for row in history:
        clim = bridge.day_of_year_climatology(
            history, "chlor_a", row["date"], _CLIMATOLOGY_WINDOW_DAYS
        )
        z = bridge.z_score(row["chlor_a"], clim)
        points.append(
            TimeseriesPoint(
                date=row["date"],
                chlor_a=row["chlor_a"],
                anomaly_z=z["z"],
                reason=z["reason"],
            )
        )

    return TimeseriesResponse(lat=lat, lng=lng, points=points)
