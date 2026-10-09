"""On-disk store for the TEST seasonal baseline artefact, and its gated loader.

Data source: none of its own. The caller passes a manifest and per-location
NDCI history rows already produced by ``scripts/build_test_baseline.py``
(Sentinel-2 via ``data-pipeline/src/history.py``); this module only writes
them to, and reads them back from, ``backend/data/baselines/`` (gitignored
local data, like ``app.db``).

Layout, one directory per baseline version::

    <root>/<baseline_version>/manifest.json   description and activation declaration
    <root>/<baseline_version>/sites.json      {"rows": {site_id: [history rows]}}
    <root>/<baseline_version>/cells_mMM.npz   Level B only: one per target month
                                              MM = 01..12 (lat, lng float64;
                                              median, mad float32; n uint16)

``write_artifact`` / ``read_artifact`` / ``latest_artifact_path`` do not
validate the manifest or judge whether the baseline is fit to use; they hand
back whatever was written, including a manifest that would be refused.
``write_artifact`` does refuse to overwrite an existing version unless asked
(``ArtifactExists``), so one version name never silently changes content.

``load_active_baseline`` (and ``active_manifest``) is the one gated reader:
it returns nothing unless ``config.BASELINE_MODE`` is exactly ``"test"``, and
then only the newest artefact that passes ``detection/src/baseline.py``'s
``validate_manifest`` against the live preprocessing signature and today's
UTC date, plus a structural check that the rows match the manifest and
that the declared minimum is the weakest location's ``min_season_dates``. It
decides nothing itself beyond those checks; the rules are detection's.
Parsed files are cached on each file's (mtime_ns, size, inode), but
validation is re-run on every call, because "today" and the live signature
are not properties of the files.

``load_cell_baseline`` / ``cell_baseline_or_reason`` read one season of the
Level B (per-cell) baseline from the same artefact. They NEVER raise: a
missing, stale or malformed cell baseline is None plus a logged reason. They
require the Level A part to validate too (one artefact, one version), plus
``validate_level_b`` against the live CELL preprocessing signature (raster
scale ``config.RASTER_SCAN_SCALE_M`` and the study polygon), all twelve
season files present, and the requested file agreeing with the manifest. A
broken Level B block never affects the Level A gate.

Limitations: the rows are dimensionless NDCI readings from a point-buffer
mean over clear-sky water pixels, kept only on cloud-free days. They are a
statistical record of one place, not bloom evidence, and carry no validation
against recorded bloom events. A Level B cell is one sampled native pixel
per day at the raster scale; its median/MAD describe that pixel's own
clear-sky record only.
"""

from __future__ import annotations

import copy
import json
import logging
import math
import os
import re
import shutil
import tempfile
import threading
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from functools import cached_property
from pathlib import Path
from types import MappingProxyType
from typing import Any

import numpy as np

from . import _detection as bridge
from . import _study_area, config

logger = logging.getLogger(__name__)

BASELINE_ROOT = Path(__file__).resolve().parents[1] / "data" / "baselines"

MANIFEST_NAME = "manifest.json"
SITES_NAME = "sites.json"

# Level B season files: exactly cells_m01.npz .. cells_m12.npz, nothing else
# (the name becomes a path, so it is matched, never trusted).
CELLS_FILE_PATTERN = re.compile(r"^cells_m(0[1-9]|1[0-2])\.npz$")
# The arrays of a cells file and the dtype each is stored as. float64
# coordinates keep Earth Engine's pixelLonLat exactly; float32 is ample for
# NDCI statistics; uint16 counts dates.
CELL_ARRAY_DTYPES: dict[str, np.dtype] = {
    "lat": np.dtype(np.float64),
    "lng": np.dtype(np.float64),
    "median": np.dtype(np.float32),
    "mad": np.dtype(np.float32),
    "n": np.dtype(np.uint16),
}


def _check_version(version: object) -> str:
    """A baseline version becomes a directory name, so it must be a plain one."""
    if (
        not isinstance(version, str)
        or not version
        or version.startswith(".")
        or any(sep in version for sep in ("/", "\\", "\0"))
    ):
        raise ValueError(f"unsafe or missing baseline_version for a directory name: {version!r}")
    return version


