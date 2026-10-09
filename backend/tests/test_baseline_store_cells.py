"""Level B (per-cell) TEST baseline: cells-file IO and the never-raising loader.

Offline and filesystem-only: every artefact is synthetic, written under
pytest's ``tmp_path`` with ``baseline_store.BASELINE_ROOT`` pointed there.
The manifest (Level A part and ``level_b`` block) is built by the real
``detection/src/baseline.py`` through the bridge, so the fixture is what the
builder writes, not a hand copy. Nothing here touches GEE or backend/data.
"""

from __future__ import annotations

import json
import logging
from datetime import date

import numpy as np
import pytest

from src import _detection as bridge
from src import _study_area, baseline_store, config

logic = bridge.baseline_logic

DEG = 200 / 111319.49079327357
FLOOR = bridge.SIGNAL_ANOMALY_MIN_INDEPENDENT_DATES
BUILT_ON = date(2026, 1, 15)


# --------------------------------------------------------------------------
# Synthetic artefact
# --------------------------------------------------------------------------


def _site_rows() -> list[dict]:
    return [
        {"acquisition_date": f"{y}-{m:02d}-{d:02d}", "ndci": 0.02 + 0.001 * ((y + m + d) % 7),
         "cloud_fraction": 0.0, "scene_id": f"s{y}{m:02d}{d:02d}"}
        for y in range(2011, 2026) for m in range(1, 13) for d in (5, 20)
    ]


def _cells(month: int, count: int = 20, low_n: int = 1) -> dict:
    """``count`` aligned cells; the first ``low_n`` have n below the floor."""
    rows = 7000 + np.arange(count) // 5
    cols = 55800 + np.arange(count) % 5
    n = np.full(count, 40 + month, dtype=np.uint16)
    n[:low_n] = 10
    return {
        "lat": (rows + 0.5) * DEG,
        "lng": (cols + 0.5) * DEG,
        "median": np.linspace(0.01, 0.05, count).astype(np.float32) + np.float32(month / 1000),
        "mad": np.full(count, 0.02, dtype=np.float32),
        "n": n,
    }


def _live_cell_signature() -> str:
    return logic.preprocessing_signature(baseline_store.live_cell_preprocessing_params())


def _level_b(cells_by_month: dict[int, dict], **overrides) -> dict:
    seasons = {}
    for month, arrays in cells_by_month.items():
        summary = logic.cell_season_summary(arrays["n"], arrays["mad"])
        seasons[logic.season_key(month)] = {
            "file": logic.cells_file_name(month),
            "months": list(logic.season_months(month)),
            **summary,
            "n_dates": 140,
            "first_date": "2017-12-13",
            "last_date": "2025-11-30",
        }
    block = logic.build_level_b(
        scale_m=config.RASTER_SCAN_SCALE_M,
        cell_preprocessing_signature=_live_cell_signature(),
        cell_preprocessing_params=baseline_store.live_cell_preprocessing_params(),
        built_at="2026-01-15T03:00:00+00:00",
        query_start="2017-03-28",
        query_end_exclusive="2025-12-31",
        seasons=seasons,
    )
    block.update(overrides)
    return block


def _manifest(level_b: dict | None) -> tuple[dict, dict]:
    rows = {"alpha": _site_rows()}
    signature = logic.preprocessing_signature(bridge.preprocessing_params())
    manifest = logic.build_manifest(
        baseline_version=logic.version_for(BUILT_ON, signature),
        built_at="2026-01-15T03:00:00+00:00",
        history_start=rows["alpha"][0]["acquisition_date"],
        history_end=rows["alpha"][-1]["acquisition_date"],
        preprocessing_signature=signature,
        preprocessing_params=bridge.preprocessing_params(),
        locations={"alpha": {"n_dates": len(rows["alpha"]), "min_season_dates": 90,
                             "first": rows["alpha"][0]["acquisition_date"],
                             "last": rows["alpha"][-1]["acquisition_date"]}},
        self_check={"by_season": {}, "total": {"assessed": 0}},
        builder_git_sha=None,
    )
    if level_b is not None:
        manifest["level_b"] = level_b
    return manifest, rows


