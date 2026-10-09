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
    build_index_composite(polygon_latlng, date)   -- whole-polygon index
    download_composite_arrays(composite, scale_m) raster, see raster.py
    summarize_raster_cells(arrays)                (pure, no GEE call)
    valid_cell_mask(date_ms)                      (pure, no GEE call)
    get_ndci_history(lat, lng, start, end)  -- per-site NDCI history rows for
                                               the TEST baseline, see
                                               history.py
    preprocessing_params()                        (pure, no GEE call)
    assess_new_scenes(polygon_latlng, since_date) -- per-date cloud/water
                                               decision for the latest-scene
                                               policy, see scene_assess.py
    SceneAssessment, decide(...), scene_thresholds()  (pure, no GEE call)
"""

from .auth import GEEAuthError, GEEConfigError, initialize_ee
from .history import get_ndci_history, preprocessing_params
from .imagery import get_ndci_heatmap, get_true_color_image
from .modis import get_modis_chlorophyll_history, get_modis_sst
from .rainfall import get_rainfall_proxy
from .raster import (
    DEFAULT_RASTER_SCALE_M,
    RASTER_BAND_ORDER,
    RASTER_BAND_REDUCERS,
    RASTER_DATE_BAND,
    RASTER_INDEX_BANDS,
    RASTER_STORED_BANDS,
    RASTER_TRUE_COLOR_BANDS,
    SENTINEL2_SR_ARCHIVE_START_DATE,
    DateBandPrecisionError,
    FabricatedDateError,
    build_index_composite,
    download_composite_arrays,
    iter_bootstrap_windows,
    summarize_raster_cells,
    valid_cell_mask,
)
from .scene_assess import (
    SceneAssessment,
    assess_new_scenes,
    decide,
    scene_thresholds,
)
from .scene_poll import get_newest_scene_timestamp
from .sentinel2 import (
    DEFAULT_MAX_SCENE_AGE_DAYS,
    NoCloudFreeImageryError,
    NoWaterPixelsError,
    default_max_scene_age_days,
    get_sentinel2_bands,
)
from .study_area import STUDY_AREA_POLYGON_LATLNG, check_point_in_study_area

__all__ = [
    "GEEAuthError",
    "GEEConfigError",
    "initialize_ee",
    "get_sentinel2_bands",
    "get_modis_chlorophyll_history",
    "get_modis_sst",
    "get_rainfall_proxy",
    "get_true_color_image",
    "get_ndci_heatmap",
    "NoCloudFreeImageryError",
    "NoWaterPixelsError",
    "DEFAULT_MAX_SCENE_AGE_DAYS",
    "default_max_scene_age_days",
    "check_point_in_study_area",
    "STUDY_AREA_POLYGON_LATLNG",
    "get_newest_scene_timestamp",
    "build_index_composite",
    "download_composite_arrays",
    "iter_bootstrap_windows",
    "summarize_raster_cells",
    "valid_cell_mask",
    "get_ndci_history",
    "preprocessing_params",
    "assess_new_scenes",
    "SceneAssessment",
    "scene_thresholds",
    "decide",
    "RASTER_BAND_REDUCERS",
    "RASTER_BAND_ORDER",
    "RASTER_INDEX_BANDS",
    "RASTER_TRUE_COLOR_BANDS",
    "RASTER_STORED_BANDS",
    "RASTER_DATE_BAND",
    "SENTINEL2_SR_ARCHIVE_START_DATE",
    "DEFAULT_RASTER_SCALE_M",
    "FabricatedDateError",
    "DateBandPrecisionError",
]