def _dump(payload: object, path: Path, *, indent: int | None) -> None:
    # allow_nan=False: a NaN/inf would otherwise be written as the non-JSON
    # tokens NaN/Infinity and silently poison every later reader.
    separators = None if indent else (",", ":")
    text = json.dumps(payload, indent=indent, separators=separators, allow_nan=False)
    path.write_text(text + "\n", encoding="utf-8")


class ArtifactExists(FileExistsError):
    """``<root>/<baseline_version>`` already exists and replacing it was not asked for.

    A baseline version is what a cached site anomaly is paired with
    (``DetectionCache.baseline_version``); silently rewriting a version's
    content would make old pairings describe history they were never
    computed from. ``path`` is the existing directory.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        super().__init__(
            f"baseline version {self.path.name} already exists at {self.path}; "
            "a version must identify one content -- replace it explicitly"
        )


def _prepare_cells(name: str, arrays: dict) -> dict[str, np.ndarray]:
    """Validate one season's arrays and cast them to ``CELL_ARRAY_DTYPES``.

    Raises ``ValueError`` (never writes) for an unsafe file name, missing or
    extra arrays, non-1-D or unequal lengths, non-finite statistics or
    coordinates, or counts that are not whole numbers in uint16 range.
    """
    if not isinstance(name, str) or not CELLS_FILE_PATTERN.match(name):
        raise ValueError(f"unsafe or unexpected cells file name: {name!r}")
    if set(arrays) != set(CELL_ARRAY_DTYPES):
        raise ValueError(
            f"{name}: arrays must be exactly {sorted(CELL_ARRAY_DTYPES)}, got {sorted(arrays)}"
        )
    raw = {key: np.asarray(arrays[key]) for key in CELL_ARRAY_DTYPES}
    lengths = {key: value.shape for key, value in raw.items()}
    if any(value.ndim != 1 for value in raw.values()) or len(set(lengths.values())) != 1:
        raise ValueError(f"{name}: arrays must be 1-D and of equal length, got {lengths}")
    for key in ("lat", "lng", "median", "mad"):
        if raw[key].size and not np.all(np.isfinite(raw[key].astype(np.float64))):
            raise ValueError(f"{name}: {key} holds non-finite values")
    counts = raw["n"].astype(np.float64)
    if counts.size and (
        not np.all(counts == np.round(counts)) or counts.min() < 0 or counts.max() > np.iinfo(np.uint16).max
    ):
        raise ValueError(f"{name}: n must be whole numbers of dates in uint16 range")
    return {key: raw[key].astype(dtype) for key, dtype in CELL_ARRAY_DTYPES.items()}


def read_cells_file(path: Path) -> dict[str, np.ndarray]:
    """Read one Level B season file, refusing anything but the stored layout.

    Exactly the arrays of ``CELL_ARRAY_DTYPES``, each with exactly that
    dtype (a narrowed coordinate is refused, not widened back), 1-D and of
    equal length. Pickled content is never loaded. Raises ``ValueError``.
    """
    with np.load(Path(path), allow_pickle=False) as data:
        names = set(data.files)
        if names != set(CELL_ARRAY_DTYPES):
            raise ValueError(f"{path}: arrays {sorted(names)} != {sorted(CELL_ARRAY_DTYPES)}")
        arrays = {name: data[name] for name in CELL_ARRAY_DTYPES}
    for name, dtype in CELL_ARRAY_DTYPES.items():
        if arrays[name].dtype != dtype:
            raise ValueError(f"{path}: {name} is {arrays[name].dtype}, expected {dtype}")
        if arrays[name].ndim != 1:
            raise ValueError(f"{path}: {name} is not 1-D")
    if len({value.size for value in arrays.values()}) != 1:
        raise ValueError(f"{path}: arrays differ in length")
    return arrays


def write_artifact(
    root: Path,
    manifest: dict,
    rows_by_location: dict[str, list[dict]],
    *,
    replace: bool = False,
    cells_by_file: dict[str, dict] | None = None,
) -> Path:
    """Write ``manifest``, ``rows_by_location`` and any Level B cells; return the version directory.

    The directory is ``<root>/<manifest["baseline_version"]>``. Every file is
    written into a hidden scratch directory first and moved into place only
    when all succeeded, so a failed or interrupted write never leaves a
    directory that ``latest_artifact_path`` would take for a complete one.

    ``cells_by_file`` maps ``cells_mMM.npz`` names to ``{"lat", "lng",
    "median", "mad", "n"}`` arrays (Level B); they are validated and cast to
    ``CELL_ARRAY_DTYPES`` before anything is created, and written with
    ``np.savez_compressed``.

    An existing directory for the same version is refused with
    ``ArtifactExists`` (nothing written) unless ``replace=True``, which
    replaces it.

    Raises ``ValueError`` for an unusable version name, a value JSON cannot
    carry (NaN, inf) or malformed cells. Nothing is left behind in that case.
    """
    version = _check_version(manifest.get("baseline_version"))
    prepared = {name: _prepare_cells(name, arrays) for name, arrays in (cells_by_file or {}).items()}
    root = Path(root)
    final = root / version
    if final.exists() and not replace:
        raise ArtifactExists(final)

    root.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix=f".tmp-{version}-", dir=root))
    try:
        _dump(manifest, scratch / MANIFEST_NAME, indent=2)
        _dump({"rows": rows_by_location}, scratch / SITES_NAME, indent=None)
        for name, arrays in prepared.items():
            np.savez_compressed(scratch / name, **arrays)
        if final.exists():
            if not replace:  # appeared while the files were being written
                raise ArtifactExists(final)
            retired = Path(tempfile.mkdtemp(prefix=f".old-{version}-", dir=root))
            os.replace(final, retired / "previous")
            shutil.rmtree(retired, ignore_errors=True)
        os.replace(scratch, final)
    except BaseException:
        shutil.rmtree(scratch, ignore_errors=True)
        raise
    return final


def read_artifact(path: Path) -> tuple[dict, dict[str, list[dict]]]:
    """Read a version directory back as ``(manifest, rows_by_location)``."""
    path = Path(path)
    manifest = json.loads((path / MANIFEST_NAME).read_text(encoding="utf-8"))
    sites = json.loads((path / SITES_NAME).read_text(encoding="utf-8"))
    return manifest, sites["rows"]


def latest_artifact_path(root: Path | None = None) -> Path | None:
    """The highest-versioned directory under ``root`` holding both files.

    Versions are ``TEST-<YYYYMMDD>-<signature8>``, so name order is build-date
    order. Directories missing either file, hidden scratch directories and
    stray files are ignored. Returns None when nothing qualifies (including a
    root that does not exist). ``root`` defaults to ``BASELINE_ROOT``, read at
    call time.
    """
    root = BASELINE_ROOT if root is None else Path(root)
    if not root.is_dir():
        return None
    complete = [
        child
        for child in root.iterdir()
        if child.is_dir()
        and not child.name.startswith(".")
        and (child / MANIFEST_NAME).is_file()
        and (child / SITES_NAME).is_file()
    ]
    return max(complete, key=lambda child: child.name, default=None)


# --------------------------------------------------------------------------
# Gated loader: the only reader that may feed the signal-anomaly gate
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ActiveBaseline:
    """A TEST baseline that validated at load time. The dicts are the caller's
    own copies; mutating them never reaches the cache or the gate."""

    manifest: dict
    rows_by_location: dict[str, list[dict]]
    version: str


# ((path, manifest stat, sites stat), (manifest, rows_by_location)) -- the
# parsed JSON only. Never handed out without a copy.
_artifact_cache: tuple[tuple, tuple[dict, dict]] | None = None


def _utc_today() -> date:
    return datetime.now(timezone.utc).date()


def _file_state(path: Path) -> tuple[int, int, int]:
    # Same discipline as scientific_status._load_config: mtime alone can
    # miss a same-granularity rewrite, so size and inode are in the key.
    st = os.stat(path)
    return (st.st_mtime_ns, st.st_size, st.st_ino)


def _read_cached(path: Path) -> tuple[dict, dict]:
    """Parsed ``(manifest, rows_by_location)``, re-read when either file changes.

    The global is read once into a local, so a concurrent refill between
    the key check and the return can never hand back another artefact's
    files under this key.
    """
    global _artifact_cache
    key = (str(path), _file_state(path / MANIFEST_NAME), _file_state(path / SITES_NAME))
    entry = _artifact_cache
    if entry is None or entry[0] != key:
        entry = (key, read_artifact(path))
        _artifact_cache = entry
    return entry[1]


def _is_count(value: object) -> bool:
    """A date count: a non-negative int (bool, float, str, NaN are not)."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _check_structure(manifest: dict, rows_by_location: object) -> None:
    """Raise unless the files have the shape consumers rely on.

    Runs after ``validate_manifest``, which does not look at ``locations``,
    ``self_check`` or the rows. A baseline whose rows describe other sites
    than its manifest, or whose manifest cannot say how much history it has,
    is not used (``ValueError``). The declared ``minimum_independent_dates``
    must be exactly the weakest location's ``min_season_dates`` -- what
    ``build_manifest`` writes -- or the declaration does not describe this
    history (``BaselineInvalid("inconsistent_declaration")``).
    """
    locations = manifest.get("locations")
    if not isinstance(locations, dict) or not locations:
        raise ValueError("manifest 'locations' is missing or empty")
    for site_id, info in locations.items():
        if not isinstance(info, dict):
            raise ValueError(f"manifest location {site_id!r} is not an object")
        for field in ("n_dates", "min_season_dates"):
            if not _is_count(info.get(field)):
                raise ValueError(f"manifest location {site_id!r} has no integer {field}")
    weakest = min(info["min_season_dates"] for info in locations.values())
    if manifest["signal_anomaly"]["minimum_independent_dates"] != weakest:
        raise bridge.baseline_logic.BaselineInvalid("inconsistent_declaration")
    self_check = manifest.get("self_check")
    if not isinstance(self_check, dict) or not isinstance(self_check.get("total"), dict):
        raise ValueError("manifest 'self_check.total' is missing")
    if not isinstance(rows_by_location, dict):
        raise ValueError("sites.json 'rows' is not a {location: [rows]} mapping")
    if set(rows_by_location) != set(locations):
        raise ValueError("sites.json locations differ from the manifest's locations")
    for site_id, rows in rows_by_location.items():
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise ValueError(f"sites.json rows for {site_id!r} are not a list of objects")


