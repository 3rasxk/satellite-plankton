"""GET /timeseries -- MODIS chlor_a history + per-point anomaly z-score,
for the site panel / anomaly strip (docs/FRONTEND_PLAN.md §4).

Uses get_modis_chlorophyll_history (the only *bulk* historical series
detection/data-pipeline expose -- Sentinel-2 bands are a per-date point
query, so a per-day Sentinel-2 pull across months of history would mean
one live GEE call per day requested, which is impractical). See
schemas.TimeseriesPoint's docstring-equivalent field descriptions for why
cloud_fraction/actual_date are explicitly null here rather than omitted.

Deliberately no per-point satellite image (no image_url field added to
TimeseriesPoint), despite the human's initial request mentioning imagery
"alongside every detection result" including /timeseries. Two independent
reasons ruled it out, not just latency:

1. Scale: this series returns up to ~880 points for a single lat/lng
   (confirmed range in this project: 2002-07-12 to 2025-11-30 at some
   coordinates). Attaching a rendered image per point would mean ~880
   synchronous live GEE image-render calls in one request -- at this
   endpoint's own measured per-image cost (see backend-api build report:
   +2-4s per true-color render, warm session), that is tens of minutes of
   wall-clock time and hundreds of GEE calls for one page load, not a
   minor inefficiency.
2. Data-type mismatch, independent of scale: this series is MODIS chlor_a
   (~1 km, daily composite, 2002-present climatology baseline per
   CLAUDE.md §0), not Sentinel-2. There is no Sentinel-2 scene tied 1:1 to
   a MODIS timeseries point in the first place -- "the image for this
   point" is not a well-defined thing here the way it is for /detect
   (which IS a specific Sentinel-2-backed reading). Rendering *some*
   Sentinel-2 image near a MODIS point's date would silently blend two
   different satellites/resolutions into what looks like one reading,
   which CLAUDE.md's truth-boundary rules (never conflate detection
   sources) argue against.

The frontend is expected to pair this series with /detect's image fields
(`true_color_image_url`/`ndci_heatmap_image_url`) for whatever single date
is currently selected in the UI (e.g. a click on the anomaly strip) --
that reuses /detect's existing per-date image machinery instead of
duplicating it here, and keeps the Sentinel-2-vs-MODIS distinction
explicit rather than papered over."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from .. import _detection as bridge
from ..schemas import TimeseriesPoint, TimeseriesResponse

router = APIRouter()

_CLIMATOLOGY_WINDOW_DAYS = 7


@router.get("/timeseries", response_model=TimeseriesResponse, tags=["detection"])
async def get_timeseries(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
) -> TimeseriesResponse:
    import asyncio

    # Real, live GEE call -- no artificial timeout. A prior version of
    # this endpoint wrapped the call in `asyncio.wait_for(..., timeout=0.6)`
    # and, on ANY exception (including a real GEEAuthError) or timeout,
    # silently substituted a fabricated sine-wave + hash-seeded series
    # (`_generate_fallback_history`, now removed) that then flowed through
    # real climatology/z-score math and was returned as an ordinary 200 --
    # a direct violation of CLAUDE.md's "never catch-and-fabricate" rule,
    # since a real GEE round trip genuinely takes several seconds to tens
    # of seconds and would essentially always exceed 0.6s. As with
    # routers/detect.py, `get_modis_chlorophyll_history` reports real
    # "no data" conditions via its returned series (sparse/gappy, per its
    # own docstring), not exceptions -- the only exception it documents is
    # GEEAuthError, caught here only to translate it into a clear 503,
    # never to hide it or substitute a fake reading.
    try:
        history = await asyncio.to_thread(bridge.get_modis_chlorophyll_history, lat, lng)
    except bridge.GEEAuthError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Google Earth Engine is not authenticated -- the pipeline is unusable: {exc}",
        )

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
