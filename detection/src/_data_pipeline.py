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
get_sentinel2_bands = _dp.get_sentinel2_bands
get_modis_chlorophyll_history = _dp.get_modis_chlorophyll_history
get_modis_sst = _dp.get_modis_sst
get_rainfall_proxy = _dp.get_rainfall_proxy

# Image rendering (data-pipeline/src/imagery.py) -- added for backend-api's
# satellite-image endpoints (GET /satellite-image, /risk-map/{id}/image).
# detection/src's own prediction.py/thresholds.py never call these (no
# detection/prediction logic uses rendered images, only numeric bands) --
# re-exported here purely as a pass-through so backend/src/_detection.py
# can reach them through this same bridge module rather than opening a
# fourth, parallel path into data-pipeline/src.
get_true_color_image = _dp.get_true_color_image
get_ndci_heatmap = _dp.get_ndci_heatmap
build_ndci_watch_overlay = _dp.build_ndci_watch_overlay
NoWatchOverlayImageryError = _dp.NoWatchOverlayImageryError

# Study-area boundary check (data-pipeline/src/study_area.py) -- pure, no
# GEE call. Re-exported for the same pass-through reason as the image
# functions above: backend/src/_detection.py reaches it through this one
# bridge rather than a separate path into data-pipeline/src.
check_point_in_study_area = _dp.check_point_in_study_area

# `day_of_year_climatology` is a pure function in data-pipeline/src/modis.py
# whose own docstring says bloom-detection is "expected to build on this
# rather than reimplement it" — re-exported here for src/climatology.py so
# the per-location/per-day-of-year mean+std logic is not duplicated.
day_of_year_climatology = _dp.modis.day_of_year_climatology

# Typed "data genuinely unavailable" errors from sentinel2.py, distinct
# from GEEAuthError. detect()/risk_level() in src/prediction.py catch
# these (not GEEAuthError, which must always propagate per CLAUDE.md's
# "never catch-and-fabricate" rule) to return an honest no-data result
# instead of crashing on a cloudy day or an all-land buffer.
NoCloudFreeImageryError = _dp.sentinel2.NoCloudFreeImageryError
NoWaterPixelsError = _dp.sentinel2.NoWaterPixelsError

__all__ = [
    "GEEAuthError",
    "get_sentinel2_bands",
    "get_modis_chlorophyll_history",
    "get_modis_sst",
    "get_rainfall_proxy",
    "day_of_year_climatology",
    "NoCloudFreeImageryError",
    "NoWaterPixelsError",
    "get_true_color_image",
    "get_ndci_heatmap",
    "build_ndci_watch_overlay",
    "NoWatchOverlayImageryError",
    "check_point_in_study_area",
]
