"""
Cross-project bridge into `data-pipeline/src` — the only module in
`detection/` allowed to talk to Google Earth Engine, and it does so only
indirectly, by calling the real `satellite-data` functions.

Why this exists: `detection/` and `data-pipeline/` are deliberately
separate projects with separate venvs/requirements.txt (CLAUDE.md §5), so
a plain `import` across the two directories is not available out of the
box, and this project's own package happens to also be named `src`
(`detection/src/`, alongside `data-pipeline/src/`) — a bare
`sys.path.insert` of `data-pipeline/` plus `import src` would collide with
`detection/src` itself if both are ever imported in the same interpreter
(e.g. `detection/src/climatology.py` doing `import src` would get
whichever `src` package Python resolved first, silently).

Fix: load `data-pipeline/src/__init__.py` via `importlib.util` under an
unambiguous module name (`data_pipeline_src`, registered in
`sys.modules`) instead of relying on `sys.path` + a bare `import src`.
`submodule_search_locations` is set explicitly so the package's own
relative imports (`from .auth import ...`, `from .modis import ...`)
resolve correctly under the new name. This is the "pip install -e" idea
from `.claude/agents/bloom-detection.md`, done without needing a
`pyproject.toml`/`setup.py` added to `data-pipeline/` (which does not
have one and is out of scope to add here).

No data-pipeline logic is duplicated or reimplemented here — every name
below is the exact object from `data-pipeline/src`, just re-exported
under a name `detection/` code can import without a path collision.

Environment: GEE needs `EE_PROJECT_ID` set (see `data-pipeline/src/auth.py`).
`detection/.env` carries the same value as `data-pipeline/.env` (see
`detection/.env.example`); if `detection/.env` is missing, this module
falls back to reading `data-pipeline/.env` directly so a second copy of
the secret is not strictly required. Both files are gitignored (`*.env`
in the repo-root `.gitignore`) — never commit either.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

_DETECTION_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = _DETECTION_DIR.parent
_DATA_PIPELINE_SRC = _REPO_ROOT / "data-pipeline" / "src"

_MODULE_NAME = "data_pipeline_src"


def _load_env_file(path: Path) -> None:
    """Minimal `.env` parser (KEY=VALUE per line, '#' comments) — no extra
    dependency (python-dotenv is not in either requirements.txt). Uses
    `setdefault` so an already-exported shell env var always wins."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if key and value:
            os.environ.setdefault(key, value)