def _validated_artifact_at() -> tuple[Path, dict, dict] | None:
    """``(path, manifest, rows)`` of the validated artefact -- NOT copies; internal only.

    None when the mode is not ``test`` or no complete artefact exists. Raises
    ``BaselineInvalid`` (reason in ``str(exc)``) for a refused manifest and
    other exceptions (``OSError``, ``ValueError`` incl. JSON errors,
    ``KeyError``) for an unreadable or malformed one. Level A checks only:
    the ``level_b`` block is not looked at here.
    """
    if config.BASELINE_MODE != "test":
        return None
    path = latest_artifact_path()
    if path is None:
        return None
    manifest, rows_by_location = _read_cached(path)
    logic = bridge.baseline_logic
    live_signature = logic.preprocessing_signature(bridge.preprocessing_params())
    logic.validate_manifest(manifest, live_signature=live_signature, today=_utc_today())
    _check_structure(manifest, rows_by_location)
    return path, manifest, rows_by_location


def _validated_artifact() -> tuple[dict, dict] | None:
    """The cached, validated ``(manifest, rows)``; see ``_validated_artifact_at``."""
    loaded = _validated_artifact_at()
    return None if loaded is None else (loaded[1], loaded[2])


def active_manifest() -> dict | None:
    """A copy of the validated manifest only (no rows copied); see ``load_active_baseline``."""
    loaded = _validated_artifact()
    return None if loaded is None else copy.deepcopy(loaded[0])


