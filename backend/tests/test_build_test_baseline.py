"""The TEST-baseline builder (``scripts/build_test_baseline.py``), offline.

``fetch_history`` is always a fake that returns synthetic rows, so no test here
reaches Google Earth Engine. The script file is loaded by path because
``scripts/`` is not a package.
"""

from __future__ import annotations

import importlib.util
import json
import math
from datetime import date, timedelta
from pathlib import Path

import pytest

from src import _detection
from src.baseline_store import read_artifact

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "build_test_baseline.py"

_spec = importlib.util.spec_from_file_location("build_test_baseline_under_test", _SCRIPT)
builder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(builder)

baseline = _detection.baseline_logic

BUILT_ON = date(2026, 10, 9)
FLOOR = _detection.SIGNAL_ANOMALY_MIN_INDEPENDENT_DATES

SITES = [
    {"site_id": "alpha", "name": "Alpha", "lat": 13.0, "lng": 100.0},
    {"site_id": "beta", "name": "Beta", "lat": 12.0, "lng": 101.0},
]


def _row(day: date, i: int = 0) -> dict:
    return {
        "acquisition_date": day.isoformat(),
        "ndci": 0.05 + 0.04 * math.sin(i / 3.0),
        "cloud_fraction": 0.0,
        "scene_id": f"scene-{day.isoformat()}",
        # Fields a real history row never has; the artefact must not keep them.
        "location_id": "ignored",
        "extra_junk": i,
    }