def _load_data_pipeline_package():
    if _MODULE_NAME in sys.modules:
        return sys.modules[_MODULE_NAME]

    init_path = _DATA_PIPELINE_SRC / "__init__.py"
    if not init_path.exists():
        raise ImportError(
            f"data-pipeline/src not found at {_DATA_PIPELINE_SRC} — "
            "expected a sibling `data-pipeline/` directory next to `detection/`."
        )

    spec = importlib.util.spec_from_file_location(
        _MODULE_NAME,
        init_path,
        submodule_search_locations=[str(_DATA_PIPELINE_SRC)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


# Load env vars before the data-pipeline package's `auth.py` is exercised
# (its functions read os.environ lazily on call, but doing this at import
# time here keeps the ordering obvious and matches how data-pipeline's own
# code expects EE_PROJECT_ID to already be set).
_load_env_file(_DETECTION_DIR / ".env")
_load_env_file(_REPO_ROOT / "data-pipeline" / ".env")

_dp = _load_data_pipeline_package()

# Re-exported, unmodified, from data-pipeline/src.
GEEAuthError = _dp.GEEAuthError
GEEConfigError = _dp.GEEConfigError
get_sentinel2_bands = _dp.get_sentinel2_bands
# The system-wide scene-age ceiling and its env override live in
# data-pipeline (sentinel2.py); re-exported so backend/ can report the
# effective value without a second copy of the default.
DEFAULT_MAX_SCENE_AGE_DAYS = _dp.DEFAULT_MAX_SCENE_AGE_DAYS
default_max_scene_age_days = _dp.default_max_scene_age_days
get_modis_chlorophyll_history = _dp.get_modis_chlorophyll_history
get_modis_sst = _dp.get_modis_sst
get_rainfall_proxy = _dp.get_rainfall_proxy

# Image rendering (data-pipeline/src/imagery.py) -- added for backend-api's
# satellite-image endpoints (GET /satellite-image, /risk-map/{id}/image).
# detection/src's prediction.py never calls these (no
# detection/prediction logic uses rendered images, only numeric bands) --
# re-exported here purely as a pass-through so backend/src/_detection.py
# can reach them through this same bridge module rather than opening a
# fourth, parallel path into data-pipeline/src.
get_true_color_image = _dp.get_true_color_image
get_ndci_heatmap = _dp.get_ndci_heatmap

# The NDCI display ramp itself, plus its pure colour math (imagery.py's
# NDCI_RAMP_HEX / NDCI_RAMP_DOMAIN / hex_to_rgb / ndci_value_to_color).
# Re-exported for backend/src/raster_scan/render.py, which draws the
# whole-polygon overlay from *stored cells* instead of from a GEE
# thumbnail. It has to paint the same quantity in the same colours over
# the same value domain as the per-site NDCI heatmap, or the dashboard
# would show one index in two disagreeing palettes -- so there is one
# ramp, read by both, and never a second copy of the stops or the domain.
NDCI_RAMP_HEX = _dp.imagery.NDCI_RAMP_HEX
NDCI_RAMP_DOMAIN = _dp.imagery.NDCI_RAMP_DOMAIN
TRUE_COLOR_MIN = _dp.imagery.TRUE_COLOR_MIN
TRUE_COLOR_MAX = _dp.imagery.TRUE_COLOR_MAX
hex_to_rgb = _dp.imagery.hex_to_rgb
ndci_value_to_color = _dp.imagery.ndci_value_to_color

# Study-area boundary check (data-pipeline/src/study_area.py) -- pure, no
# GEE call. Re-exported for the same pass-through reason as the image
# functions above: backend/src/_detection.py reaches it through this one
# bridge rather than a separate path into data-pipeline/src.
check_point_in_study_area = _dp.check_point_in_study_area

# Sentinel-2 scene-freshness poll (data-pipeline/src/scene_poll.py) --
# added for backend-api's regional-scan event-driven trigger. Re-exported
# purely as a pass-through, same reasoning as check_point_in_study_area
# above.
get_newest_scene_timestamp = _dp.get_newest_scene_timestamp

# Whole-polygon raster composite (data-pipeline/src/raster.py) -- added for
# backend-api's raster scan. Re-exported purely as a pass-through, same
# reasoning as check_point_in_study_area above: detection/src's own
# prediction path is per-point and never builds a raster, but backend/src/
# _detection.py must reach these through this one bridge rather than
# opening yet another path into data-pipeline/src.
#
# RASTER_BAND_REDUCERS travels with the functions on purpose. It is the
# rule that the per-cell acquisition date is selected (mode) and never
# averaged; a downstream project re-deriving its own aggregation policy
# is exactly how a fabricated date would get in, so there is one constant
# and every layer reads it.
build_index_composite = _dp.build_index_composite
download_composite_arrays = _dp.download_composite_arrays
iter_bootstrap_windows = _dp.iter_bootstrap_windows
summarize_raster_cells = _dp.summarize_raster_cells
valid_cell_mask = _dp.valid_cell_mask
RASTER_BAND_REDUCERS = _dp.RASTER_BAND_REDUCERS
RASTER_BAND_ORDER = _dp.RASTER_BAND_ORDER
RASTER_INDEX_BANDS = _dp.RASTER_INDEX_BANDS
RASTER_TRUE_COLOR_BANDS = _dp.RASTER_TRUE_COLOR_BANDS
RASTER_STORED_BANDS = _dp.RASTER_STORED_BANDS
RASTER_DATE_BAND = _dp.RASTER_DATE_BAND
SENTINEL2_SR_ARCHIVE_START_DATE = _dp.SENTINEL2_SR_ARCHIVE_START_DATE
DEFAULT_RASTER_SCALE_M = _dp.DEFAULT_RASTER_SCALE_M
FabricatedDateError = _dp.FabricatedDateError
DateBandPrecisionError = _dp.DateBandPrecisionError

# Per-site NDCI history for the TEST baseline (data-pipeline/src/history.py).
# Re-exported as a pass-through, same reasoning as the raster names above:
# detection/src's own prediction path never fetches history, but
# backend/src/_detection.py reaches data-pipeline only through this one
# bridge. `preprocessing_params` is pure (no GEE call) and is the single
# description of how history rows are made, which the baseline hashes into
# its preprocessing signature.
get_ndci_history = _dp.get_ndci_history
preprocessing_params = _dp.preprocessing_params

# Per-cell season statistics for the Level B TEST baseline
# (data-pipeline/src/baseline_raster.py). Same pass-through reasoning: only
# scripts/build_test_baseline.py (via backend/src/_detection.py) builds
# them, and `cell_baseline_params` is the pure description of how cells are
# made, which the cell baseline hashes into its own preprocessing signature
# (deliberately different from the site signature above).
build_cell_baseline = _dp.build_cell_baseline
cell_baseline_params = _dp.cell_baseline_params

# Per-date scene assessment for the latest-scene policy
# (data-pipeline/src/scene_assess.py). Re-exported as a pass-through, same
# reasoning as the raster names above: backend's raster-scan trigger decides
# whether a new acquisition passed the cloud criterion with these, and the
# thresholds come from the one `scene_thresholds()` rather than a backend
# copy. `decide` and `scene_thresholds` are pure (no GEE call).
assess_new_scenes = _dp.assess_new_scenes
SceneAssessment = _dp.SceneAssessment
scene_thresholds = _dp.scene_thresholds
decide = _dp.decide

# `day_of_year_climatology` is a pure function in data-pipeline/src/modis.py
# whose own docstring says bloom-detection is "expected to build on this
# rather than reimplement it" — re-exported here for src/climatology.py so
# the per-location/per-day-of-year mean+std logic is not duplicated.
day_of_year_climatology = _dp.modis.day_of_year_climatology

# MODIS product identity (data-pipeline/src/modis.py): collection id, the two
# bands read, the Level-3 grid it is sampled at (~4.6 km, the figure that
# module says to state) and the archive start. Plain constants, no GEE call;
# re-exported so backend's GET /methods describes MODIS from the module that
# queries it rather than from a second copy.
MODIS_COLLECTION_ID = _dp.modis.COLLECTION_ID
MODIS_CHLOR_A_BAND = _dp.modis.CHLOR_A_BAND
MODIS_SST_BAND = _dp.modis.SST_BAND
MODIS_GRID_SCALE_M = _dp.modis.DEFAULT_SCALE_M
MODIS_ARCHIVE_START = _dp.modis.ARCHIVE_START

# Typed "data genuinely unavailable" errors from sentinel2.py, distinct
# from GEEAuthError. detect()/risk_level() in src/prediction.py catch
# these (not GEEAuthError, which must always propagate per CLAUDE.md's
# "never catch-and-fabricate" rule) to return an honest no-data result
# instead of crashing on a cloudy day or an all-land buffer.
NoCloudFreeImageryError = _dp.sentinel2.NoCloudFreeImageryError
NoWaterPixelsError = _dp.sentinel2.NoWaterPixelsError

__all__ = [
    "GEEAuthError",
    "GEEConfigError",
    "get_sentinel2_bands",
    "DEFAULT_MAX_SCENE_AGE_DAYS",
    "default_max_scene_age_days",
    "get_modis_chlorophyll_history",
    "get_modis_sst",
    "get_rainfall_proxy",
    "day_of_year_climatology",
    "MODIS_COLLECTION_ID",
    "MODIS_CHLOR_A_BAND",
    "MODIS_SST_BAND",
    "MODIS_GRID_SCALE_M",
    "MODIS_ARCHIVE_START",
    "NoCloudFreeImageryError",
    "NoWaterPixelsError",
    "get_true_color_image",
    "get_ndci_heatmap",
    "NDCI_RAMP_HEX",
    "NDCI_RAMP_DOMAIN",
    "TRUE_COLOR_MIN",
    "TRUE_COLOR_MAX",
    "hex_to_rgb",
    "ndci_value_to_color",
    "check_point_in_study_area",
    "get_newest_scene_timestamp",
    "build_index_composite",
    "download_composite_arrays",
    "iter_bootstrap_windows",
    "summarize_raster_cells",
    "valid_cell_mask",
    "get_ndci_history",
    "preprocessing_params",
    "build_cell_baseline",
    "cell_baseline_params",
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
