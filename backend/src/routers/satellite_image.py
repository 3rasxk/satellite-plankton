"""GET /satellite-image -- live, on-demand PNG render (true_color or
ndci_heatmap) of the exact Sentinel-2 scene /detect would use for the same
lat/lng/date.

Returns raw image bytes directly (Content-Type: image/png), not wrapped in
JSON/base64 -- lets the frontend use a plain `<img src="...">`, gets
native browser caching, and avoids inflating a JSON payload by base64's
~33% size overhead for no benefit (per the human's request: "lets the
frontend use a plain <img src=...>").

Uses `data-pipeline`'s own defaults for search_window_days/buffer_m/
max_cloud_fraction (the same ones get_sentinel2_bands/detect() use
internally, unless a caller explicitly overrides them here) -- so a URL
built from /detect's own lat/lng/date resolves to the same scene
deterministically (data-pipeline/src/imagery.py's "same-scene guarantee",
extended through this HTTP layer, per .claude/agents/backend-api.md's
brief for this endpoint).

Deliberately NOT cached, unlike /risk-map's fixed 7-site grid (see
scheduler.py): lat/lng/date here is caller-chosen and effectively
unbounded (any point, any date) -- there is no small, enumerable key space
worth pre-rendering, the same reasoning /detect itself already applies to
the numeric path. Real, live-measured latency for this endpoint (warm GEE
session, real Gulf of Thailand coordinate, see the backend-api build
report): numeric-only ~4.2s; true_color adds ~+2-4s; ndci_heatmap adds
~+2-3s -- so every call here is genuinely a multi-second live GEE round
trip, by design, not an oversight.

Error mapping (mirrors routers/detect.py's GEEAuthError handling, extended
to the two additional failure modes this endpoint can hit that /detect's
own response never raises out of its own status field):
    GEEAuthError            -> 503 (GEE session itself unusable)
    NoCloudFreeImageryError -> 404 (no scene on or before the requested
                                date, within the scene-age ceiling, meets
                                the cloud threshold -- a real, expected
                                data gap, not a server error)
    NoWaterPixelsError      -> 404 (sample buffer is entirely land per the
                                JRC Global Surface Water mask)
    urllib.error.URLError   -> 502 (scene resolved fine; the thumbnail
                                fetch itself failed -- a transient
                                upstream/network problem, distinct from
                                both of the above)
No placeholder, blank, or stale-date image is ever substituted for any of
these -- the caller gets an honest, typed HTTP error instead (CLAUDE.md:
never overclaim / never fabricate).
"""

from __future__ import annotations

import urllib.error
from datetime import date as date_cls
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Response

from .. import _detection as bridge

router = APIRouter()

# Looked up dynamically (getattr on the `bridge` module at call time, not
# bound into a dict at import time) so tests can monkeypatch
# `satellite_image.bridge.get_true_color_image`/`get_ndci_heatmap` the same
# way every other router in this project monkeypatches `bridge.*`
# (see backend/tests/test_gee_auth_503.py) -- a dict built once at import
# time would have captured the original function object and silently
# ignored a monkeypatch applied afterward.
_RENDERER_NAMES = {
    "true_color": "get_true_color_image",
    "ndci_heatmap": "get_ndci_heatmap",
}


@router.get("/satellite-image", tags=["detection"])
def get_satellite_image(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    date: str = Query(..., description="YYYY-MM-DD"),
    image_type: Literal["true_color", "ndci_heatmap"] = Query(
        ..., description="'true_color' (RGB) or 'ndci_heatmap' (5-stop NDCI visualization ramp)."
    ),
) -> Response:
    try:
        date_cls.fromisoformat(date)
    except ValueError:
        raise HTTPException(status_code=422, detail="date must be YYYY-MM-DD")

    render = getattr(bridge, _RENDERER_NAMES[image_type])

    try:
        result = render(lat, lng, date)
    except bridge.GEEAuthError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Google Earth Engine is not authenticated -- the pipeline is "
            f"unusable, not just this one image: {exc}",
        ) from exc
    except bridge.NoCloudFreeImageryError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"No cloud-free Sentinel-2 imagery available for this location "
            f"on or before {date}, within the scene-age ceiling: {exc}",
        ) from exc
    except bridge.NoWaterPixelsError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"No water pixels in the sample buffer for this location -- "
            f"entirely land per the JRC Global Surface Water mask: {exc}",
        ) from exc
    except urllib.error.URLError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"The Sentinel-2 scene resolved but fetching the rendered "
            f"thumbnail from Google Earth Engine failed (network/upstream "
            f"error), not a data-availability problem: {exc}",
        ) from exc

    return Response(
        content=result["image_bytes"],
        media_type=f"image/{result['image_format']}",
        headers={
            # Surfaced even in a binary response -- CLAUDE.md/backend-api.md:
            # "never silently substitute a different date without saying
            # so." A client inspecting these headers can see the actual
            # scene date/cloud fraction behind the picture it just got.
            "X-Actual-Date": str(result["actual_date"]),
            "X-Cloud-Fraction": str(result["cloud_fraction"]),
            "X-Image-Type": image_type,
            "X-Requested-Date": date,
        },
    )