def _every_other_day(start: date, days: int) -> list[dict]:
    return [_row(start + timedelta(days=2 * i), i) for i in range(days // 2)]


def _rich_rows() -> list[dict]:
    """Two years, one date every other day: ~30 dates per month, ~90 per season."""
    return _every_other_day(date(2022, 1, 1), 730)


def _rows_per_month(overrides: dict[int, int], default: int = 11) -> list[dict]:
    """One year of rows: ``default`` dates in each month unless overridden."""
    return [
        _row(date(2023, month, day), month * 100 + day)
        for month in range(1, 13)
        for day in range(1, overrides.get(month, default) + 1)
    ]


def _exact_floor_rows(per_month: int | None = None) -> list[dict]:
    """One year with exactly ``per_month`` dates in each month (floor/3 by default)."""
    return _rows_per_month({}, FLOOR // 3 if per_month is None else per_month)


class FakeHistory:
    """Records its calls; serves per-site rows keyed by latitude."""

    def __init__(self, rows_by_lat: dict[float, list[dict]]):
        self.rows_by_lat = rows_by_lat
        self.calls: list[tuple] = []

    def __call__(self, lat, lng, start, end):
        self.calls.append((lat, lng, start, end))
        return [dict(r) for r in self.rows_by_lat[lat]]


def _rich_fetch() -> FakeHistory:
    return FakeHistory({13.0: _rich_rows(), 12.0: _rich_rows()[:-40]})


def _build(root, fetch=None, **overrides):
    kwargs = dict(
        start="2017-03-28",
        end="2026-10-10",
        built_on=BUILT_ON,
        fetch_history=fetch or _rich_fetch(),
        git_sha="abc1234",
        root=root,
    )
    kwargs.update(overrides)
    return builder.build(SITES, **kwargs)


# --------------------------------------------------------------------------
# build(): the artefact
# --------------------------------------------------------------------------


def test_build_fetches_every_site_over_the_requested_window(tmp_path):
    fetch = _rich_fetch()
    _build(tmp_path, fetch)
    assert fetch.calls == [
        (13.0, 100.0, "2017-03-28", "2026-10-10"),
        (12.0, 101.0, "2017-03-28", "2026-10-10"),
    ]


def test_manifest_declares_a_test_baseline_with_the_live_signature(tmp_path):
    path = _build(tmp_path)
    manifest, _ = read_artifact(path)

    params = _detection.preprocessing_params()
    signature = baseline.preprocessing_signature(params)
    assert manifest["baseline_kind"] == "test"
    assert manifest["preprocessing_signature"] == signature
    assert manifest["preprocessing_params"] == params
    assert manifest["baseline_version"] == f"TEST-20261009-{signature[:8]}"
    assert path.name == manifest["baseline_version"]
    assert manifest["builder_git_sha"] == "abc1234"
    assert manifest["season_rule"] == baseline.SEASON_RULE
    assert manifest["signal_anomaly"]["status"] == "active"
    assert manifest["built_at"].startswith("20")  # an ISO timestamp, not blank


def test_manifest_passes_validate_manifest(tmp_path):
    manifest, _ = read_artifact(_build(tmp_path))
    baseline.validate_manifest(
        manifest,
        live_signature=baseline.preprocessing_signature(_detection.preprocessing_params()),
        today=BUILT_ON,
    )


def test_history_window_is_the_first_and_last_row_not_the_requested_window(tmp_path):
    fetch = _rich_fetch()
    manifest, _ = read_artifact(_build(tmp_path, fetch))
    dates = sorted(r["acquisition_date"] for rows in fetch.rows_by_lat.values() for r in rows)
    assert manifest["history_start"] == dates[0] == "2022-01-01"
    assert manifest["history_end"] == dates[-1]
    assert manifest["history_end"] != "2026-10-10"


def test_location_entries_carry_the_computed_counts(tmp_path):
    fetch = _rich_fetch()
    manifest, _ = read_artifact(_build(tmp_path, fetch))

    assert set(manifest["locations"]) == {"alpha", "beta"}
    for site_id, lat in (("alpha", 13.0), ("beta", 12.0)):
        rows = fetch.rows_by_lat[lat]
        dates = sorted({r["acquisition_date"] for r in rows})
        info = manifest["locations"][site_id]
        assert info["n_dates"] == len(dates)
        assert info["first"] == dates[0]
        assert info["last"] == dates[-1]
        expected_min = min(
            len({d for d in dates if int(d[5:7]) in baseline.season_months(month)})
            for month in range(1, 13)
        )
        assert info["min_season_dates"] == expected_min >= FLOOR


def test_declared_minimum_is_the_weakest_season_over_all_sites(tmp_path):
    rich = _rich_rows()
    # A thinner but sufficient site: 31 distinct dates in every season.
    thin = _exact_floor_rows(per_month=11)
    fetch = FakeHistory({13.0: rich, 12.0: thin})
    manifest, _ = read_artifact(_build(tmp_path, fetch))

    assert manifest["locations"]["beta"]["min_season_dates"] == 33
    assert manifest["signal_anomaly"]["minimum_independent_dates"] == 33
    assert manifest["signal_anomaly"]["minimum_independent_dates"] == min(
        info["min_season_dates"] for info in manifest["locations"].values()
    )


def test_rows_from_several_tiles_on_one_date_count_once(tmp_path):
    rows = _exact_floor_rows()
    doubled = rows + [dict(r, scene_id=r["scene_id"] + "-b") for r in rows]
    fetch = FakeHistory({13.0: doubled, 12.0: doubled})
    manifest, _ = read_artifact(_build(tmp_path, fetch))
    assert manifest["locations"]["alpha"]["n_dates"] == 12 * (FLOOR // 3)
    assert manifest["locations"]["alpha"]["min_season_dates"] == FLOOR


def test_sites_json_has_every_site_with_only_the_four_row_fields(tmp_path):
    fetch = _rich_fetch()
    path = _build(tmp_path, fetch)
    on_disk = json.loads((path / "sites.json").read_text(encoding="utf-8"))

    assert list(on_disk) == ["rows"]
    assert set(on_disk["rows"]) == {"alpha", "beta"}
    for site_id, lat in (("alpha", 13.0), ("beta", 12.0)):
        stored = on_disk["rows"][site_id]
        assert len(stored) == len(fetch.rows_by_lat[lat])
        for row in stored:
            assert set(row) == {"acquisition_date", "ndci", "cloud_fraction", "scene_id"}
        assert [r["acquisition_date"] for r in stored] == sorted(
            r["acquisition_date"] for r in stored
        )


def test_self_check_is_the_sum_of_the_per_location_checks(tmp_path):
    fetch = _rich_fetch()
    manifest, rows_by_site = read_artifact(_build(tmp_path, fetch))
    check = manifest["self_check"]

    assert set(check["per_location"]) == {"alpha", "beta"}
    n_rows = sum(len(rows) for rows in rows_by_site.values())
    assert check["total"]["assessed"] + check["total"]["no_assessment"] == n_rows

    for key in ("assessed", "watch", "high", "no_assessment"):
        assert check["total"][key] == sum(
            check["per_location"][s]["total"][key] for s in ("alpha", "beta")
        )
    season = baseline.season_key(7)
    for key in ("assessed", "watch", "high", "no_assessment"):
        assert check["by_season"][season][key] == sum(
            check["per_location"][s]["by_season"][season][key] for s in ("alpha", "beta")
        )
    # Sum of every season's reasons is the total's reasons.
    merged: dict[str, int] = {}
    for counts in check["by_season"].values():
        for reason, n in counts["reasons"].items():
            merged[reason] = merged.get(reason, 0) + n
    assert merged == check["total"]["reasons"]

    # And a per-location entry is exactly what baseline.self_check says.
    signature = manifest["preprocessing_signature"]
    assert check["per_location"]["alpha"] == baseline.self_check(
        rows_by_site["alpha"], location_id="alpha", preprocessing_signature=signature
    )


def test_exactly_the_floor_is_accepted(tmp_path):
    fetch = FakeHistory({13.0: _exact_floor_rows(), 12.0: _exact_floor_rows()})
    manifest, _ = read_artifact(_build(tmp_path, fetch))
    assert manifest["signal_anomaly"]["minimum_independent_dates"] == FLOOR


# --------------------------------------------------------------------------
# build(): refusal
# --------------------------------------------------------------------------


def test_one_short_season_refuses_and_writes_nothing(tmp_path):
    root = tmp_path / "baselines"
    # beta has 11 dates in every month except June, July and August, which
    # have 3 each: the July window (Jun+Jul+Aug) holds only 9 distinct dates.
    sparse = _rows_per_month({6: 3, 7: 3, 8: 3})
    fetch = FakeHistory({13.0: _rich_rows(), 12.0: sparse})

    with pytest.raises(builder.BuilderRefused) as excinfo:
        _build(root, fetch)

    message = str(excinfo.value)
    assert message.startswith(f"beta: m07+-1 has 9 < {FLOOR} independent dates")
    assert "alpha" not in message
    assert not root.exists()


def test_refusal_names_the_weakest_season_and_its_count(tmp_path):
    rows = _exact_floor_rows()
    rows = [r for r in rows if r["acquisition_date"] != "2023-03-01"]  # 29 in m02, m03, m04
    fetch = FakeHistory({13.0: rows, 12.0: _exact_floor_rows()})
    with pytest.raises(builder.BuilderRefused) as excinfo:
        _build(tmp_path / "out", fetch)
    assert str(excinfo.value).startswith(f"alpha: m02+-1 has {FLOOR - 1} < {FLOOR} independent dates")


def test_every_short_site_is_named(tmp_path):
    thin = _exact_floor_rows(per_month=5)
    fetch = FakeHistory({13.0: thin, 12.0: thin})
    with pytest.raises(builder.BuilderRefused) as excinfo:
        _build(tmp_path / "out", fetch)
    assert "alpha" in str(excinfo.value) and "beta" in str(excinfo.value)
    assert not (tmp_path / "out").exists()


def test_a_site_with_no_rows_is_refused(tmp_path):
    fetch = FakeHistory({13.0: _rich_rows(), 12.0: []})
    with pytest.raises(builder.BuilderRefused, match="beta"):
        _build(tmp_path / "out", fetch)
    assert not (tmp_path / "out").exists()


def test_no_sites_is_refused(tmp_path):
    with pytest.raises(builder.BuilderRefused):
        builder.build(
            [], start="2017-03-28", end="2026-10-10", built_on=BUILT_ON,
            fetch_history=_rich_fetch(), git_sha=None, root=tmp_path / "out",
        )
    assert not (tmp_path / "out").exists()


# --------------------------------------------------------------------------
# main(): CLI
# --------------------------------------------------------------------------


def test_dry_run_writes_nothing_and_prints_counts(tmp_path, capsys):
    root = tmp_path / "baselines"
    code = builder.main(
        ["--dry-run", "--root", str(root), "--start", "2017-03-28", "--end", "2026-10-10"],
        fetch_history=_rich_fetch(),
        sites=SITES,
        today=BUILT_ON,
    )
    out = capsys.readouterr().out

    assert code == 0
    assert not root.exists()
    assert "alpha" in out and "beta" in out
    assert "dry run" in out.lower()
    n_alpha = len({r["acquisition_date"] for r in _rich_rows()})
    assert str(n_alpha) in out


def test_dry_run_reports_a_site_that_a_real_build_would_refuse(tmp_path, capsys):
    root = tmp_path / "baselines"
    thin = _exact_floor_rows(per_month=5)
    code = builder.main(
        ["--dry-run", "--root", str(root)],
        fetch_history=FakeHistory({13.0: thin, 12.0: _rich_rows()}),
        sites=SITES,
        today=BUILT_ON,
    )
    out = capsys.readouterr().out
    assert code == 2
    assert not root.exists()
    assert "alpha" in out and "below" in out.lower()


def test_main_builds_and_prints_the_artefact_path(tmp_path, capsys):
    root = tmp_path / "baselines"
    code = builder.main(
        ["--root", str(root)],
        fetch_history=_rich_fetch(),
        sites=SITES,
        today=BUILT_ON,
    )
    out = capsys.readouterr().out
    assert code == 0
    [artefact] = list(root.iterdir())
    assert artefact.name.startswith("TEST-20261009-")
    assert str(artefact) in out
    assert (artefact / "manifest.json").is_file() and (artefact / "sites.json").is_file()


def test_main_end_defaults_to_the_day_after_today(tmp_path):
    fetch = _rich_fetch()
    builder.main(["--root", str(tmp_path)], fetch_history=fetch, sites=SITES, today=BUILT_ON)
    assert {(c[2], c[3]) for c in fetch.calls} == {
        (_detection.SENTINEL2_SR_ARCHIVE_START_DATE, "2026-10-10")
    }


def test_main_refusal_exits_nonzero_and_writes_nothing(tmp_path, capsys):
    root = tmp_path / "baselines"
    thin = _exact_floor_rows(per_month=5)
    code = builder.main(
        ["--root", str(root)],
        fetch_history=FakeHistory({13.0: thin, 12.0: thin}),
        sites=SITES,
        today=BUILT_ON,
    )
    captured = capsys.readouterr()
    assert code == 2
    assert not root.exists()
    assert "refus" in captured.err.lower()
    assert "alpha" in captured.err


# --------------------------------------------------------------------------
# An existing version is never silently rewritten
# --------------------------------------------------------------------------


def _main(root, fetch, *extra):
    return builder.main(["--root", str(root), *extra], fetch_history=fetch, sites=SITES, today=BUILT_ON)


def test_build_refuses_an_existing_version_before_fetching(tmp_path):
    path = _build(tmp_path, built_at="2026-10-09T01:00:00+00:00")
    before = (path / "manifest.json").read_text(encoding="utf-8")
    fetch = _rich_fetch()

    with pytest.raises(builder.ArtifactExists) as excinfo:
        _build(tmp_path, fetch=fetch, built_at="2026-10-09T02:00:00+00:00")

    assert excinfo.value.path == path
    assert fetch.calls == []  # refused before any history was fetched
    assert (path / "manifest.json").read_text(encoding="utf-8") == before


def test_build_with_replace_rewrites_the_version(tmp_path):
    path = _build(tmp_path, built_at="2026-10-09T01:00:00+00:00")
    again = _build(tmp_path, built_at="2026-10-09T02:00:00+00:00", replace=True)
    assert again == path
    assert read_artifact(path)[0]["built_at"] == "2026-10-09T02:00:00+00:00"
    assert [p.name for p in tmp_path.iterdir()] == [path.name]


def test_main_refuses_an_existing_version_and_names_replace(tmp_path, capsys):
    root = tmp_path / "baselines"
    assert _main(root, _rich_fetch()) == 0
    [artefact] = list(root.iterdir())
    before = {name: (artefact / name).read_text(encoding="utf-8") for name in ("manifest.json", "sites.json")}
    capsys.readouterr()

    fetch = _rich_fetch()
    code = _main(root, fetch)
    err = capsys.readouterr().err

    assert code == 2
    assert fetch.calls == []
    assert artefact.name in err
    assert "--replace" in err
    assert "refused" in err.lower()
    assert {name: (artefact / name).read_text(encoding="utf-8") for name in before} == before


def test_main_replace_overwrites_the_existing_version(tmp_path, capsys):
    root = tmp_path / "baselines"
    assert _main(root, _rich_fetch()) == 0
    [artefact] = list(root.iterdir())

    # Different history this time, so the rewrite is visible.
    fetch = FakeHistory({13.0: _rich_rows()[:-20], 12.0: _rich_rows()[:-40]})
    code = _main(root, fetch, "--replace")

    assert code == 0
    assert fetch.calls  # it did fetch and build
    assert [p.name for p in root.iterdir()] == [artefact.name]
    assert len(read_artifact(artefact)[1]["alpha"]) == len(_rich_rows()) - 20


def test_dry_run_is_unaffected_by_an_existing_version(tmp_path, capsys):
    root = tmp_path / "baselines"
    assert _main(root, _rich_fetch()) == 0
    [artefact] = list(root.iterdir())
    before = (artefact / "sites.json").read_text(encoding="utf-8")
    capsys.readouterr()

    fetch = _rich_fetch()
    code = _main(root, fetch, "--dry-run")

    assert code == 0
    assert fetch.calls  # counts were fetched and printed as usual
    assert "dry run" in capsys.readouterr().out.lower()
    assert (artefact / "sites.json").read_text(encoding="utf-8") == before


def test_git_sha_is_none_when_git_fails(monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("no git")

    monkeypatch.setattr(builder.subprocess, "run", boom)
    assert builder.current_git_sha() is None


def test_default_sites_are_the_monitored_grid():
    from src.grid import MONITORED_GRID

    assert builder.DEFAULT_SITES is MONITORED_GRID


# ==========================================================================
# Level B (per-cell baseline): --level AB / B
# ==========================================================================

import numpy as np  # noqa: E402

from src import _study_area, config  # noqa: E402
from src.baseline_store import read_cells_file  # noqa: E402

DEG = 200 / 111319.49079327357
CELL_END = "2026-09-24"  # BUILT_ON - 15 days
GRID_DTYPE = [
    ("median", "<f4"), ("mad", "<f4"), ("n", "<i4"), ("longitude", "<f8"), ("latitude", "<f8"),
]


class FakeCells:
    """Stands in for the Earth Engine per-cell fetch; records its calls.

    Every season gets a 4 x 5 grid of cells on the production pixel grid
    (centres at (k + 1/2) cells from 0 deg) plus one masked cell (n = 0).
    ``low_n_by_month`` makes that many cells of a season fall under the
    30-date floor; ``offset_cells`` shifts the whole grid off the pixel grid.
    """

    def __init__(self, low_n_by_month=None, offset_cells=0.0):
        self.low_n_by_month = low_n_by_month or {}
        self.offset_cells = offset_cells
        self.calls = []

    def dates(self, months, start, end):
        out = [
            f"{year}-{month:02d}-{day:02d}"
            for year in range(2018, 2026) for month in months for day in (1, 10, 20)
        ]
        return sorted(d for d in out if start <= d < end)

    def __call__(self, polygon, months, start, end, scale_m):
        self.calls.append((polygon, months, start, end, scale_m))
        target = months[1]
        g = np.zeros((4, 6), dtype=GRID_DTYPE)
        low = self.low_n_by_month.get(target, 1)
        for i in range(4):
            for j in range(6):
                k = i * 6 + j
                if j == 5:
                    continue  # masked cell: zeros everywhere, n = 0
                n = 10 if k < low else 40 + target
                g[i, j] = (
                    0.02 + 0.001 * k, 0.01 + 0.0005 * target, n,
                    (55800 + j + 0.5 + self.offset_cells) * DEG,
                    (7003 - i + 0.5) * DEG,
                )
        return g, self.dates(months, start, end)


def _build_ab(root, cells=None, fetch=None, **overrides):
    kwargs = dict(level="AB", fetch_cells=cells or FakeCells(), cell_end=CELL_END)
    kwargs.update(overrides)
    return _build(root, fetch, **kwargs)


def _live_cell_signature():
    from src.baseline_store import live_cell_preprocessing_params

    return baseline.preprocessing_signature(live_cell_preprocessing_params())


def test_level_ab_writes_twelve_season_files_into_the_same_version(tmp_path):
    cells = FakeCells()
    path = _build_ab(tmp_path, cells)
    names = sorted(p.name for p in path.iterdir())
    assert names == sorted(
        ["manifest.json", "sites.json", *(baseline.cells_file_name(m) for m in range(1, 13))]
    )
    manifest, _ = read_artifact(path)
    assert path.name == manifest["baseline_version"]
    # Level A is the same as a plain build's.
    assert manifest["preprocessing_signature"] == baseline.preprocessing_signature(
        _detection.preprocessing_params()
    )


def test_level_b_fetches_twelve_seasons_in_order(tmp_path):
    cells = FakeCells()
    _build_ab(tmp_path, cells)
    assert [c[1] for c in cells.calls] == [baseline.season_months(m) for m in range(1, 13)]
    assert {c[0] for c in cells.calls} == {tuple(_study_area.STUDY_AREA_POLYGON_LATLNG)}
    assert {(c[2], c[3], c[4]) for c in cells.calls} == {
        ("2017-03-28", CELL_END, config.RASTER_SCAN_SCALE_M)
    }


def test_level_b_manifest_block(tmp_path):
    path = _build_ab(tmp_path)
    manifest, _ = read_artifact(path)
    block = manifest["level_b"]

    assert block["scale_m"] == config.RASTER_SCAN_SCALE_M
    assert block["cell_preprocessing_signature"] == _live_cell_signature()
    assert block["cell_preprocessing_signature"] != manifest["preprocessing_signature"]
    assert block["query_end_exclusive"] == CELL_END
    assert block["history_end"] == "2026-09-23"
    assert block["history_start"] == "2018-01-01"
    assert set(block["seasons"]) == {baseline.season_key(m) for m in range(1, 13)}
    oct_season = block["seasons"]["m10+-1"]
    assert oct_season["file"] == "cells_m10.npz"
    assert oct_season["months"] == [9, 10, 11]
    assert oct_season["cells"] == 20  # the masked cell is not stored
    assert oct_season["cells_n_ge_floor"] == 19
    assert oct_season["n_min"] == 10 and oct_season["n_max"] == 50
    assert oct_season["n_dates"] == len(FakeCells().dates((9, 10, 11), "2017-03-28", CELL_END))
    for key in ("mad_p05", "mad_p50", "mad_p95"):
        assert oct_season[key] == pytest.approx(0.015)

    baseline.validate_manifest(
        manifest,
        live_signature=baseline.preprocessing_signature(_detection.preprocessing_params()),
        today=BUILT_ON,
        live_cell_signature=_live_cell_signature(),
    )


def test_cells_files_hold_what_the_builder_computed(tmp_path):
    path = _build_ab(tmp_path)
    expected = _detection.build_cell_baseline(
        _study_area.STUDY_AREA_POLYGON_LATLNG, (9, 10, 11), "2017-03-28", CELL_END,
        config.RASTER_SCAN_SCALE_M, _fetch=FakeCells(),
    )
    got = read_cells_file(path / "cells_m10.npz")
    for key in ("lat", "lng", "median", "mad", "n"):
        np.testing.assert_array_equal(got[key], expected[key])
        assert got[key].dtype == expected[key].dtype


def test_a_season_under_ninety_percent_refuses_everything(tmp_path):
    root = tmp_path / "baselines"
    cells = FakeCells(low_n_by_month={7: 3})  # 17 of 20 cells = 85 %
    with pytest.raises(builder.BuilderRefused) as excinfo:
        _build_ab(root, cells)
    message = str(excinfo.value)
    assert "m07+-1" in message
    assert "85.0%" in message
    assert "90%" in message
    assert not root.exists()
    # Refused at the failing season: the later seasons were never fetched.
    assert [c[1][1] for c in cells.calls] == list(range(1, 8))


def test_exactly_ninety_percent_is_accepted(tmp_path):
    cells = FakeCells(low_n_by_month={m: 2 for m in range(1, 13)})  # 18 of 20 cells
    manifest, _ = read_artifact(_build_ab(tmp_path, cells))
    assert manifest["level_b"]["seasons"]["m01+-1"]["share_n_ge_floor"] == 0.9


def test_cells_off_the_production_pixel_grid_are_refused(tmp_path):
    root = tmp_path / "baselines"
    with pytest.raises(builder.BuilderRefused, match="pixel grid"):
        _build_ab(root, FakeCells(offset_cells=0.5))
    assert not root.exists()


def test_level_a_refusal_comes_before_any_cell_fetch(tmp_path):
    root = tmp_path / "baselines"
    thin = _exact_floor_rows(per_month=5)
    cells = FakeCells()
    with pytest.raises(builder.BuilderRefused, match="alpha"):
        _build_ab(root, cells, FakeHistory({13.0: thin, 12.0: thin}))
    assert cells.calls == []
    assert not root.exists()


def test_level_ab_refuses_an_existing_version_before_fetching(tmp_path):
    path = _build(tmp_path)  # Level A only
    cells = FakeCells()
    fetch = _rich_fetch()
    with pytest.raises(builder.ArtifactExists):
        _build_ab(tmp_path, cells, fetch)
    assert cells.calls == [] and fetch.calls == []
    assert "level_b" not in read_artifact(path)[0]


def test_unknown_level_is_refused(tmp_path):
    with pytest.raises(ValueError):
        _build(tmp_path, level="C")


# --------------------------------------------------------------------------
# main(): --level
# --------------------------------------------------------------------------


def _main_b(root, *extra, cells=None, fetch=None):
    return builder.main(
        ["--root", str(root), *extra],
        fetch_history=fetch or _rich_fetch(),
        fetch_cells=cells or FakeCells(),
        sites=SITES,
        today=BUILT_ON,
    )


def test_main_default_level_is_a_and_never_fetches_cells(tmp_path):
    cells = FakeCells()
    assert _main_b(tmp_path, cells=cells) == 0
    assert cells.calls == []
    [artefact] = list(tmp_path.iterdir())
    assert "level_b" not in read_artifact(artefact)[0]


def test_main_level_ab_defaults_the_cell_end_to_fifteen_days_ago(tmp_path, capsys):
    cells = FakeCells()
    fetch = _rich_fetch()
    assert _main_b(tmp_path, "--level", "AB", cells=cells, fetch=fetch) == 0
    assert {c[3] for c in cells.calls} == {(BUILT_ON - timedelta(days=15)).isoformat()}
    # Level A keeps its own default end (tomorrow).
    assert {c[3] for c in fetch.calls} == {"2026-10-10"}
    [artefact] = list(tmp_path.iterdir())
    assert read_artifact(artefact)[0]["level_b"]["history_end"] == "2026-09-23"
    out = capsys.readouterr().out
    assert "m10+-1" in out and "Level B" in out


def test_main_cell_end_flag(tmp_path):
    cells = FakeCells()
    assert _main_b(tmp_path, "--level", "AB", "--cell-end", "2026-06-01", cells=cells) == 0
    assert {c[3] for c in cells.calls} == {"2026-06-01"}


def test_main_level_ab_refusal_exits_two_and_writes_nothing(tmp_path, capsys):
    root = tmp_path / "baselines"
    code = _main_b(root, "--level", "AB", cells=FakeCells(low_n_by_month={3: 5}))
    err = capsys.readouterr().err
    assert code == 2
    assert not root.exists()
    assert "m03+-1" in err and "refused" in err.lower()


def test_main_level_ab_dry_run_prints_every_season_and_writes_nothing(tmp_path, capsys):
    root = tmp_path / "baselines"
    cells = FakeCells(low_n_by_month={3: 5})
    code = _main_b(root, "--level", "AB", "--dry-run", cells=cells)
    out = capsys.readouterr().out
    assert code == 2  # a real build would be refused
    assert not root.exists()
    assert len(cells.calls) == 12  # a dry run looks at every season
    for month in range(1, 13):
        assert baseline.season_key(month) in out
    assert "m03+-1" in out.split("refused")[-1]


def test_main_level_b_needs_an_existing_level_a_artefact(tmp_path, capsys):
    root = tmp_path / "baselines"
    cells = FakeCells()
    code = _main_b(root, "--level", "B", "--replace", cells=cells)
    err = capsys.readouterr().err
    assert code == 2
    assert cells.calls == []
    assert "--level AB" in err
    assert not root.exists() or list(root.iterdir()) == []


def test_main_level_b_without_replace_is_refused_before_fetching(tmp_path, capsys):
    root = tmp_path / "baselines"
    assert _main_b(root) == 0
    capsys.readouterr()
    cells = FakeCells()
    code = _main_b(root, "--level", "B", cells=cells)
    err = capsys.readouterr().err
    assert code == 2
    assert cells.calls == []
    assert "--replace" in err


def test_main_level_b_adds_cells_and_keeps_level_a_unchanged(tmp_path):
    root = tmp_path / "baselines"
    assert _main_b(root) == 0
    [artefact] = list(root.iterdir())
    manifest_before, _ = read_artifact(artefact)
    sites_before = (artefact / "sites.json").read_bytes()

    fetch = _rich_fetch()
    cells = FakeCells()
    assert _main_b(root, "--level", "B", "--replace", cells=cells, fetch=fetch) == 0

    assert fetch.calls == []  # Level A is carried over, not refetched
    assert len(cells.calls) == 12
    assert [p.name for p in root.iterdir()] == [artefact.name]
    assert (artefact / "sites.json").read_bytes() == sites_before
    manifest_after, _ = read_artifact(artefact)
    level_b = manifest_after.pop("level_b")
    assert manifest_after == manifest_before
    assert set(level_b["seasons"]) == {baseline.season_key(m) for m in range(1, 13)}
    assert (artefact / "cells_m01.npz").is_file()
