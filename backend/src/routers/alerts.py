"""
High-Performance Alerts Router (GET /api/alerts & GET /alerts).
Returns lightweight, cached alert payloads with sub-150ms latency.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import as_aware_utc
from ..db import get_db
from ..db_models import DetectionCache, MonitoredSite
from ..services.cache_service import get_cached, set_cached
from ..scientific_status import risk_evaluation_active

router = APIRouter(tags=["alerts"])

CACHE_KEY_ALERTS = "api_alerts_summary"
CACHE_TTL_SECONDS = 300  # 5 minutes


class AlertStation(BaseModel):
    site_id: str
    name: str
    risk_tier: str
    confidence: Optional[float] = None
    coordinates: List[float] = Field(..., description="[lat, lng]")
    spatial_anomaly_z: Optional[float] = None
    actual_date: Optional[str] = None


class AlertsResponse(BaseModel):
    # None when not_evaluated: no evaluation happened, so there is no time to report.
    updated_at: Optional[str] = None
    evaluation_status: Literal["active", "not_evaluated"] = "active"
    # None when not_evaluated: 0 would read as "evaluated, none active".
    total_active_alerts: Optional[int] = None
    highest_risk_tier: Optional[str] = None
    stations: List[AlertStation]


@router.get("/alerts", response_model=AlertsResponse)
@router.get("/api/alerts", response_model=AlertsResponse)
async def get_alerts_summary(db: Session = Depends(get_db)) -> AlertsResponse:
    """
    Returns the cached risk-alert summary. Empty and `not_evaluated` while
    calibrated risk evaluation is disabled.
    Response latency < 150ms on cache hit.
    """
    # Evaluate the scientific gate before cache lookup. A payload cached while
    # evaluation was enabled must not survive a later disable for five minutes.
    if not risk_evaluation_active():
        return AlertsResponse(
            updated_at=None,
            evaluation_status="not_evaluated",
            total_active_alerts=None,
            highest_risk_tier=None,
            stations=[],
        )

    cached = get_cached(CACHE_KEY_ALERTS)
    if cached is not None:
        return AlertsResponse(**cached)

    # Cache miss: fetch from SQLite DB
    rows = db.execute(
        select(MonitoredSite, DetectionCache)
        .outerjoin(DetectionCache, DetectionCache.site_id == MonitoredSite.site_id)
    ).all()

    stations: List[Dict[str, Any]] = []
    highest_tier_priority = {"NORMAL": 0, "ELEVATED": 1, "WATCH": 2, "WARNING": 3}
    highest_priority = 0
    highest_tier_str = None
    latest_ts = datetime.now(timezone.utc).isoformat()

    for site, cache in rows:
        if cache is None:
            continue

        raw_level = cache.level.upper() if cache.level else None
        if raw_level in ["ELEVATED", "WATCH", "WARNING"]:
            z = cache.spatial_anomaly_z

            stations.append({
                "site_id": site.site_id,
                "name": site.name,
                "risk_tier": raw_level,
                # No numeric confidence model exists. Null is explicit and
                # avoids manufacturing a percentage from station coordinates.
                "confidence": None,
                "coordinates": [round(site.lat, 4), round(site.lng, 4)],
                "spatial_anomaly_z": round(z, 2) if z is not None else None,
                "actual_date": cache.actual_date,
            })

            priority = highest_tier_priority.get(raw_level, 0)
            if priority > highest_priority:
                highest_priority = priority
                highest_tier_str = raw_level

        if cache.fetched_at:
            aware_ts = as_aware_utc(cache.fetched_at)
            if aware_ts:
                latest_ts = aware_ts.isoformat()

    result = {
        "updated_at": latest_ts,
        "total_active_alerts": len(stations),
        "highest_risk_tier": highest_tier_str,
        "stations": stations,
    }

    # Store in fast in-memory cache
    set_cached(CACHE_KEY_ALERTS, result, ttl_seconds=CACHE_TTL_SECONDS)

    return AlertsResponse(**result)