def load_active_baseline() -> ActiveBaseline | None:
    """The TEST baseline in force, or None.

    None when ``config.BASELINE_MODE`` (read now) is not exactly ``"test"``
    -- no file is looked at then -- or when ``BASELINE_ROOT`` holds no
    complete artefact. Otherwise the newest artefact, validated now against
    ``preprocessing_signature(preprocessing_params())`` and today's UTC date.

    Fails loudly, never quietly: raises ``BaselineInvalid`` for a manifest
    that must not be used and other exceptions for an unreadable one, so a
    caller can never mistake a refused baseline for an absent one. The
    never-raising view is ``scientific_status.baseline_status()``.
    """
    loaded = _validated_artifact()
    if loaded is None:
        return None
    manifest, rows_by_location = loaded
    return ActiveBaseline(
        manifest=copy.deepcopy(manifest),
        rows_by_location=copy.deepcopy(rows_by_location),
        version=manifest["baseline_version"],
    )


# --------------------------------------------------------------------------
# Level B: per-cell season baseline (never raises)
# --------------------------------------------------------------------------


def live_cell_preprocessing_params() -> dict:
    """How the production raster's cells are made NOW: raster scale and study polygon.

    Read at call time (``config.RASTER_SCAN_SCALE_M``), so a changed raster
    scale makes an existing cell baseline incompatible instead of silently
    comparing a 100 m cell with a 200 m history.
    """
    return bridge.cell_baseline_params(
        scale_m=config.RASTER_SCAN_SCALE_M,
        polygon_latlng=_study_area.STUDY_AREA_POLYGON_LATLNG,
    )


