"""Artefact IO for the TEST baseline: write/read round-trip and version choice.

Offline and filesystem-only (pytest ``tmp_path``). Nothing here touches GEE,
the database or ``backend/data``.
"""

from __future__ import annotations

import json

import pytest

from src import baseline_store
from src.baseline_store import (
    BASELINE_ROOT,
    ArtifactExists,
    latest_artifact_path,
    read_artifact,
    write_artifact,
)


def _manifest(version: str) -> dict:
    return {"baseline_kind": "test", "baseline_version": version, "locations": {}}


def _rows() -> dict[str, list[dict]]:
    return {
        "bangsaen": [
            {"acquisition_date": "2024-01-05", "ndci": 0.12, "cloud_fraction": 0.0, "scene_id": "a"},
            {"acquisition_date": "2024-01-10", "ndci": -0.03, "cloud_fraction": 0.05, "scene_id": None},
        ],
        "pattaya": [],
    }


def test_baseline_root_is_under_backend_data_baselines():
    assert BASELINE_ROOT.parts[-3:] == ("backend", "data", "baselines")


def test_write_then_read_round_trips(tmp_path):
    manifest = _manifest("TEST-20261009-aaaaaaaa")
    path = write_artifact(tmp_path, manifest, _rows())

    assert path == tmp_path / "TEST-20261009-aaaaaaaa"
    assert (path / "manifest.json").is_file()
    assert (path / "sites.json").is_file()

    got_manifest, got_rows = read_artifact(path)
    assert got_manifest == manifest
    assert got_rows == _rows()


def test_sites_file_wraps_rows_under_a_rows_key(tmp_path):
    path = write_artifact(tmp_path, _manifest("TEST-20261009-aaaaaaaa"), _rows())
    on_disk = json.loads((path / "sites.json").read_text(encoding="utf-8"))
    assert list(on_disk) == ["rows"]
    assert set(on_disk["rows"]) == {"bangsaen", "pattaya"}


def test_write_creates_missing_root(tmp_path):
    root = tmp_path / "does" / "not" / "exist"
    path = write_artifact(root, _manifest("TEST-20261009-aaaaaaaa"), _rows())
    assert path.parent == root


def test_rewriting_the_same_version_is_refused_by_default(tmp_path):
    """A version is what cached anomalies are paired with; its content must not change silently."""
    version = "TEST-20261009-aaaaaaaa"
    path = write_artifact(tmp_path, _manifest(version), _rows())
    replacement = {"bangsaen": [{"acquisition_date": "2025-02-01", "ndci": 0.2}]}

    with pytest.raises(ArtifactExists) as excinfo:
        write_artifact(tmp_path, _manifest(version), replacement)

    assert isinstance(excinfo.value, FileExistsError)
    assert excinfo.value.path == path
    assert version in str(excinfo.value)
    _, rows = read_artifact(path)
    assert rows == _rows()  # untouched
    assert sorted(p.name for p in tmp_path.iterdir()) == [version]  # no scratch left


def test_rewriting_the_same_version_with_replace_replaces_it_and_leaves_no_debris(tmp_path):
    version = "TEST-20261009-aaaaaaaa"
    write_artifact(tmp_path, _manifest(version), _rows())
    replacement = {"bangsaen": [{"acquisition_date": "2025-02-01", "ndci": 0.2}]}
    path = write_artifact(tmp_path, _manifest(version), replacement, replace=True)

    _, rows = read_artifact(path)
    assert rows == replacement
    assert sorted(p.name for p in tmp_path.iterdir()) == [version]


def test_replace_on_a_new_version_simply_writes_it(tmp_path):
    path = write_artifact(tmp_path, _manifest("TEST-20261009-aaaaaaaa"), _rows(), replace=True)
    assert read_artifact(path)[1] == _rows()


def test_non_finite_values_are_refused_rather_than_written_as_invalid_json(tmp_path):
    bad = {"bangsaen": [{"acquisition_date": "2024-01-05", "ndci": float("nan")}]}
    with pytest.raises(ValueError):
        write_artifact(tmp_path, _manifest("TEST-20261009-aaaaaaaa"), bad)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("version", ["", "../escape", "a/b", ".hidden", "a\\b", None])
def test_unsafe_version_names_are_refused(tmp_path, version):
    manifest = _manifest("x")
    manifest["baseline_version"] = version
    with pytest.raises(ValueError):
        write_artifact(tmp_path, manifest, _rows())
    assert list(tmp_path.iterdir()) == []


def test_latest_artifact_path_picks_the_highest_version(tmp_path):
    for version in ("TEST-20260101-aaaaaaaa", "TEST-20261009-bbbbbbbb", "TEST-20260601-cccccccc"):
        write_artifact(tmp_path, _manifest(version), _rows())
    assert latest_artifact_path(tmp_path) == tmp_path / "TEST-20261009-bbbbbbbb"


def test_latest_artifact_path_ignores_directories_missing_a_file(tmp_path):
    write_artifact(tmp_path, _manifest("TEST-20260101-aaaaaaaa"), _rows())
    only_manifest = tmp_path / "TEST-20270101-bbbbbbbb"
    only_manifest.mkdir()
    (only_manifest / "manifest.json").write_text("{}", encoding="utf-8")
    only_sites = tmp_path / "TEST-20280101-cccccccc"
    only_sites.mkdir()
    (only_sites / "sites.json").write_text("{}", encoding="utf-8")
    (tmp_path / "TEST-20290101-stray.txt").write_text("not a directory", encoding="utf-8")

    assert latest_artifact_path(tmp_path) == tmp_path / "TEST-20260101-aaaaaaaa"


def test_latest_artifact_path_ignores_hidden_scratch_directories(tmp_path):
    write_artifact(tmp_path, _manifest("TEST-20260101-aaaaaaaa"), _rows())
    scratch = tmp_path / ".tmp-TEST-20990101-zzzzzzzz"
    scratch.mkdir()
    (scratch / "manifest.json").write_text("{}", encoding="utf-8")
    (scratch / "sites.json").write_text("{}", encoding="utf-8")

    assert latest_artifact_path(tmp_path) == tmp_path / "TEST-20260101-aaaaaaaa"


def test_latest_artifact_path_is_none_when_empty_or_missing(tmp_path):
    assert latest_artifact_path(tmp_path) is None
    assert latest_artifact_path(tmp_path / "nope") is None


def test_latest_artifact_path_defaults_to_baseline_root(monkeypatch, tmp_path):
    write_artifact(tmp_path, _manifest("TEST-20261009-aaaaaaaa"), _rows())
    monkeypatch.setattr(baseline_store, "BASELINE_ROOT", tmp_path)
    assert latest_artifact_path() == tmp_path / "TEST-20261009-aaaaaaaa"
