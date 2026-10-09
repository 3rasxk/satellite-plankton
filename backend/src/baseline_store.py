"""On-disk store for the TEST seasonal baseline artefact, and its gated loader.

Data source: none of its own. The caller passes a manifest and per-location
NDCI history rows already produced by ``scripts/build_test_baseline.py``
(Sentinel-2 via ``data-pipeline/src/history.py``); this module only writes
them to, and reads them back from, ``backend/data/baselines/`` (gitignored
local data, like ``app.db``).

Layout, one directory per baseline version::

    <root>/<baseline_version>/manifest.json   description and activation declaration
    <root>/<baseline_version>/sites.json      {"rows": {site_id: [history rows]}}

``write_artifact`` / ``read_artifact`` / ``latest_artifact_path`` do not
validate the manifest or judge whether the baseline is fit to use; they hand
back whatever was written, including a manifest that would be refused.

``load_active_baseline`` (and ``active_manifest``) is the one gated reader:
it returns nothing unless ``config.BASELINE_MODE`` is exactly ``"test"``, and
then only the newest artefact that passes ``detection/src/baseline.py``'s
``validate_manifest`` against the live preprocessing signature and today's
UTC date, plus a structural check that the rows match the manifest. It
decides nothing itself beyond that structure check; the rules are
detection's. Parsed files are cached on each file's (mtime_ns, size, inode),
but validation is re-run on every call, because "today" and the live
signature are not properties of the files.

Limitations: the rows are dimensionless NDCI readings from a point-buffer
mean over clear-sky water pixels, kept only on cloud-free days. They are a
statistical record of one place, not bloom evidence, and carry no validation
against recorded bloom events.
"""

from __future__ import annotations

import copy
import json
import math
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from . import _detection as bridge
from . import config

BASELINE_ROOT = Path(__file__).resolve().parents[1] / "data" / "baselines"

MANIFEST_NAME = "manifest.json"
SITES_NAME = "sites.json"


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


def write_artifact(root: Path, manifest: dict, rows_by_location: dict[str, list[dict]]) -> Path:
    """Write ``manifest`` and ``rows_by_location``; return the version directory.

    The directory is ``<root>/<manifest["baseline_version"]>``. Both files are
    written into a hidden scratch directory first and moved into place only
    when both succeeded, so a failed or interrupted write never leaves a
    directory that ``latest_artifact_path`` would take for a complete one. An
    existing directory for the same version is replaced.

    Raises ``ValueError`` for an unusable version name or a value JSON cannot
    carry (NaN, inf). Nothing is left behind in that case.
    """
    version = _check_version(manifest.get("baseline_version"))
    root = Path(root)
    final = root / version

    root.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix=f".tmp-{version}-", dir=root))
    try:
        _dump(manifest, scratch / MANIFEST_NAME, indent=2)
        _dump({"rows": rows_by_location}, scratch / SITES_NAME, indent=None)
        if final.exists():
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
    """Parsed ``(manifest, rows_by_location)``, re-read when either file changes."""
    global _artifact_cache
    key = (str(path), _file_state(path / MANIFEST_NAME), _file_state(path / SITES_NAME))
    if _artifact_cache is None or _artifact_cache[0] != key:
        _artifact_cache = (key, read_artifact(path))
    return _artifact_cache[1]


def _is_count(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _check_structure(manifest: dict, rows_by_location: object) -> None:
    """Raise ``ValueError`` unless the files have the shape consumers rely on.

    Runs after ``validate_manifest``, which does not look at ``locations``,
    ``self_check`` or the rows. A baseline whose rows describe other sites
    than its manifest, or whose manifest cannot say how much history it has,
    is not used.
    """
    locations = manifest.get("locations")
    if not isinstance(locations, dict) or not locations:
        raise ValueError("manifest 'locations' is missing or empty")
    for site_id, info in locations.items():
        if not isinstance(info, dict) or not _is_count(info.get("n_dates")):
            raise ValueError(f"manifest location {site_id!r} has no numeric n_dates")
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


def _validated_artifact() -> tuple[dict, dict] | None:
    """The cached, validated ``(manifest, rows)`` -- NOT copies; internal only.

    None when the mode is not ``test`` or no complete artefact exists. Raises
    ``BaselineInvalid`` (reason in ``str(exc)``) for a refused manifest and
    other exceptions (``OSError``, ``ValueError`` incl. JSON errors,
    ``KeyError``) for an unreadable or malformed one.
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
    return manifest, rows_by_location


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
