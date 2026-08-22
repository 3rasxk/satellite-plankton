"""
Fetches `cloud_fraction`/`actual_date` for a satellite-backed response.

Why this exists: detect()'s and risk_level()'s return shapes (Phase 2,
detection/src/prediction.py) don't include `cloud_fraction`/`actual_date`
even though they compute them internally (via get_sentinel2_bands) --
that data is discarded once indices are computed. backend-api's brief
requires surfacing both on every satellite-backed response
(.claude/agents/backend-api.md "Non-negotiable rules"), and this project
does not modify detection/src (out of scope -- "you do not implement
detection logic yourself").

The tradeoff, stated plainly: this makes a second, separate
get_sentinel2_bands call, duplicating the live Sentinel-2 round trip
detect()/risk_level() already make internally. It is not a duplicated
*decision* (index computation, z-score, thresholding all still happen
exactly once, inside detect()) -- just a duplicated *read* of the same
underlying imagery, which get_sentinel2_bands's own nearest-cloud-free-
image search makes deterministic enough that both calls resolve to the
same actual scene for the same (lat, lng, date).
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