def live_cell_signature() -> str:
    """The cell preprocessing signature a Level B baseline must carry to be used."""
    return bridge.baseline_logic.preprocessing_signature(live_cell_preprocessing_params())


# Packing of a (row, col) cell key into one int64 for sorted lookup. Keys are
# |row|, |col| < 2**31 (a 100 m cell is ~0.0009 deg; 180 deg is ~2e5 cells).
_KEY_PACK = 1 << 32


def _packed_keys(rows: np.ndarray, cols: np.ndarray) -> np.ndarray:
    return rows.astype(np.int64) * _KEY_PACK + cols.astype(np.int64)


@dataclass(frozen=True, eq=False)
class CellBaseline:
    """One season of the Level B TEST baseline, validated at load time.

    Arrays are read-only and shared with the loader's cache (copying ~290k
    cells per request would be the expensive part); ``index_of`` /
    ``key_index`` match cells by ``baseline.cell_key``, never by position.
    ``history_end`` is the leakage cutoff: only a cell acquired strictly
    after it may be assessed against this baseline.

    ``min_independent_dates`` is the floor the ``level_b`` block DECLARES
    (validated >= signal_anomaly's 30; rounded up if a hand edit made it
    fractional, so it can never be loosened by truncation). ``summary`` is
    a read-only view of this season's manifest description (counts, MAD
    percentiles, history span) for the API's ``baseline.level_b`` block;
    it is read from the same manifest as everything else here, so the
    numbers it shows describe exactly these arrays.
    """

    season_key: str
    months: tuple[int, int, int]
    version: str
    history_end: str
    scale_m: int
    file: str
    lat: np.ndarray = field(repr=False)
    lng: np.ndarray = field(repr=False)
    median: np.ndarray = field(repr=False)
    mad: np.ndarray = field(repr=False)
    n: np.ndarray = field(repr=False)
    min_independent_dates: int = field(
        default_factory=lambda: bridge.SIGNAL_ANOMALY_MIN_INDEPENDENT_DATES
    )
    summary: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}), repr=False)

    @cached_property
    def _sorted_keys(self) -> tuple[np.ndarray, np.ndarray]:
        rows, cols = bridge.baseline_logic.cell_keys(self.lat, self.lng, self.scale_m)
        packed = _packed_keys(rows, cols)
        order = np.argsort(packed, kind="stable")
        return packed[order], order

    @cached_property
    def key_index(self) -> dict[tuple[int, int], int]:
        """``{cell_key: array index}``, built on first use. ~170 bytes per
        cell; prefer ``index_of`` for many cells at once."""
        rows, cols = bridge.baseline_logic.cell_keys(self.lat, self.lng, self.scale_m)
        return {key: i for i, key in enumerate(zip(rows.tolist(), cols.tolist()))}

    def index_of(self, lat, lng) -> np.ndarray:
        """Array index of the baseline cell at each (lat, lng), -1 where none.

        Vectorised; non-finite coordinates are -1. Same key, same half-cell
        tolerance as ``baseline.cell_key``.
        """
        lat = np.asarray(lat, dtype=np.float64)
        lng = np.asarray(lng, dtype=np.float64)
        out = np.full(lat.shape, -1, dtype=np.int64)
        finite = np.isfinite(lat) & np.isfinite(lng)
        if not finite.any() or self.lat.size == 0:
            return out
        rows, cols = bridge.baseline_logic.cell_keys(lat[finite], lng[finite], self.scale_m)
        wanted = _packed_keys(rows, cols)
        keys, order = self._sorted_keys
        pos = np.searchsorted(keys, wanted)
        clipped = np.minimum(pos, keys.size - 1)
        found = (pos < keys.size) & (keys[clipped] == wanted)
        out[finite] = np.where(found, order[clipped], -1)
        return out


