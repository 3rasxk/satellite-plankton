"""
data-pipeline/src — the only package in this project allowed to talk to
Google Earth Engine (GEE).

Data sources: Sentinel-2 (Copernicus, via GEE), MODIS-Aqua Ocean Color
(NASA, via GEE), CHIRPS daily precipitation (UCSB/CHG, via GEE).
Resolution: see each module's docstring — resolution differs per product.
Limitation: every public function requires a working GEE session
(`earthengine authenticate` + optionally `EE_PROJECT_ID`). None of these
functions fabricate data when auth is missing — they raise
`auth.GEEAuthError` instead. Downstream code (`detection/`) must never
catch that error and substitute a placeholder value.

Public functions re-exported here for `bloom-detection` and other
downstream consumers:
    get_sentinel2_bands(lat, lng, date)
    get_modis_chlorophyll_history(lat, lng)
    get_modis_sst(lat, lng, date)
    get_rainfall_proxy(lat, lng, date)
"""

from .auth import GEEAuthError, initialize_ee
from .modis import get_modis_chlorophyll_history, get_modis_sst
from .rainfall import get_rainfall_proxy
from .sentinel2 import get_sentinel2_bands

__all__ = [
    "GEEAuthError",
    "initialize_ee",
    "get_sentinel2_bands",
    "get_modis_chlorophyll_history",
    "get_modis_sst",
    "get_rainfall_proxy",
]