def _write(root, *, with_level_b: bool = True, replace: bool = False, cells=None, **overrides):
    cells = cells or {month: _cells(month) for month in range(1, 13)}
    manifest, rows = _manifest(_level_b(cells, **overrides) if with_level_b else None)
    files = {logic.cells_file_name(m): arrays for m, arrays in cells.items()} if with_level_b else None
    path = baseline_store.write_artifact(root, manifest, rows, replace=replace, cells_by_file=files)
    return path, manifest, cells


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    root = tmp_path / "baselines"
    monkeypatch.setattr(baseline_store, "BASELINE_ROOT", root)
    monkeypatch.setattr(baseline_store, "_artifact_cache", None)
    monkeypatch.setattr(baseline_store, "_last_cell_warning", None)
    baseline_store.clear_cell_cache()
    monkeypatch.setattr(config, "BASELINE_MODE", "off")
    yield root
    baseline_store.clear_cell_cache()


@pytest.fixture()
def root(_isolated):
    return _isolated


@pytest.fixture()
def test_mode(monkeypatch):
    monkeypatch.setattr(config, "BASELINE_MODE", "test")


SEASON = logic.season_key(10)


# --------------------------------------------------------------------------
# Cells files
# --------------------------------------------------------------------------


def test_cells_files_round_trip_with_storage_dtypes(root):
    path, manifest, cells = _write(root)
    for month in range(1, 13):
        name = logic.cells_file_name(month)
        assert (path / name).is_file()
        got = baseline_store.read_cells_file(path / name)
        assert set(got) == {"lat", "lng", "median", "mad", "n"}
        assert got["lat"].dtype == np.float64 and got["lng"].dtype == np.float64
        assert got["median"].dtype == np.float32 and got["mad"].dtype == np.float32
        assert got["n"].dtype == np.uint16
        for key in got:
            np.testing.assert_array_equal(got[key], cells[month][key])
    assert set(manifest["level_b"]["seasons"]) == {logic.season_key(m) for m in range(1, 13)}


@pytest.mark.parametrize("name", ["../escape.npz", "sites.json", "manifest.json", "cells_m13.npz", "cells.npz"])
def test_unsafe_cells_file_names_are_refused_and_nothing_is_left(root, name):
    manifest, rows = _manifest(None)
    with pytest.raises(ValueError):
        baseline_store.write_artifact(root, manifest, rows, cells_by_file={name: _cells(1)})
    assert not root.exists() or list(root.iterdir()) == []


@pytest.mark.parametrize(
    "mutate",
    [
        lambda a: a.update(n=a["n"][:-1]),
        lambda a: a.update(n=a["n"].astype(np.float64) + 0.5),
        lambda a: a.update(n=np.full(a["lat"].size, 70000, dtype=np.int64)),
        lambda a: a.update(n=np.full(a["lat"].size, -1, dtype=np.int64)),
        lambda a: a.pop("mad"),
        lambda a: a.update(extra=np.zeros(3)),
        lambda a: a.update(lat=a["lat"].reshape(4, 5)),
    ],
)
def test_malformed_cells_are_refused_before_anything_is_written(root, mutate):
    arrays = _cells(1)
    mutate(arrays)
    manifest, rows = _manifest(None)
    with pytest.raises(ValueError):
        baseline_store.write_artifact(root, manifest, rows, cells_by_file={"cells_m01.npz": arrays})
    assert not root.exists() or list(root.iterdir()) == []


def test_read_cells_file_refuses_wrong_dtypes_and_extra_arrays(tmp_path):
    good = _cells(1)
    narrow = tmp_path / "narrow.npz"
    np.savez_compressed(narrow, **{**good, "lat": good["lat"].astype(np.float32)})
    with pytest.raises(ValueError, match="lat"):
        baseline_store.read_cells_file(narrow)
    extra = tmp_path / "extra.npz"
    np.savez_compressed(extra, **good, other=np.zeros(1))
    with pytest.raises(ValueError):
        baseline_store.read_cells_file(extra)
    objects = tmp_path / "objects.npz"
    np.savez(objects, **{**good, "n": np.array([{"a": 1}] * good["n"].size, dtype=object)})
    with pytest.raises(ValueError):
        baseline_store.read_cells_file(objects)


def test_float32_and_float64_are_cast_to_the_storage_dtypes_on_write(root):
    arrays = _cells(1)
    arrays["median"] = arrays["median"].astype(np.float64)
    arrays["n"] = arrays["n"].astype(np.int64)
    manifest, rows = _manifest(None)
    path = baseline_store.write_artifact(root, manifest, rows, cells_by_file={"cells_m01.npz": arrays})
    got = baseline_store.read_cells_file(path / "cells_m01.npz")
    assert got["median"].dtype == np.float32 and got["n"].dtype == np.uint16


