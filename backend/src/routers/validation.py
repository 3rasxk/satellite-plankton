"""GET /validation -- the 14-row per-event table from detection/src's
threshold calibration attempt (thresholds.run()). Never a percentage
(CLAUDE.md truth boundary): counts are reported as plain integers
(n_events, n_matchable, ...), per-event results are a list, leave-one-out
results are a list -- no ratio/percentage field exists anywhere in
schemas.ValidationResponse.

Caches thresholds.run()'s output in DetectionCache's sibling table,
ValidationCache (src/db_models.py), for VALIDATION_CACHE_TTL_HOURS
(src/config.py) -- run() makes a real, slow GEE call (the th_001
regional-proxy attempt) and events.csv/config.yaml don't change between
requests, so re-running it on every /validation hit would be both slow
and pointless.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import _detection as bridge
from ..config import VALIDATION_CACHE_TTL_HOURS, as_aware_utc
from ..db import get_db
from ..db_models import ValidationCache
from ..schemas import LeaveOneOutRow, ValidationEventRow, ValidationResponse

router = APIRouter()


def _validation_image_url(lat: float, lng: float, date: str, image_type: str) -> str:
    """Same URL shape as routers/detect.py's `_satellite_image_url` --
    built from the event's own coordinate and the actual Sentinel-2 scene
    date the matching attempt already resolved (thresholds.py's
    `attempt_satellite_reading` -> entry["actual_date"]), so this resolves
    to the exact same scene the event's spectral indices were computed from
    (same-scene guarantee), not a fresh/different search."""
    qs = urlencode({"lat": lat, "lng": lng, "date": date, "image_type": image_type})
    return f"/satellite-image?{qs}"


def _build_payload() -> dict:
    """Runs thresholds.run() (real GEE call) and reduces it to the plain-
    dict shape stored in ValidationCache.payload / returned to callers."""
    result = bridge.threshold_run()
    primary_index = result["config"]["indices"]["primary"]

    events = []
    for row in result["rows"]:
        # A real index reading and the event's own scene/coordinate are
        # enough to show imagery. No anomaly statistic is computed.
        true_color_url = None
        ndci_heatmap_url = None
        if (row.get("index_values") and row.get("lat") is not None
                and row.get("lng") is not None and row.get("actual_date")):
            true_color_url = _validation_image_url(
                row["lat"], row["lng"], row["actual_date"], "true_color"
            )
            ndci_heatmap_url = _validation_image_url(
                row["lat"], row["lng"], row["actual_date"], "ndci_heatmap"
            )

        events.append(
            {
                "event_id": row["event_id"],
                "date_display": row["date_display"],
                "location_name": row["location_name"],
                "location_precision": row["location_precision"],
                "species": row["species"],
                "cell_count_raw": row["cell_count"]["raw"] or None,
                "cell_count_representative": row["cell_count"]["representative"],
                "matchable": row["matchable"],
                "match_method": row["match_method"],
                "match_reason": row["match_reason"],
                "low_evidentiary_weight": row["low_weight"],
                "index_used": primary_index,
                "index_values": row.get("index_values"),
                "actual_date": row.get("actual_date"),
                "reading_status": row.get("sentinel2_status"),
                "spatial_anomaly_z": None,
                "z_score_status": row["z_score_status"],
                "flagged": None,
                "notes": row["match_reason"] or "",
                "true_color_image_url": true_color_url,
                "ndci_heatmap_image_url": ndci_heatmap_url,
            }
        )

    loo = [
        {
            "iteration_label": it["label"],
            "held_out_event_ids": it["held_out_ids"],
            "caught": it["caught"],
            "reason": it["reason"],
        }
        for it in result["loo_results"]
    ]

    return {
        "n_events": result["n_events"],
        "n_matchable": result["n_matchable"],
        "n_with_real_satellite_reading": result["n_with_real_reading"],
        "events": events,
        "leave_one_out": loo,
    }


@router.get("/validation", response_model=ValidationResponse, tags=["validation"])
def get_validation(
    db: Session = Depends(get_db),
    refresh: bool = Query(
        False, description="Force a live re-run of thresholds.run() instead of serving cache."
    ),
) -> ValidationResponse:
    cached = db.execute(select(ValidationCache).where(ValidationCache.id == 1)).scalar_one_or_none()

    is_fresh = (
        cached is not None
        and datetime.now(timezone.utc) - as_aware_utc(cached.computed_at)
        < timedelta(hours=VALIDATION_CACHE_TTL_HOURS)
    )

    if refresh or not is_fresh:
        try:
            payload = _build_payload()
        except bridge.GEEAuthError as exc:
            if cached is not None:
                # Serve stale cache rather than a hard failure, but this
                # is a live-recompute failure, not a routine cache hit --
                # surfaced via HTTP header-equivalent field so it's never
                # confused with a fresh result.
                response = ValidationResponse(
                    calibration_status="uncalibrated",
                    n_events=cached.payload["n_events"],
                    n_matchable=cached.payload["n_matchable"],
                    n_with_real_satellite_reading=cached.payload["n_with_real_satellite_reading"],
                    events=[ValidationEventRow(**e) for e in cached.payload["events"]],
                    leave_one_out=[LeaveOneOutRow(**r) for r in cached.payload["leave_one_out"]],
                    computed_at=as_aware_utc(cached.computed_at).isoformat(),
                )
                response.calibration_caveat += (
                    " [Serving cached result: live recompute failed with GEEAuthError.]"
                )
                return response
            raise HTTPException(
                status_code=503,
                detail=f"Google Earth Engine is not authenticated and no cached "
                f"validation result exists yet: {exc}",
            ) from exc

        computed_at = datetime.now(timezone.utc)
        if cached is None:
            cached = ValidationCache(id=1, computed_at=computed_at, payload=payload)
            db.add(cached)
        else:
            cached.computed_at = computed_at
            cached.payload = payload
        db.commit()
        db.refresh(cached)

    payload = cached.payload
    return ValidationResponse(
        n_events=payload["n_events"],
        n_matchable=payload["n_matchable"],
        n_with_real_satellite_reading=payload["n_with_real_satellite_reading"],
        events=[ValidationEventRow(**e) for e in payload["events"]],
        leave_one_out=[LeaveOneOutRow(**r) for r in payload["leave_one_out"]],
        computed_at=cached.computed_at.isoformat(),
    )