# Parsed and checked seasons, keyed on (artefact path, season, manifest /
# sites / cells file states). Small: one season is ~7 MB of arrays.
_CELL_CACHE_SIZE = 2
_cell_cache: "OrderedDict[tuple, CellBaseline]" = OrderedDict()
_cell_cache_lock = threading.Lock()
_last_cell_warning: str | None = None


def clear_cell_cache() -> None:
    """Forget every cached season (tests; or after replacing an artefact by hand)."""
    with _cell_cache_lock:
        _cell_cache.clear()


def _load_season(path: Path, season_key: str, manifest: dict) -> CellBaseline:
    """Read one season file and check it against the manifest (raises)."""
    logic = bridge.baseline_logic
    level_b = manifest["level_b"]
    info = level_b["seasons"][season_key]
    arrays = read_cells_file(path / info["file"])
    scale_m = level_b["scale_m"]

    reaching = int(np.count_nonzero(arrays["n"] >= level_b["min_independent_dates"]))
    if arrays["n"].size != info["cells"] or reaching != info["cells_n_ge_floor"]:
        raise logic.BaselineInvalid(f"level_b_inconsistent:{season_key}")
    if logic.grid_offset_cells(arrays["lat"], arrays["lng"], scale_m) > logic.CELL_GRID_TOLERANCE_CELLS:
        raise logic.BaselineInvalid(f"level_b_off_grid:{season_key}")
    rows, cols = logic.cell_keys(arrays["lat"], arrays["lng"], scale_m)
    if np.unique(_packed_keys(rows, cols)).size != arrays["n"].size:
        raise logic.BaselineInvalid(f"level_b_duplicate_cells:{season_key}")

    for value in arrays.values():
        value.setflags(write=False)
    # validate_level_b has checked it is a finite number >= the floor.
    floor = int(math.ceil(level_b["min_independent_dates"]))
    return CellBaseline(
        season_key=season_key,
        months=tuple(info["months"]),
        version=manifest["baseline_version"],
        history_end=level_b["history_end"],
        scale_m=scale_m,
        file=info["file"],
        **arrays,
        min_independent_dates=floor,
        summary=MappingProxyType(_season_summary(level_b, season_key, info, floor)),
    )


# Season-file statistics copied into ``CellBaseline.summary`` when the
# manifest has them (builder extras are optional; absent means None).
_SUMMARY_SEASON_FIELDS = (
    "cells", "cells_n_ge_floor", "share_n_ge_floor", "n_median", "n_min", "n_max",
    "mad_p05", "mad_p50", "mad_p95", "n_dates", "first_date", "last_date",
)


