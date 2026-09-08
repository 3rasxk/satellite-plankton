"""
Cross-project bridge into `data-pipeline/src`, used by the raster trigger
to poll the confirmed study-area polygon for new acquisitions.

`backend/src/_detection.py` already reaches `check_point_in_study_area`
indirectly (through `detection/src/_data_pipeline.py`'s own bridge), but
only via that module's private, undocumented `_dp` attribute -- not part
of its public `__all__`. Rather than reach through another project's
private internals, this file is a third, direct instance of the exact
`importlib.util.spec_from_file_location` namespaced-import pattern
`detection/src/_data_pipeline.py` established for the identical
two-projects-both-named-`src` collision problem (see that module's own
docstring) -- "the same one this codebase already uses twice"
(the namespaced bridge convention documented in CLAUDE.md §8).

No data-pipeline logic is duplicated here -- both names below are the
exact objects from `data-pipeline/src/__init__.py`. `check_point_in_study_area`
is pure and GEE-free (data-pipeline/src/study_area.py's own docstring),
so loading this whole package a second time under a different module
name never triggers a live GEE call -- module import alone never touches
`ee`, only calling a Sentinel-2/MODIS function does.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = _BACKEND_DIR.parent
_DATA_PIPELINE_SRC = _REPO_ROOT / "data-pipeline" / "src"

_MODULE_NAME = "backend_data_pipeline_src"


def _load_data_pipeline_package():
    if _MODULE_NAME in sys.modules:
        return sys.modules[_MODULE_NAME]

    init_path = _DATA_PIPELINE_SRC / "__init__.py"
    if not init_path.exists():
        raise ImportError(
            f"data-pipeline/src not found at {_DATA_PIPELINE_SRC} -- expected a "
            "sibling `data-pipeline/` directory next to `backend/`."
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


_dp = _load_data_pipeline_package()

STUDY_AREA_POLYGON_LATLNG = _dp.STUDY_AREA_POLYGON_LATLNG
check_point_in_study_area = _dp.check_point_in_study_area

__all__ = ["STUDY_AREA_POLYGON_LATLNG", "check_point_in_study_area"]
