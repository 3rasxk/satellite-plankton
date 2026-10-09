"""On-disk store for the TEST seasonal baseline artefact (file IO only).

Data source: none of its own. The caller passes a manifest and per-location
NDCI history rows already produced by ``scripts/build_test_baseline.py``
(Sentinel-2 via ``data-pipeline/src/history.py``); this module only writes
them to, and reads them back from, ``backend/data/baselines/`` (gitignored
local data, like ``app.db``).

Layout, one directory per baseline version::

    <root>/<baseline_version>/manifest.json   description and activation declaration
    <root>/<baseline_version>/sites.json      {"rows": {site_id: [history rows]}}

What it deliberately does not do: it does not validate the manifest, judge
whether the baseline is fit to use, or compute anything. Deciding that is
``detection/src/baseline.py``'s ``validate_manifest``; this module will hand
back whatever was written, including a manifest that would be refused.

Limitations: the rows are dimensionless NDCI readings from a point-buffer
mean over clear-sky water pixels, kept only on cloud-free days. They are a
statistical record of one place, not bloom evidence, and carry no validation
against recorded bloom events.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

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
