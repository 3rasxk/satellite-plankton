"""
Cross-project bridge into `detection/src` -- the only module in `backend/`
allowed to talk to the detection/prediction engine, and the only one that
(transitively, through `detection/src/_data_pipeline.py`) reaches
Google Earth Engine at all.

Why this exists: `backend/`, `detection/`, and `data-pipeline/` are three
separate projects with separate venvs/requirements.txt (CLAUDE.md §5).
`detection/src/_data_pipeline.py` already solved the two-projects-both-
named-`src` collision for `detection/` importing `data-pipeline/src`, via
`importlib.util.spec_from_file_location` under an unambiguous module name
registered in `sys.modules`, with `submodule_search_locations` set so the
loaded package's own relative imports still resolve.

`detection/src` (unlike `data-pipeline/src`) has no `__init__.py` -- it is
not a package, just a directory of loose modules (`prediction.py`,
`climatology.py`, `indices.py`, `_data_pipeline.py`).
Each of those modules already inserts its own directory onto `sys.path`
at import time (see the `_THIS_DIR = Path(__file__).resolve().parent;
sys.path.insert(...)` header every one of them carries) specifically so
their sibling absolute imports (`from _data_pipeline import ...`, `from
climatology import ...`) resolve regardless of who imports them or from
where. That means loading `detection/src/prediction.py` directly via
`spec_from_file_location` is sufficient -- exec'ing it triggers its own
sys.path bootstrap before its internal imports run, so nothing extra is
needed here beyond pointing importlib at the file.

We load `prediction.py` under the explicit namespaced module name
`detection_src_prediction` rather than letting it register under its
bare name (`prediction`) in `sys.modules` -- bare generic
names are exactly the kind of thing a `backend/` dependency could someday
collide with, and CLAUDE.md's "detection/ and backend/ are separate
projects" boundary is easiest to keep obvious if `backend/` never lets
another project's modules masquerade under undecorated names.

No detection/prediction logic is duplicated or reimplemented here --
every name below is the exact object from `detection/src`, just
re-exported under names `backend/` code can import without ambiguity.

Environment: GEE needs `EE_PROJECT_ID` set. This bridge does not load any
.env itself -- `detection/src/_data_pipeline.py` (loaded transitively,
here, as part of `prediction.py`'s own import chain)
already does that (reading `detection/.env`, falling back to
`data-pipeline/.env`), so by the time this module returns, GEE auth env
vars are already in `os.environ`. `backend/.env` is a separate concern
(DB connection string only -- see `src/config.py`), not read here.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = _BACKEND_DIR.parent
_DETECTION_SRC = _REPO_ROOT / "detection" / "src"


def _load_detection_module(filename: str, module_name: str):
    """Load one `detection/src/*.py` file under an explicit module name.

    Idempotent (returns the cached module on a second call) so repeated
    imports across `backend/` routers don't re-run GEE session setup or
    re-parse config.yaml more than once per process.
    """
    if module_name in sys.modules:
        return sys.modules[module_name]

    file_path = _DETECTION_SRC / filename
    if not file_path.exists():
        raise ImportError(
            f"detection/src/{filename} not found at {file_path} -- expected a "
            "sibling `detection/` directory next to `backend/`."
        )

    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_prediction = _load_detection_module("prediction.py", "detection_src_prediction")
_climatology_bridge = _load_detection_module("climatology.py", "detection_src_climatology")

# `prediction.py` imports `_data_pipeline` under its bare sibling name.
# Reuse that loaded object. Climatology is loaded explicitly above because
# prediction no longer imports it after anomaly scoring was removed.
_data_pipeline_bridge = sys.modules["_data_pipeline"]

# --- Detection / prediction (Phase 2 public API) --------------------------
# Re-exported, unmodified, from detection/src/prediction.py. backend/
# routers call these; they never reimplement indices/climatology/rules.
detect = _prediction.detect
risk_level = _prediction.risk_level
load_prediction_config = _prediction.load_config

# --- Errors / lower-level pipeline calls -----------------------------------
# GEEAuthError must always propagate out of backend routers too (never
# caught-and-faked, per CLAUDE.md) -- routers catch it only to translate
# it into a clear 503, not to hide it. NoCloudFreeImageryError/
# NoWaterPixelsError are the "real-world data gap" errors that
# detect()/risk_level() already convert into status fields internally;
# backend re-raises/re-catches these itself only in the one place it
# makes its own extra get_sentinel2_bands call (see routers/detect.py and
# src/scheduler.py) to surface cloud_fraction/actual_date, which
# detect()'s/risk_level()'s return shapes do not expose.
GEEAuthError = _data_pipeline_bridge.GEEAuthError
NoCloudFreeImageryError = _data_pipeline_bridge.NoCloudFreeImageryError
NoWaterPixelsError = _data_pipeline_bridge.NoWaterPixelsError
get_sentinel2_bands = _data_pipeline_bridge.get_sentinel2_bands
get_modis_chlorophyll_history = _data_pipeline_bridge.get_modis_chlorophyll_history
day_of_year_climatology = _data_pipeline_bridge.day_of_year_climatology

# Image rendering (data-pipeline/src/imagery.py, re-exported through
# detection/src/_data_pipeline.py) -- true-color and NDCI-heatmap PNG
# thumbnails of the exact same resolved Sentinel-2 scene
# get_sentinel2_bands returns numeric bands for (same-scene guarantee, see
# data-pipeline/src/imagery.py's module docstring). Used by
# routers/satellite_image.py (on-demand, per lat/lng/date) and
# scheduler.py (pre-rendered/cached for the 7-site monitored grid).
get_true_color_image = _data_pipeline_bridge.get_true_color_image
get_ndci_heatmap = _data_pipeline_bridge.get_ndci_heatmap

# Study-area boundary check -- pure, no GEE call. Used by routers/detect.py
# to flag (never silently accept) a query outside the upper Gulf polygon.
check_point_in_study_area = _data_pipeline_bridge.check_point_in_study_area

# Sentinel-2 scene-freshness poll -- used by
# backend/src/regional_scan/trigger.py's poll_and_maybe_scan().
get_newest_scene_timestamp = _data_pipeline_bridge.get_newest_scene_timestamp

# Pure function for computing an anomaly z-score -- reused (not
# reimplemented) for /timeseries, same call climatology.py itself makes
# for the single-date case in detect().
z_score = _climatology_bridge.z_score

__all__ = [
    "detect",
    "risk_level",
    "load_prediction_config",
    "GEEAuthError",
    "NoCloudFreeImageryError",
    "NoWaterPixelsError",
    "get_sentinel2_bands",
    "get_modis_chlorophyll_history",
    "day_of_year_climatology",
    "z_score",
    "get_true_color_image",
    "get_ndci_heatmap",
    "check_point_in_study_area",
    "get_newest_scene_timestamp",
]
