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


def test_git_sha_is_none_when_git_fails(monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("no git")

    monkeypatch.setattr(builder.subprocess, "run", boom)
    assert builder.current_git_sha() is None


def test_default_sites_are_the_monitored_grid():
    from src.grid import MONITORED_GRID

    assert builder.DEFAULT_SITES is MONITORED_GRID
