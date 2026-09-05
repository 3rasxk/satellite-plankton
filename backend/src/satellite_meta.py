"""
Fetches `cloud_fraction`/`actual_date` for a satellite-backed response.

This makes a second Sentinel-2 read to obtain cloud_fraction. detect()
already returns its actual_date directly, and API/cache consumers keep
that original date so metadata cannot replace the numeric reading's
provenance. No spectral-index anomaly score or threshold is computed.
"""

from __future__ import annotations

from . import _detection as bridge


def fetch_satellite_meta(lat: float, lng: float, date: str) -> dict:
    """Returns {'cloud_fraction': float | None, 'actual_date': str | None,
    'imagery_status': 'ok' | 'no_imagery' | 'no_water_pixels'}.

    Raises:
        GEEAuthError: propagated, never caught (same rule as detect()).
    """
    try:
        bands = bridge.get_sentinel2_bands(lat, lng, date)
        return {
            "cloud_fraction": bands.get("cloud_fraction"),
            "actual_date": bands.get("actual_date"),
            "imagery_status": "ok",
        }
    except bridge.NoCloudFreeImageryError:
        return {"cloud_fraction": None, "actual_date": None, "imagery_status": "no_imagery"}
    except bridge.NoWaterPixelsError:
        return {"cloud_fraction": None, "actual_date": None, "imagery_status": "no_water_pixels"}
