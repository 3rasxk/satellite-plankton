"""Compatibility tombstone for the retired 501-point regional scan."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..schemas import disclaimer_in_force

router = APIRouter(tags=["retired"])


@router.get("/regional-scan", deprecated=True)
async def retired_regional_scan() -> JSONResponse:
    """Direct old clients to the full-area raster replacement."""
    return JSONResponse(
        status_code=410,
        content={
            "detail": "The 501-point regional scan has been retired.",
            "replacement": "/raster-scan",
            # Not a DisclaimerMixin model, so the same never-raising
            # resolution is called by hand: the text for the baseline in force.
            "disclaimer": disclaimer_in_force(),
        },
    )
