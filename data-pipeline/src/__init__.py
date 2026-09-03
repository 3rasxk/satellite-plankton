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
    check_point_in_study_area(lat, lng)    -- boundary check, see study_area.py
                                               (pure, no GEE call -- doesn't
                                               need auth to run)
    get_newest_scene_timestamp(polygon_latlng, since_date)  -- Sentinel-2
                                               scene-freshness poll, see
                                               scene_poll.py
"""

from .auth import GEEAuthError, initialize_ee
from .imagery import get_ndci_heatmap, get_true_color_image
from .modis import get_modis_chlorophyll_history, get_modis_sst
from .rainfall import get_rainfall_proxy
from .scene_poll import get_newest_scene_timestamp
from .sentinel2 import (
    NoCloudFreeImageryError,
    NoWaterPixelsError,
    get_sentinel2_bands,
)
from .study_area import STUDY_AREA_POLYGON_LATLNG, check_point_in_study_area

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
    "check_point_in_study_area",
    "STUDY_AREA_POLYGON_LATLNG",
    "get_newest_scene_timestamp",
]
