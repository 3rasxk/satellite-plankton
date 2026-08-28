"""
FastAPI Router for Sentinel-2 Satellite Imagery Extraction.
Provides /api/satellite/pin-preview endpoint for dynamic pin previews.
"""

from __future__ import annotations

from typing import Any, Dict
from fastapi import APIRouter, HTTPException, Query

try:
    from services.sentinel_service import get_sentinel_image_for_pin
except ImportError:
    from ...services.sentinel_service import get_sentinel_image_for_pin

router = APIRouter(prefix="/api/satellite", tags=["Satellite"])


@router.get("/pin-preview")
async def get_pin_preview(
    lat: float = Query(..., description="Latitude of the pin"),
    lon: float = Query(..., description="Longitude of the pin"),
    date: str = Query(..., description="Target date in YYYY-MM-DD format"),
) -> Dict[str, Any]:
    """
    Extracts Sentinel-2 RGB True-Color and NDCI (Chlorophyll Index) preview URLs
    centered on the given map pin coordinates with lookback cloud fallback.
    """
    try:
        result = get_sentinel_image_for_pin(lat=lat, lon=lon, date_str=date)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