# --------------------------------------------------------------------------
# Loader: off, absent, invalid
# --------------------------------------------------------------------------


def test_mode_off_returns_none_without_touching_files(root, monkeypatch):
    _write(root)

    def must_not_be_called(*_a, **_k):
        raise AssertionError("mode off must not look at the artefact")

    monkeypatch.setattr(baseline_store, "latest_artifact_path", must_not_be_called)
    assert baseline_store.load_cell_baseline(SEASON) is None
    assert baseline_store.cell_baseline_or_reason(SEASON) == (None, "mode_off")


def test_no_artifact(root, test_mode):
    assert baseline_store.cell_baseline_or_reason(SEASON) == (None, "no_artifact")


def test_level_a_only_artefact_has_no_cell_baseline(root, test_mode):
    _write(root, with_level_b=False)
    assert baseline_store.cell_baseline_or_reason(SEASON) == (None, "no_level_b")
    # ... and the site baseline is unaffected.
    assert baseline_store.load_active_baseline() is not None


def test_missing_cells_file_is_reported_even_for_another_season(root, test_mode):
    path, _, _ = _write(root)
    (path / "cells_m03.npz").unlink()
    assert baseline_store.cell_baseline_or_reason(SEASON) == (None, "missing_cells_file:cells_m03.npz")
    assert baseline_store.load_cell_baseline(SEASON) is None


def test_unknown_season(root, test_mode):
    _write(root)
    assert baseline_store.cell_baseline_or_reason("m13+-1") == (None, "unknown_season:m13+-1")


def test_live_scale_change_makes_the_cell_baseline_incompatible(root, test_mode, monkeypatch):
    _write(root)
    monkeypatch.setattr(config, "RASTER_SCAN_SCALE_M", 100)
    assert baseline_store.cell_baseline_or_reason(SEASON) == (None, "invalid:cell_signature_mismatch")
    # Level A does not depend on the raster scale.
    assert baseline_store.load_active_baseline() is not None


def test_live_masking_change_makes_the_cell_baseline_incompatible(root, test_mode, monkeypatch):
    _write(root)
    real = bridge.cell_baseline_params
    monkeypatch.setattr(bridge, "cell_baseline_params", lambda **kw: {**real(**kw), "cloud_classes": [9]})
    assert baseline_store.cell_baseline_or_reason(SEASON) == (None, "invalid:cell_signature_mismatch")


def test_level_b_history_end_in_the_future_is_refused(root, test_mode, monkeypatch):
    _write(root)
    monkeypatch.setattr(baseline_store, "_utc_today", lambda: date(2025, 12, 1))
    # The Level A history ends 2025-12-20, so Level A fails first here.
    assert baseline_store.cell_baseline_or_reason(SEASON)[1] == "invalid:history_in_future"


def test_level_b_history_end_alone_in_the_future_is_refused(root, test_mode, monkeypatch):
    _write(root, history_end="2099-01-01")
    assert baseline_store.cell_baseline_or_reason(SEASON) == (None, "invalid:level_b_history_in_future")


def test_level_a_invalid_means_no_cell_baseline(root, test_mode, monkeypatch):
    _write(root)
    monkeypatch.setattr(bridge, "preprocessing_params", lambda: {"changed": True})
    assert baseline_store.cell_baseline_or_reason(SEASON) == (None, "invalid:signature_mismatch")


def test_file_that_disagrees_with_the_manifest_is_refused(root, test_mode):
    cells = {month: _cells(month) for month in range(1, 13)}
    path, manifest, _ = _write(root, cells=cells)
    # Same name, different content: one cell fewer than the manifest declares.
    shorter = {k: v[:-1] for k, v in cells[10].items()}
    np.savez_compressed(path / "cells_m10.npz", **shorter)
    assert baseline_store.cell_baseline_or_reason(SEASON) == (None, r"invalid:level_b_inconsistent:m10+-1")


def test_duplicate_grid_keys_are_refused(root, test_mode):
    cells = {month: _cells(month) for month in range(1, 13)}
    cells[10]["lat"][1] = cells[10]["lat"][0] + 1e-7
    cells[10]["lng"][1] = cells[10]["lng"][0] - 1e-7
    _write(root, cells=cells)
    assert baseline_store.cell_baseline_or_reason(SEASON) == (None, "invalid:level_b_duplicate_cells:m10+-1")