def _season_summary(level_b: dict, season_key: str, info: dict, floor: int) -> dict:
    """A plain-JSON description of one season of the Level B baseline.

    Scalars only (``months`` as a tuple), copied, so the read-only view on
    the cached ``CellBaseline`` shares nothing mutable with the manifest.
    """
    summary: dict[str, Any] = {
        "season_key": season_key,
        "months": tuple(info["months"]),
        "file": info["file"],
        "scale_m": level_b["scale_m"],
        "history_start": level_b["history_start"],
        "history_end": level_b["history_end"],
        "history_end_rule": level_b.get("history_end_rule"),
        "season_rule": level_b.get("season_rule"),
        "min_independent_dates": floor,
        "cell_preprocessing_signature": level_b["cell_preprocessing_signature"],
        "built_at": level_b.get("built_at"),
    }
    for name in _SUMMARY_SEASON_FIELDS:
        value = info.get(name)
        summary[name] = value if value is None or isinstance(value, (int, float, str)) else None
    return summary


def _cached_season(path: Path, season_key: str, manifest: dict) -> CellBaseline:
    info = manifest["level_b"]["seasons"][season_key]
    key = (
        str(path),
        season_key,
        _file_state(path / MANIFEST_NAME),
        _file_state(path / SITES_NAME),
        _file_state(path / info["file"]),
    )
    with _cell_cache_lock:
        hit = _cell_cache.get(key)
        if hit is not None:
            _cell_cache.move_to_end(key)
            return hit
    loaded = _load_season(path, season_key, manifest)  # file IO outside the lock
    with _cell_cache_lock:
        _cell_cache[key] = loaded
        _cell_cache.move_to_end(key)
        while len(_cell_cache) > _CELL_CACHE_SIZE:
            _cell_cache.popitem(last=False)
    return loaded


def _cell_refused(season_key: str, reason: str, *, detail: str | None = None, exc_info: bool = False):
    """Log (once per distinct message) why no cell baseline is used; return ``(None, reason)``."""
    global _last_cell_warning
    message = f"Level B cell baseline {season_key} not used ({reason})"
    if detail:
        message += f": {detail}"
    if message != _last_cell_warning:
        logger.warning(message, exc_info=exc_info)
        _last_cell_warning = message
    return None, reason


def cell_baseline_or_reason(season_key: str) -> tuple[CellBaseline | None, str | None]:
    """``(CellBaseline, None)`` for a usable season, else ``(None, reason)``. Never raises.

    Reasons: ``mode_off`` (BASELINE_MODE is not ``test``; no file is looked
    at), ``no_artifact``, ``no_level_b`` (a Level A-only artefact),
    ``unknown_season:<key>``, ``missing_cells_file:<name>`` (any of the
    twelve), ``invalid:<BaselineInvalid reason>`` (Level A or Level B
    validation, a file disagreeing with the manifest, cells off the grid or
    sharing a key) and ``unreadable`` (anything else). Every reason but
    ``mode_off`` is logged at WARNING, once per distinct message.
    """
    global _last_cell_warning
    try:
        if config.BASELINE_MODE != "test":
            return None, "mode_off"
        loaded = _validated_artifact_at()
        if loaded is None:
            return _cell_refused(season_key, "no_artifact")
        path, manifest, _rows = loaded
        level_b = manifest.get("level_b")
        if level_b is None:
            return _cell_refused(season_key, "no_level_b")
        logic = bridge.baseline_logic
        logic.validate_level_b(level_b, live_cell_signature=live_cell_signature(), today=_utc_today())
        seasons = level_b["seasons"]
        if season_key not in seasons:
            return _cell_refused(season_key, f"unknown_season:{season_key}")
        for info in seasons.values():
            if not (path / info["file"]).is_file():
                return _cell_refused(season_key, f"missing_cells_file:{info['file']}")
        cells = _cached_season(path, season_key, manifest)
    except bridge.baseline_logic.BaselineInvalid as exc:
        return _cell_refused(season_key, f"invalid:{exc}")
    except Exception as exc:  # noqa: BLE001 -- the cell baseline must fail closed, never raise
        return _cell_refused(season_key, "unreadable", detail=f"{type(exc).__name__}: {exc}", exc_info=True)
    _last_cell_warning = None
    return cells, None


def load_cell_baseline(season_key: str) -> CellBaseline | None:
    """The usable Level B season ``season_key`` (e.g. ``"m10+-1"``), or None. Never raises.

    See ``cell_baseline_or_reason`` for when and why it is None.
    """
    return cell_baseline_or_reason(season_key)[0]
