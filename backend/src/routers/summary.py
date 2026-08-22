"""GET /summary -- region-wide stats over the monitored grid's cache.
Reads the same DetectionCache table /risk-map does; no live GEE calls."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import _detection as bridge
from ..config import as_aware_utc
from ..db import get_db
from ..db_models import DetectionCache, MonitoredSite
from ..schemas import MostRecentDetection, RiskLevelCounts, SummaryResponse

router = APIRouter()


@router.get("/summary", response_model=SummaryResponse, tags=["summary"])
def get_summary(db: Session = Depends(get_db)) -> SummaryResponse:
    rows = db.execute(
        select(MonitoredSite, DetectionCache)
        .outerjoin(DetectionCache, DetectionCache.site_id == MonitoredSite.site_id)
    ).all()

    counts = RiskLevelCounts()
    stale_count = 0
    fetched_ats: list = []
    most_recent: MostRecentDetection | None = None
    most_recent_dt = None

    for site, cache in rows:
        if cache is None:
            counts.no_data += 1
            continue

        level = cache.level or "normal"
        if level in ("normal", "elevated", "watch", "warning"):
            setattr(counts, level, getattr(counts, level) + 1)

        if cache.stale:
            stale_count += 1

        fetched_at = as_aware_utc(cache.fetched_at)
        if fetched_at is not None:
            fetched_ats.append(fetched_at)

        if cache.detected and fetched_at is not None:
            if most_recent_dt is None or fetched_at > most_recent_dt:
                most_recent_dt = fetched_at
                most_recent = MostRecentDetection(
                    site_id=site.site_id,
                    name=site.name,
                    anomaly_z=cache.anomaly_z,
                    detected=cache.detected,
                    actual_date=cache.actual_date,
                    fetched_at=fetched_at.isoformat(),
                )

    config = bridge.load_prediction_config()

    return SummaryResponse(
        total_sites=len(rows),
        risk_level_counts=counts,
        most_recent_detected_signal=most_recent,
        stale_site_count=stale_count,
        oldest_fetched_at=min(fetched_ats).isoformat() if fetched_ats else None,
        newest_fetched_at=max(fetched_ats).isoformat() if fetched_ats else None,
        prediction_confidence_label=config["prediction_confidence_label"],
    )