def test_corrupt_cells_file_is_unreadable_and_never_raises(root, test_mode):
    path, _, _ = _write(root)
    (path / "cells_m10.npz").write_bytes(b"not a zip at all")
    assert baseline_store.cell_baseline_or_reason(SEASON) == (None, "unreadable")
    assert baseline_store.load_cell_baseline(SEASON) is None


def test_unexpected_error_never_escapes(root, test_mode, monkeypatch, caplog):
    _write(root)

    def boom(*_a, **_k):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(baseline_store, "read_cells_file", boom)
    with caplog.at_level(logging.WARNING, logger=baseline_store.logger.name):
        assert baseline_store.load_cell_baseline(SEASON) is None
        assert baseline_store.load_cell_baseline(SEASON) is None
    warnings = [r for r in caplog.records if "cell baseline" in r.getMessage().lower()]
    assert len(warnings) == 1  # logged once, not on every request


def test_a_broken_level_b_never_disables_level_a(root, test_mode):
    _write(root, cell_preprocessing_signature="0" * 16)
    assert baseline_store.cell_baseline_or_reason(SEASON) == (None, "invalid:cell_signature_mismatch")
    assert baseline_store.load_active_baseline() is not None


# --------------------------------------------------------------------------
# Loader: valid
# --------------------------------------------------------------------------


def test_valid_cell_baseline(root, test_mode):
    path, manifest, cells = _write(root)
    loaded, reason = baseline_store.cell_baseline_or_reason(SEASON)
    assert reason is None
    assert loaded is not None
    assert loaded.season_key == SEASON
    assert loaded.version == manifest["baseline_version"] == path.name
    assert loaded.history_end == manifest["level_b"]["history_end"] == "2025-12-30"
    assert loaded.scale_m == config.RASTER_SCAN_SCALE_M
    assert loaded.months == (9, 10, 11)
    for key in ("lat", "lng", "median", "mad", "n"):
        np.testing.assert_array_equal(getattr(loaded, key), cells[10][key])
        assert not getattr(loaded, key).flags.writeable
    assert baseline_store.load_cell_baseline(SEASON) is loaded  # cached


def test_key_index_and_vectorised_lookup(root, test_mode):
    _write(root)
    loaded = baseline_store.load_cell_baseline(SEASON)
    index = loaded.key_index
    assert len(index) == loaded.lat.size
    for i in (0, 7, 19):
        assert index[logic.cell_key(loaded.lat[i], loaded.lng[i], loaded.scale_m)] == i

    # Production-side coordinates of the same cells, with float noise, plus
    # one cell the baseline does not have.
    probe_lat = np.append(loaded.lat[[3, 0, 19]] + 1e-7, (6000 + 0.5) * DEG)
    probe_lng = np.append(loaded.lng[[3, 0, 19]] - 1e-7, (55000 + 0.5) * DEG)
    assert loaded.index_of(probe_lat, probe_lng).tolist() == [3, 0, 19, -1]


def test_cache_follows_a_rewritten_artefact(root, test_mode):
    _write(root)
    first = baseline_store.load_cell_baseline(SEASON)
    cells = {month: _cells(month, count=25) for month in range(1, 13)}
    _write(root, cells=cells, replace=True)
    second = baseline_store.load_cell_baseline(SEASON)
    assert second is not first
    assert second.lat.size == 25


def test_live_cell_params_are_the_raster_scale_and_study_polygon(monkeypatch):
    params = baseline_store.live_cell_preprocessing_params()
    assert params == bridge.cell_baseline_params(
        scale_m=config.RASTER_SCAN_SCALE_M,
        polygon_latlng=_study_area.STUDY_AREA_POLYGON_LATLNG,
    )
    monkeypatch.setattr(config, "RASTER_SCAN_SCALE_M", 100)
    assert baseline_store.live_cell_preprocessing_params()["scale_m"] == 100


def test_cell_and_site_signatures_differ():
    assert _live_cell_signature() != logic.preprocessing_signature(bridge.preprocessing_params())


def test_bridge_re_exports_the_cell_builder():
    assert callable(bridge.build_cell_baseline)
    assert callable(bridge.cell_baseline_params)
    assert "build_cell_baseline" in bridge.__all__ and "cell_baseline_params" in bridge.__all__


def test_manifest_level_b_is_plain_json(root):
    path, _, _ = _write(root)
    on_disk = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    assert on_disk["level_b"]["seasons"][SEASON]["file"] == "cells_m10.npz"
