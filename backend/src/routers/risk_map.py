"""GET /risk-map -- GeoJSON FeatureCollection, one feature per monitored
grid cell. Reads the scheduler's cache (src/db_models.py DetectionCache),
never hits GEE live on a request (CLAUDE.md/backend-api.md: "don't hit
GEE live on every /risk-map request in production shape").

Also GET /risk-map/{site_id}/image -- serves this site's scheduler-cached
PNG bytes (true_color_png/ndci_heatmap_png, see db_models.py and
scheduler.py's "Satellite imagery" docstring section for why this bounded
6-site grid is cached rather than rendered on demand). Like the main
route, this never makes a live GEE call -- it is a DB blob read, so a 404
here means "no cached image for this site right now" (scheduler hasn't
run yet, last detection wasn't 'ok', or the image render itself failed
that cycle), never "GEE is down" (that would be the scheduler's own
concern, logged separately -- see scheduler.py)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import as_aware_utc
from ..db import get_db
from ..db_models import DetectionCache, MonitoredSite
from ..schemas import RiskMapFeature, RiskMapProperties, RiskMapResponse
from ..services.cache_service import get_cached, set_cached

router = APIRouter()
CACHE_KEY_RISK_MAP = "api_risk_map_geojson"


def _cached_image_url(site_id: str, cache: DetectionCache | None, image_type: str) -> str | None:
    """None unless a live PNG blob is actually sitting in the cache row
    for this image_type -- never a URL that's already known to 404."""
    if cache is None:
        return None
    has_bytes = (
        cache.true_color_png is not None
        if image_type == "true_color"
        else cache.ndci_heatmap_png is not None
    )
    if not has_bytes:
        return None
    return f"/risk-map/{site_id}/image?image_type={image_type}"


@router.get("/risk-map", response_model=RiskMapResponse, tags=["risk-map"])
async def get_risk_map(db: Session = Depends(get_db)) -> RiskMapResponse:
    rows = db.execute(
        select(MonitoredSite, DetectionCache)
        .outerjoin(DetectionCache, DetectionCache.site_id == MonitoredSite.site_id)
    ).all()

    features: list[RiskMapFeature] = []
    for site, cache in rows:
        if cache is None:
            # Scheduler hasn't refreshed this site yet (fresh DB / not
            # reached in the first cycle). Reported honestly, not hidden.
            props = RiskMapProperties(
                site_id=site.site_id,
                name=site.name,
                risk_level=None,
                triggered_rules=[],
                confidence_label="no cached reading yet",
                status="no_data_yet",
                detected=None,
                spatial_anomaly_z=None,
                index_used=None,
                stale=True,
            )
        else:
            props = RiskMapProperties(
                site_id=site.site_id,
                name=site.name,
                risk_level=cache.level,
                triggered_rules=cache.triggered_rules or [],
                confidence_label=cache.confidence_label or "no cached reading yet",
                status=cache.status,
                detected=cache.detected,
                spatial_anomaly_z=cache.spatial_anomaly_z,
                index_used=cache.index_used,
                index_values=cache.index_values,
                cloud_fraction=cache.cloud_fraction,
                actual_date=cache.actual_date,
                true_color_image_url=_cached_image_url(site.site_id, cache, "true_color"),
                ndci_heatmap_image_url=_cached_image_url(site.site_id, cache, "ndci_heatmap"),
                fetched_at=(
                    as_aware_utc(cache.fetched_at).isoformat() if cache.fetched_at else None
                ),
                stale=cache.stale,
                error=cache.error,
            )

        features.append(
            RiskMapFeature(
                geometry={"type": "Point", "coordinates": [site.lng, site.lat]},
                properties=props,
            )
        )

    return RiskMapResponse(features=features)


@router.get("/risk-map/{site_id}/image", tags=["risk-map"])
def get_risk_map_site_image(
    site_id: str,
    image_type: Literal["true_color", "ndci_heatmap"] = Query(
        ..., description="'true_color' (RGB) or 'ndci_heatmap' (5-stop risk-ramp NDCI)."
    ),
    db: Session = Depends(get_db),
) -> Response:
    site = db.get(MonitoredSite, site_id)
    if site is None:
        raise HTTPException(status_code=404, detail=f"Unknown site_id: {site_id!r}")

    cache = db.execute(
        select(DetectionCache).where(DetectionCache.site_id == site_id)
    ).scalar_one_or_none()

    if cache is None:
        raise HTTPException(
            status_code=404,
            detail=f"No cached reading yet for site {site_id!r} -- the scheduler has "
            "not completed its first refresh cycle for this site.",
        )

    image_bytes = cache.true_color_png if image_type == "true_color" else cache.ndci_heatmap_png

    if image_bytes is None:
        raise HTTPException(
            status_code=404,
            detail=f"No cached {image_type} image for site {site_id!r}'s latest "
            f"reading ({cache.target_date}): image_status={cache.image_status!r}"
            + (f", {cache.image_error}" if cache.image_error else ""),
        )

    return Response(
        content=image_bytes,
        media_type="image/png",
        headers={
            "X-Actual-Date": cache.actual_date or "",
            "X-Cloud-Fraction": (
                str(cache.cloud_fraction) if cache.cloud_fraction is not None else ""
            ),
            "X-Image-Type": image_type,
            "X-Fetched-At": (
                as_aware_utc(cache.fetched_at).isoformat() if cache.fetched_at else ""
            ),
            "X-Stale": str(cache.stale),
        },
    )
