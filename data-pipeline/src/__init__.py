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

Public functions re-exported here for `bloom-detection`, `backend-api`,
and other downstream consumers:
    get_sentinel2_bands(lat, lng, date)
    get_modis_chlorophyll_history(lat, lng)
    get_modis_sst(lat, lng, date)
    get_rainfall_proxy(lat, lng, date)
    get_true_color_image(lat, lng, date)   -- PNG thumbnail, see imagery.py
    get_ndci_heatmap(lat, lng, date)       -- PNG thumbnail, see imagery.py
"""

from .auth import GEEAuthError, initialize_ee
from .imagery import get_ndci_heatmap, get_true_color_image
from .modis import get_modis_chlorophyll_history, get_modis_sst
from .rainfall import get_rainfall_proxy
from .sentinel2 import (
    NoCloudFreeImageryError,
    NoWaterPixelsError,
    get_sentinel2_bands,
)

__all__ = [
    "GEEAuthError",
    "initialize_ee",
    "get_sentinel2_bands",
    "get_modis_chlorophyll_history",
    "get_modis_sst",
    "get_rainfall_proxy",
    "get_true_color_image",
    "get_ndci_heatmap",
    "NoCloudFreeImageryError",
    "NoWaterPixelsError",
]
