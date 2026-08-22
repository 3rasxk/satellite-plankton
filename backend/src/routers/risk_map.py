"""GET /risk-map -- GeoJSON FeatureCollection, one feature per monitored
grid cell. Reads the scheduler's cache (src/db_models.py DetectionCache),
never hits GEE live on a request (CLAUDE.md/backend-api.md: "don't hit
GEE live on every /risk-map request in production shape")."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import as_aware_utc
from ..db import get_db
from ..db_models import DetectionCache, MonitoredSite
from ..schemas import RiskMapFeature, RiskMapProperties, RiskMapResponse

router = APIRouter()


@router.get("/risk-map", response_model=RiskMapResponse, tags=["risk-map"])
def get_risk_map(db: Session = Depends(get_db)) -> RiskMapResponse:
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
                risk_level="normal",
                triggered_rules=[],
                confidence_label="no cached reading yet",
                status="no_data_yet",
                detected=None,
                anomaly_z=None,
                index_used=None,
                stale=True,
            )
        else:
            props = RiskMapProperties(
                site_id=site.site_id,
                name=site.name,
                risk_level=cache.level or "normal",
                triggered_rules=cache.triggered_rules or [],
                confidence_label=cache.confidence_label or "no cached reading yet",
                status=cache.status,
                detected=cache.detected,
                anomaly_z=cache.anomaly_z,
                index_used=cache.index_used,
                cloud_fraction=cache.cloud_fraction,
                actual_date=cache.actual_date,
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
