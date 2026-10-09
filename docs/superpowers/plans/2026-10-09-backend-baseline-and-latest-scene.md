# TEST Baseline, Latest-Scene Policy, Highlights and /methods — Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the data/backend half of the two approved specs: a TEST seasonal baseline for the 7 monitoring sites (built from GEE history, off by default), a latest-scene policy that refreshes the raster and sites as soon as a newer acquisition passes the cloud criterion, a highlights endpoint (anomaly pins + highest-NDCI pins), and a `/methods` endpoint.

**Architecture:** Pure, unit-tested logic lives in `detection/src/baseline.py` (season, signature, manifest, self-check, assessment) and small pure helpers beside the existing raster code; GEE access sits behind one narrow seam per module so tests never touch the network. The backend reads a baseline artefact from `backend/data/baselines/<version>/` only when `BASELINE_MODE=test`; the existing gate predicate `_signal_anomaly_active` is reused unchanged on the manifest's declarations. `risk_evaluation_active()` stays false, so `risk_level` is always null.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy/SQLite, earthengine-api, numpy, PyYAML, pytest. Three venvs are not present: run all suites with `backend/venv/bin/python` from each project directory.

**Specs:**
- `docs/superpowers/specs/2026-10-09-test-baseline-and-latest-scene-design.md` (primary)
- `docs/superpowers/specs/2026-10-09-academic-dashboard-design.md` (§4.6 pins, §6 `/methods`, §6.1 highlights)

The frontend is a separate plan, written after this one lands (it depends on these API shapes).

## Global Constraints

- Physics-based statistics only; no ML (CLAUDE.md §0/§1). Do not touch `backend/ensemble_service.py`, `train_dual_models.py`, `forecast_service.py`, `backend/models/*`.
- Truth boundary: never present baseline output as "risk"; `risk_level`/`risk_evaluation_active()` stay null/false. Anomaly vocabulary is `normal | watch | high` + `None` with a reason; Thai labels already in `signal_anomaly.py`. Never loosen the floors: 30 independent dates, ≤ 14-day-old imagery, z boundaries 2 and 3, MAD scale 1.4826.
- `BASELINE_MODE` default is off (unset/`off`); only the exact value `test` enables it. With it off, every response is byte-for-byte what it is today for existing fields.
- Every new module has a docstring stating data source + limitations (CLAUDE.md §5). Config via env vars + `.env.example` only; no secrets.
- No live GEE in tests (mock at the seam). Live checks are opt-in with `--live-gee` and marker `live_gee`.
- Cross-project imports use the existing bridges (CLAUDE.md §8): `data-pipeline/src/__init__.py` → `detection/src/_data_pipeline.py` → `backend/src/_detection.py`. Add re-exports there; never `sys.path`-import a sibling project's `src` directly in production code.
- The working tree holds uncommitted work of the user in many files. Read a file's current content before editing, keep edits local, never reformat or revert, and stage only the files a task names. Subagent commits are denied by the harness: implementers leave changes uncommitted and the controller commits (include a `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` trailer and `Claude-Session: https://claude.ai/code/session_01PTmXbZHuaq2gQcPCx9uDuf`).
- Baselines: `backend/data/` is gitignored; artefacts are not committed.
- Suites (baseline before this plan: backend 277 passed/2 skipped; data-pipeline 128; detection 84):
  `cd backend && ./venv/bin/python -m pytest tests -q --ignore=tests/test_ensemble_service.py --ignore=tests/test_forecast_engine.py --ignore=tests/test_realistic_scenarios.py`
  `cd data-pipeline && ../backend/venv/bin/python -m pytest tests -q`
  `cd detection && ../backend/venv/bin/python -m pytest tests -q`
- GEE needs `EE_PROJECT_ID`; for live runs export it from `data-pipeline/.env` (`grep '^EE_PROJECT_ID=' data-pipeline/.env`).

## Review Focus

- A baseline built from data **after** the observation (leakage): an observation on or before `history_end` must only see strictly earlier history. (T1)
- Preprocessing changes silently reusing an old baseline: any change to the live signature must yield `incompatible_preprocessing`/invalid manifest, never an assessment. (T1, T4)
- Test mode on with a missing/stale/corrupt artefact: anomaly fields stay null with a stated reason; app still starts. (T4)
- Gate looseness: a hand-edited manifest declaring 5 dates or 90-day imagery must be rejected by the same predicate. (T4)
- A rejected-cloud scene consuming the trigger (so the next good scene is ignored), or an errored scan marking its date used. (T8)
- "No pins" being indistinguishable from "nothing assessed". (T10)

---

## Task 1: Baseline logic module (`detection/src/baseline.py`)

**Files:**
- Create: `detection/src/baseline.py`
- Test: `detection/tests/test_baseline.py`

**Interfaces:**
- Consumes: `signal_anomaly.assess_signal_anomaly`, `signal_anomaly.MIN_INDEPENDENT_DATES`, `MAX_OBSERVATION_AGE_DAYS`, `signal_anomaly._config`-compatible config dict (from `config.yaml`'s `signal_anomaly`).
- Produces (exact names; later tasks import these):
  - `SEASON_RULE = "calendar-month window, target month +/- 1 (cyclic)"`
  - `season_months(month: int) -> tuple[int, int, int]` — `(m-1, m, m+1)` cyclic in 1..12.
  - `season_key(month: int) -> str` — `f"m{month:02d}+-1"` (ASCII `+-1`, no `±`, so it is safe in keys/filenames).
  - `preprocessing_signature(params: dict) -> str` — first 16 hex chars of SHA-256 over `json.dumps(params, sort_keys=True, separators=(",", ":"), ensure_ascii=True)`.
  - `scoped_history(rows: list[dict], location_id: str, target_month: int, preprocessing_signature: str) -> list[dict]` — rows (`{acquisition_date, ndci}` plus optional extras) whose acquisition month ∈ `season_months(target_month)`, returned as new dicts with `location_id`, `season_key`, `preprocessing_signature` set (inputs not mutated).
  - `assess_site(rows, *, location_id, current_ndci, actual_date, target_date, preprocessing_signature, config=None) -> dict` — calls `assess_signal_anomaly` with `season_key(month of target_date)` and `scoped_history`; returns its dict unchanged.
  - `self_check(rows, *, location_id, preprocessing_signature, config=None) -> dict` — for each season month 1..12: replays every history row dated in that month's own window through `assess_site` using `target_date = actual_date = row date` and rows strictly earlier only (the function already enforces this); returns `{"by_season": {season_key: {"assessed": int, "watch": int, "high": int, "no_assessment": int, "reasons": {reason: count}}}, "total": {...same keys}}`. `assessed` counts rows with `level is not None`.
  - `build_manifest(*, baseline_version, built_at, history_start, history_end, preprocessing_signature, preprocessing_params, locations: dict[str, dict], self_check: dict, builder_git_sha: str | None) -> dict` where `locations[id]` is `{"n_dates": int, "min_season_dates": int, "first": str, "last": str}`. Manifest keys: `baseline_kind` (`"test"`), `baseline_version`, `built_at`, `history_start`, `history_end`, `season_rule`, `preprocessing_signature`, `preprocessing_params`, `locations`, `self_check`, `builder_git_sha`, and a `signal_anomaly` declaration dict shaped like the config gate input: `{"status": "active", "minimum_independent_dates": <min over locations of min_season_dates>, "max_observation_age_days": 14, "location_specific": True, "season_specific": True, "history_before_target_only": True, "baseline_version": <version>, "preprocessing_signature": <sig>, "mad_scale": 1.4826, "watch_at_z": 2.0, "high_at_z": 3.0}`.
  - `class BaselineInvalid(ValueError)`; `validate_manifest(manifest: dict, *, live_signature: str, today: date) -> None` raises `BaselineInvalid("<reason>")` with reason ∈ `not_test_kind`, `signature_mismatch`, `history_in_future`, `missing_field:<name>`, `below_floor`. `below_floor` when `signal_anomaly.minimum_independent_dates < MIN_INDEPENDENT_DATES` or `max_observation_age_days` outside `0..MAX_OBSERVATION_AGE_DAYS`.
  - `version_for(built_on: date, signature: str) -> str` → `f"TEST-{built_on:%Y%m%d}-{signature[:8]}"`.

- [ ] **Step 1: Write the failing tests** (`detection/tests/test_baseline.py`)

```python
"""Pure-logic tests for detection/src/baseline.py (no GEE, no files)."""
from datetime import date, timedelta

import pytest

import baseline as b  # detection/src is on sys.path via the other test files' header; mirror test_signal_anomaly.py's import style


def _rows(start, n, value=0.05, step=5):
    d0 = date.fromisoformat(start)
    return [{"acquisition_date": (d0 + timedelta(days=i * step)).isoformat(), "ndci": value + (i % 7) * 0.002} for i in range(n)]


def test_season_months_cyclic():
    assert b.season_months(1) == (12, 1, 2)
    assert b.season_months(12) == (11, 12, 1)
    assert b.season_months(8) == (7, 8, 9)


def test_season_key_ascii():
    assert b.season_key(8) == "m08+-1"


def test_signature_stable_and_sensitive():
    p = {"collection": "COPERNICUS/S2_SR_HARMONIZED", "buffer_m": 30}
    assert b.preprocessing_signature(p) == b.preprocessing_signature(dict(reversed(list(p.items()))))
    assert b.preprocessing_signature(p) != b.preprocessing_signature({**p, "buffer_m": 31})
    assert len(b.preprocessing_signature(p)) == 16


def test_scoped_history_filters_month_and_sets_scope():
    rows = [{"acquisition_date": "2024-07-03", "ndci": 0.1}, {"acquisition_date": "2024-10-03", "ndci": 0.2}]
    out = b.scoped_history(rows, "x", 8, "sig")
    assert [r["acquisition_date"] for r in out] == ["2024-07-03"]
    assert out[0]["location_id"] == "x" and out[0]["season_key"] == "m08+-1" and out[0]["preprocessing_signature"] == "sig"
    assert "location_id" not in rows[0]  # input untouched


def test_assess_site_no_future_leakage():
    rows = _rows("2019-06-01", 80)  # spans many months
    # observation inside history range: only strictly earlier rows may count
    target = rows[40]["acquisition_date"]
    res = b.assess_site(rows, location_id="x", current_ndci=0.5, actual_date=target, target_date=target, preprocessing_signature="sig")
    late = b.assess_site(rows + _rows("2030-01-01", 50), location_id="x", current_ndci=0.5, actual_date=target, target_date=target, preprocessing_signature="sig")
    assert res == late  # later rows are invisible


def test_assess_site_insufficient_dates_reason():
    res = b.assess_site(_rows("2024-07-01", 5), location_id="x", current_ndci=0.1, actual_date="2024-08-20", target_date="2024-08-20", preprocessing_signature="sig")
    assert res["level"] is None and res["reason"] == "insufficient_independent_dates"


def test_assess_site_flags_outlier_and_respects_floor():
    rows = _rows("2018-01-01", 400, step=7)
    res = b.assess_site(rows, location_id="x", current_ndci=0.9, actual_date="2026-01-10", target_date="2026-01-12", preprocessing_signature="sig")
    assert res["level"] == "high" and res["robust_z"] >= 3


def test_self_check_shape_and_counts():
    rows = _rows("2018-01-01", 400, step=7)
    sc = b.self_check(rows, location_id="x", preprocessing_signature="sig")
    assert set(sc) == {"by_season", "total"}
    t = sc["total"]
    assert t["assessed"] + t["no_assessment"] == sum(1 for _ in rows)
    assert t["watch"] + t["high"] <= t["assessed"]


def _manifest(**over):
    m = b.build_manifest(
        baseline_version="TEST-20261009-abcd1234", built_at="2026-10-09T00:00:00Z", history_start="2017-12-13", history_end="2026-10-07",
        preprocessing_signature="abcd1234abcd1234", preprocessing_params={"k": 1},
        locations={"a": {"n_dates": 300, "min_season_dates": 35, "first": "2017-12-13", "last": "2026-10-07"}, "b": {"n_dates": 280, "min_season_dates": 41, "first": "2017-12-23", "last": "2026-09-29"}},
        self_check={"total": {}}, builder_git_sha="deadbee")
    m.update(over)
    return m


def test_manifest_declares_min_over_locations():
    m = _manifest()
    assert m["baseline_kind"] == "test" and m["signal_anomaly"]["minimum_independent_dates"] == 35
    b.validate_manifest(m, live_signature="abcd1234abcd1234", today=date(2026, 10, 9))


@pytest.mark.parametrize("over,reason", [
    ({"baseline_kind": "prod"}, "not_test_kind"),
    ({"history_end": "2030-01-01"}, "history_in_future"),
])
def test_validate_rejects(over, reason):
    with pytest.raises(b.BaselineInvalid, match=reason):
        b.validate_manifest(_manifest(**over), live_signature="abcd1234abcd1234", today=date(2026, 10, 9))


def test_validate_signature_mismatch():
    with pytest.raises(b.BaselineInvalid, match="signature_mismatch"):
        b.validate_manifest(_manifest(), live_signature="other", today=date(2026, 10, 9))


def test_validate_rejects_below_floor_even_if_hand_edited():
    m = _manifest()
    m["signal_anomaly"]["minimum_independent_dates"] = 5
    with pytest.raises(b.BaselineInvalid, match="below_floor"):
        b.validate_manifest(m, live_signature="abcd1234abcd1234", today=date(2026, 10, 9))
    m = _manifest()
    m["signal_anomaly"]["max_observation_age_days"] = 90
    with pytest.raises(b.BaselineInvalid, match="below_floor"):
        b.validate_manifest(m, live_signature="abcd1234abcd1234", today=date(2026, 10, 9))


def test_validate_missing_field():
    m = _manifest(); del m["season_rule"]
    with pytest.raises(b.BaselineInvalid, match="missing_field:season_rule"):
        b.validate_manifest(m, live_signature="abcd1234abcd1234", today=date(2026, 10, 9))


def test_version_for():
    assert b.version_for(date(2026, 10, 9), "abcd1234ffff0000") == "TEST-20261009-abcd1234"
```

- [ ] **Step 2: Run to verify failure.** `cd detection && ../backend/venv/bin/python -m pytest tests/test_baseline.py -q` → `ModuleNotFoundError: baseline`. (Read `detection/tests/test_signal_anomaly.py` for its import style and use the same.)
- [ ] **Step 3: Implement `detection/src/baseline.py`** per the Interfaces block, with the module docstring: *Data source: history rows supplied by a builder (data-pipeline/src/history.py); Limitations: statistical anomaly against a location's own seasonal record, TEST status, not calibrated against events, not a bloom/risk claim, thresholds provisional.* Use `signal_anomaly` constants; `assess_site` must not catch exceptions from `assess_signal_anomaly`. `validate_manifest` checks keys in this order: required top-level keys (`baseline_kind, baseline_version, built_at, history_start, history_end, season_rule, preprocessing_signature, signal_anomaly`) → `missing_field:<k>`; `baseline_kind == "test"`; `preprocessing_signature == live_signature`; `date.fromisoformat(history_end) <= today`; floors. Load the module the same way sibling modules do (loose module with its own `sys.path` header).
- [ ] **Step 4: Run tests until green; run the full detection suite** (expect 84 + new).
- [ ] **Step 5: Report** (do not commit; controller commits).

---

## Task 2: History extraction (`data-pipeline/src/history.py`)

**Files:**
- Create: `data-pipeline/src/history.py`
- Modify: `data-pipeline/src/__init__.py` (re-export `get_ndci_history`, `preprocessing_params`)
- Modify: `detection/src/_data_pipeline.py` (re-export the same two names)
- Test: `data-pipeline/tests/test_history.py`

**Interfaces:**
- Consumes: `sentinel2._cloud_flag_image`, `_water_mask_image`, `cloud_fraction_from_stats`, `band_means_from_stats`, `DEFAULT_BUFFER_M`, `DEFAULT_SCALE_M`, `DEFAULT_MAX_CLOUD_FRACTION`, `DEFAULT_CLOUD_CLASSES`, `DEFAULT_MIN_WATER_OCCURRENCE_PCT`, `BANDS`; `initialize_ee`.
- Produces:
  - `preprocessing_params() -> dict` — canonical dict from the **live constants**: `{"collection": "COPERNICUS/S2_SR_HARMONIZED", "bands": list(BANDS), "cloud_classes": list(DEFAULT_CLOUD_CLASSES), "max_cloud_fraction": DEFAULT_MAX_CLOUD_FRACTION, "min_water_occurrence_pct": DEFAULT_MIN_WATER_OCCURRENCE_PCT, "buffer_m": DEFAULT_BUFFER_M, "scale_m": DEFAULT_SCALE_M, "sampling": "point-buffer-mean", "index": "ndci=(B5-B4)/(B5+B4)"}`.
  - `rows_from_stats(features: list[dict], *, max_cloud_fraction: float = DEFAULT_MAX_CLOUD_FRACTION) -> list[dict]` — pure. For each feature's `properties` (keys as `sentinel2._candidate_stats` produces: band means/counts, cloud-flag mean/count, and `t` = system:time_start ms): skip when `cloud_fraction_from_stats > max_cloud_fraction` or `band_means_from_stats` raises `NoWaterPixelsError`; else `{"acquisition_date": "YYYY-MM-DD" (UTC), "ndci": (B5-B4)/(B5+B4) from the band means, "cloud_fraction": float, "scene_id": str|None}`; one row per feature (several tiles per date allowed here; reduction to one daily median is done by `assess_signal_anomaly`); denominators of 0 skipped. Sorted by date.
  - `get_ndci_history(lat, lng, start: str, end: str, *, max_cloud_fraction=..., _fetch=None) -> list[dict]` — GEE seam: `_fetch(region_lat, region_lng, start, end) -> list[feature dict]` defaults to `_fetch_features` (module-level function doing what `scratchpad/probe_history.py` did: point buffer, `filterBounds/filterDate`, map `_candidate_stats`-equivalent, `getInfo()["features"]`); returns `rows_from_stats(_fetch(...))`. `end` exclusive like `filterDate`.

- [ ] **Step 1: Failing tests** — `rows_from_stats` with hand-built property dicts (use the real key names: read `sentinel2.band_means_from_stats`/`cloud_fraction_from_stats` and mirror `test_sentinel2_masking.py` fixtures): (a) clear scene → row with exact NDCI `(b5-b4)/(b5+b4)`; (b) cloud fraction 0.6 → skipped; (c) zero water pixels → skipped; (d) B5+B4 == 0 → skipped; (e) UTC date from ms (e.g. 1788492600000 → `2026-09-04`); (f) output sorted. `get_ndci_history` with `_fetch` stub returns the same rows and passes `start/end` through. `preprocessing_params()` changes when `sentinel2.DEFAULT_BUFFER_M` is monkeypatched (signature sensitivity).
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.** Docstring: data source Sentinel-2 SR Harmonized + JRC water mask; limits: point-buffer mean not raster sampling, cloud-masked days only, no atmospheric validation. Put `ee` calls only in `_fetch_features`.
- [ ] **Step 4: Run data-pipeline + detection suites** (the re-export must not break `detection/tests`).
- [ ] **Step 5: Report.**

---

## Task 3: Baseline builder CLI and live artefact

**Files:**
- Create: `scripts/build_test_baseline.py`
- Create: `backend/src/baseline_store.py` (artefact IO only: `write_artifact(root, manifest, rows_by_location) -> Path`, `read_artifact(path) -> tuple[dict, dict[str, list[dict]]]`, `BASELINE_ROOT = backend/data/baselines`, `latest_artifact_path(root=BASELINE_ROOT) -> Path | None` choosing the highest `baseline_version` directory that has both files)
- Test: `backend/tests/test_baseline_store.py`, `backend/tests/test_build_test_baseline.py`

**Interfaces:**
- Consumes: Task 1 (`build_manifest`, `self_check`, `preprocessing_signature`, `version_for`), Task 2 (`get_ndci_history`, `preprocessing_params`), `backend/src/grid.py::MONITORED_GRID`.
- Produces: `scripts.build_test_baseline.build(sites: list[dict], *, start: str, end: str, built_on: date, fetch_history, git_sha: str | None, root: Path) -> Path` — loops sites, calls `fetch_history(lat, lng, start, end)`, computes per-location `n_dates` (distinct dates), `min_season_dates` (min over months 1..12 of distinct dates in `season_months(m)`), `first/last`; **raises `BuilderRefused("<site_id>: <season_key> has <n> < 30 independent dates")`** before writing anything if any location/season has fewer than 30 (`signal_anomaly.MIN_INDEPENDENT_DATES`); writes the artefact (`manifest.json`, `sites.json` = `{"rows": {site_id: [rows]}}`); `main()` with args `--start` (default `2017-03-28`), `--end` (default today+1), `--root`, `--dry-run`; uses live `get_ndci_history`. `history_end` in the manifest = latest acquisition date over all rows.

- [ ] **Step 1: Failing tests** — store: write→read round-trip, `latest_artifact_path` picks the highest version and ignores dirs missing a file, returns None when empty. Builder with a fake `fetch_history` (synthetic dates, ≥ 35 per 3-month window per site): manifest fields (`baseline_kind == "test"`, version `TEST-<built_on>-<sig8>`, signature equals `preprocessing_signature(preprocessing_params())`, `minimum_independent_dates` equals the computed min), `sites.json` has every site; refusal case (one site with 10 dates in one window) raises `BuilderRefused` naming site and season and **writes nothing**; `--dry-run` writes nothing and prints counts.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.** The script runs with `backend/venv/bin/python scripts/build_test_baseline.py`; it must add repo paths itself and use the bridges for detection/data-pipeline names (import them through `backend/src/_detection.py`; add re-exports there for `baseline` (loaded as `detection_src_baseline`), `get_ndci_history`, `preprocessing_params`). `git_sha` from `git rev-parse --short HEAD` (None on failure). Confirm `.gitignore` covers `backend/data/` (add `backend/data/baselines/` if not).
- [ ] **Step 4: Run backend suite.**
- [ ] **Step 5 (live, controller runs, not the implementer): build the real artefact**: `cd backend && EE_PROJECT_ID=… ./venv/bin/python ../scripts/build_test_baseline.py` and record the manifest's counts and self-check base rates in the report. Expected ≈ 90 s.
- [ ] **Step 6: Report.**

---

## Task 4: Test-mode gate and artefact loader

**Files:**
- Modify: `backend/src/config.py` (`BASELINE_MODE` env, parsed: only the exact value `test` → `"test"`, anything else → `"off"`), `backend/.env.example`
- Create/Modify: `backend/src/baseline_store.py` (add `load_active_baseline() -> ActiveBaseline | None`, cached on `(path, mtime_ns, size)` like `scientific_status._load_config`)
- Modify: `backend/src/scientific_status.py` (`signal_anomaly_active()` and a new `baseline_status() -> dict`)
- Modify: `backend/src/_detection.py` (re-export `baseline` module as `baseline_logic` and `preprocessing_params`)
- Test: `backend/tests/test_baseline_gate.py`

**Interfaces:**
- `@dataclass(frozen=True) class ActiveBaseline: manifest: dict; rows_by_location: dict[str, list[dict]]; version: str`
- `baseline_status() -> dict` — `{"mode": "off"}` when off; else `{"mode": "test", "valid": True, "kind": "test", "version", "built_at", "history_start", "history_end", "season_rule", "min_independent_dates", "median_independent_dates", "preprocessing_signature", "base_rates": manifest["self_check"]["total"]}` or `{"mode": "test", "valid": False, "kind": "test", "reason": "<no_artifact | BaselineInvalid reason | unreadable>"}`.
- `signal_anomaly_active()`: config path unchanged; additionally `True` when `BASELINE_MODE == "test"` **and** `baseline_status()["valid"]` **and** `_signal_anomaly_active(manifest["signal_anomaly"])` (the same predicate, same floors). `risk_evaluation_active()` unchanged (still requires `risk_evaluation.active` in config) — add a test that it stays false in test mode.
- Config re-read rule: read `BASELINE_MODE` from `config` module at call time (tests monkeypatch `config.BASELINE_MODE`).

- [ ] **Step 1: Failing tests** — mode off → `signal_anomaly_active()` false even with a valid artefact present; test mode + valid fixture artefact (build one with Task 3's builder/fake fetch into `tmp_path`, point `BASELINE_ROOT` at it) → true and `baseline_status()` fields; test mode + no artefact → false, `reason == "no_artifact"`; corrupt `manifest.json` → `valid False`, app import unaffected; signature mismatch (monkeypatch `preprocessing_params`) → invalid `signature_mismatch`; hand-edited manifest with `minimum_independent_dates: 5` → invalid `below_floor`; `history_end` in the future → invalid; `risk_evaluation_active()` false in every case; cache refresh when the file changes (same mtime-granularity guard as `_load_config`: key includes size and inode).
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.** Never raise out of `baseline_status()`/`signal_anomaly_active()` — any exception becomes `valid False, reason "unreadable"` (log at warning). Existing gate tests (`test_signal_anomaly_contract.py`, `test_scientific_status_cache.py`, `test_signal_gate_single_source.py`) must stay green; note that `scientific_status._load_config` bypass logic and the new loader are independent caches.
- [ ] **Step 4: Full backend suite.**
- [ ] **Step 5: Report.**

---

## Task 5: Site anomaly in the scheduler and API

**Files:**
- Modify: `backend/src/db_models.py` (`DetectionCache`: add nullable `signal_robust_z: float`, `baseline_version: str`, `signal_anomaly_reason: str`), `backend/src/db.py` only if the `_add_missing_columns` pattern needs the new column list (read it first)
- Modify: `backend/src/scheduler.py` (`refresh_one_site`)
- Modify: `backend/src/schemas.py` (`BaselineInfo` model; `RiskMapProperties` + `signal_robust_z`, `signal_anomaly_reason`; `RiskMapResponse.baseline: BaselineInfo | None`; `SummaryResponse.baseline`; `DetectResponse.signal_anomaly: dict | None` and `baseline`)
- Modify: `backend/src/routers/risk_map.py`, `summary.py`, `detect.py`
- Test: `backend/tests/test_site_anomaly.py`

**Interfaces:**
- Consumes: Task 4 `load_active_baseline`, `baseline_status`, `signal_anomaly_active`; Task 1 `assess_site` via the bridge.
- Behaviour: in `refresh_one_site`, after the detection read, **only if** `signal_anomaly_active()` and the detection status is `ok` and `NDCI` present: `assess_site(active.rows_by_location[site.site_id], location_id=site.site_id, current_ndci=index_values["ndci"], actual_date=detection["actual_date"], target_date=target_date, preprocessing_signature=manifest["preprocessing_signature"])` → store `signal_anomaly_level` (= `level`), `signal_robust_z`, `signal_anomaly_reason`, `baseline_version`. Otherwise those fields are None (with `signal_anomaly_reason` explaining when test mode is on but assessment impossible, e.g. `no_imagery`). Existing `spatial_anomaly_z` stays None. `level` (risk) stays None.
- `/risk-map`: `signal_anomaly_level`/`signal_robust_z` are exposed only when `signal_anomaly_active()` (existing gate pattern in `risk_map.py`); the response-level `baseline` carries `baseline_status()` when mode is test, else `None` (field absent-equivalent; **with mode off the JSON for every existing field is unchanged**).
- `/detect` (live): when active, compute the same assessment from the live reading and return `signal_anomaly` = the assess dict (level/robust_z/median_ndci/mad/independent_date_count/reason) and `baseline`.
- `BaselineInfo` fields: `mode, valid, kind, version, built_at, history_start, history_end, season_rule, min_independent_dates, median_independent_dates, preprocessing_signature, base_rates, reason`.

- [ ] **Step 1: Failing tests** — (a) mode off: `/risk-map` features have `signal_anomaly_level is None`, `baseline is None`; (b) test mode, fixture baseline, seeded `DetectionCache` row produced via `refresh_one_site` with `bridge.risk_level` monkeypatched to return an `ok` detection at NDCI far above the fixture history → feature has `signal_anomaly_level == "high"`, `signal_robust_z >= 3`, `baseline.kind == "test"`; (c) NDCI inside the history range → `normal`; (d) `no_imagery` detection → level None with reason; (e) test mode but invalid artefact → fields None, `baseline.valid == False`; (f) `/summary` includes the `baseline` block; (g) a column-migration test on an existing DB lacking the new columns (copy the pattern in `test_cache_schema_reset.py`).
- [ ] **Step 2–4: Fail, implement, green; full backend suite.**
- [ ] **Step 5: Report.**

---

## Task 6: Scene assessment (`data-pipeline/src/scene_assess.py`)

**Files:**
- Create: `data-pipeline/src/scene_assess.py`
- Modify: `data-pipeline/src/__init__.py`, `detection/src/_data_pipeline.py`, `backend/src/_detection.py` (re-export `assess_new_scenes`, `SceneAssessment`)
- Test: `data-pipeline/tests/test_scene_assess.py`

**Interfaces:**
- `@dataclass(frozen=True) class SceneAssessment: acquisition_date: str; cloud_fraction: float | None; water_pixels: int; decision: str; reason: str | None`; decisions: `"passed"`, `"rejected_cloud"`, `"rejected_no_water"`.
- `decide(*, cloud_fraction: float | None, water_pixels: int, max_cloud_fraction: float, min_water_pixels: int) -> tuple[str, str | None]` — pure: `water_pixels < min_water_pixels` → `("rejected_no_water", "<n> unmasked water pixels < <min>")`; `cloud_fraction > max_cloud_fraction` → `("rejected_cloud", "cloud <x:.0%> > <max:.0%>")`; else `("passed", None)`. `cloud_fraction is None` is treated as `rejected_no_water` only if `water_pixels == 0`, otherwise raises `ValueError` (no silent default).
- `combine_tiles(tile_stats: list[dict]) -> dict` — pure, merges per-tile `{"cloud_sum", "valid_count", "water_count"}`-style partial sums for the same UTC date into one `cloud_fraction`/`water_pixels` (weighted by pixel counts, never a mean of means). Define the partial-sum keys in the module docstring and use them in the GEE seam.
- `assess_new_scenes(polygon_latlng, since_date: str, *, max_cloud_fraction=…, min_water_pixels=…, scale_m=200, skip_dates: set[str] = frozenset(), _fetch=None) -> list[SceneAssessment]` — newest date first; skips dates in `skip_dates`; the `_fetch(polygon, since_date, scale_m) -> list[dict]` seam returns one dict per scene `{"date": "YYYY-MM-DD", "cloud_count": int, "valid_count": int, "water_count": int}` and the default implementation reduces, per scene, the production `_cloud_flag_image` and `_water_mask_image` over the polygon at `scale_m` (sum reducers, `maxPixels` high, `bestEffort=False`); a per-scene EE failure is **not** converted into a decision (raise; the caller leaves the date unassessed).
- Defaults read from `sentinel2.DEFAULT_MAX_CLOUD_FRACTION` and env `RASTER_SCENE_MAX_CLOUD_FRACTION` / `RASTER_SCENE_MIN_WATER_PIXELS` (default 1000) through one function `scene_thresholds() -> tuple[float, int]` with validation (invalid env → `ValueError` naming the variable, like `_gee_timeout_seconds`).

- [ ] **Step 1: Failing tests** — `decide` truth table incl. boundary equality (cloud exactly 0.5 passes), `cloud_fraction None` rules; `combine_tiles` weighted correctness (two tiles 100px @0.0 and 900px @1.0 → 0.9, **not** 0.5); `assess_new_scenes` with stub `_fetch`: several tiles same date merge; order newest-first; `skip_dates` honoured; env thresholds; invalid env raises named `ValueError`; a `_fetch` that raises propagates.
- [ ] **Step 2–4: Fail, implement, green; data-pipeline + detection suites.**
- [ ] **Step 5: Report.**

---

## Task 7: Latest-scene trigger, `scene_assessments` table, sites refresh

**Files:**
- Modify: `backend/src/db_models.py` (`SceneAssessment` table: `acquisition_date` PK, `cloud_fraction`, `water_pixels`, `decision`, `reason`, `assessed_at`, `used_in_run_id` nullable)
- Modify: `backend/src/config.py` (`RASTER_SCAN_MIN_INTERVAL_HOURS` default 1; `RASTER_SCAN_POLL_INTERVAL_HOURS` default **1**; keep `RASTER_SCAN_COOLDOWN_HOURS` readable but no longer applied to qualifying scenes), `backend/.env.example`
- Modify: `backend/src/raster_scan/trigger.py` (poll rewrite), `backend/src/raster_scan/scan.py` (record `used_in_run_id` on success; keep existing bootstrap semantics)
- Modify: `backend/src/scheduler.py` (export a function `refresh_grid_for(target_date)` or reuse `refresh_grid`; call it after a qualifying scan)
- Test: `backend/tests/test_latest_scene_trigger.py` (+ update `test_raster_scan_trigger.py` only where an assertion encoded the 20 h cooldown for a new scene — state this in the report)

**Behaviour (from the spec §7):**
1. `poll_and_maybe_scan()` reads existing `SceneAssessment` dates, calls `assess_new_scenes(polygon, since, skip_dates=assessed_dates)` (bridge); persists each result (a raise leaves that date unassessed and ends the poll with a logged warning; GEE auth errors log and return as today).
2. Let `newest_passing` be the newest date with `decision == "passed"` whose date is **newer than the newest `used_in_run_id IS NOT NULL` date** (or no used date exists). If none → return (rejected scenes trigger nothing, previous raster keeps serving).
3. Respect `RASTER_SCAN_MIN_INTERVAL_HOURS` relative to the latest attempt `started_at` (any status). A qualifying scene bypasses the old 20 h cooldown. No running run → start `run_raster_scan(db, today_str(), trigger_scene_timestamp=<iso of newest_passing>)`. On success set `used_in_run_id` for that date; an `error` run leaves it NULL (retried after the min interval).
4. After a **successful** scan, call the sites refresh once so sites and raster describe the same acquisition (failures there are logged, never raised).
5. Shutdown flag checks as in the current poll (`shutdown.stop_requested()` at entry and between assessment and scan).
6. `trigger.should_trigger_scan` may stay for backwards compatibility but must no longer be called by `poll_and_maybe_scan`; update/remove its tests only if they exercised the old call path.

- [ ] **Step 1: Failing tests** (monkeypatch `bridge.assess_new_scenes`, `run_raster_scan`, `scheduler.refresh_grid`; fake clock via `datetime` patch or injected `now`): passing new scene + last attempt 2 h ago → scan starts (old code: blocked by 20 h cooldown); rejected-cloud newest scene → no scan, assessment row stored with the fraction, previous used date unchanged; rejected newest + older passing newer-than-used scene → scan for the older passing date; min-interval blocks a second scan 10 min later; errored scan leaves `used_in_run_id` NULL and retries next poll after the interval; success sets `used_in_run_id` and calls the sites refresh once; sites refresh raising does not raise out; assessed dates are not re-assessed on the next poll (`skip_dates` passed); assessment error leaves the date unassessed and starts nothing; shutdown flag set → returns before assessing; `used` date equal to newest passing → nothing to do.
- [ ] **Step 2–4: Fail, implement, green; full backend suite** (the earlier trigger/budget/resume tests must still pass or be updated with a stated reason).
- [ ] **Step 5: Report.**

---

## Task 8: `/raster-scan` latest-scene fields

**Files:**
- Modify: `backend/src/schemas.py` (`LatestSceneInfo`; `RasterScanResponse.latest_scene: LatestSceneInfo | None`), `backend/src/routers/raster_scan.py`
- Test: `backend/tests/test_raster_scan_endpoint.py` (add cases)

**Interfaces:** `LatestSceneInfo{acquisition_date, decision, cloud_fraction, threshold_cloud_fraction, reason, used_in_run_id, assessed_at}` = the newest `SceneAssessment` row (or `None` when the table is empty). `threshold_cloud_fraction` from `scene_thresholds()`. Other `RasterScanResponse` fields unchanged.

- [ ] **Step 1: Failing tests:** table empty → `latest_scene is None`; newest row `rejected_cloud` → fields echoed with `threshold_cloud_fraction`; row used in the served run → `used_in_run_id == run_id`; response validates against the schema; existing endpoint tests unchanged.
- [ ] **Step 2–4:** fail, implement, green, full suite. **Step 5:** report.

---

## Task 9: Highlights endpoint (NDCI ranking + anomaly-ready)

**Files:**
- Create: `backend/src/raster_scan/highlights.py` (pure ranking), update module docstring pattern from `pixel.py`
- Modify: `backend/src/schemas.py` (`RasterHighlightPin`, `RasterHighlightsResponse`), `backend/src/routers/raster_scan.py` (`GET /raster-scan/highlights`)
- Test: `backend/tests/test_raster_highlights.py`, endpoint cases appended to `test_raster_scan_endpoint.py`

**Interfaces (pure):**
- `rank_cells(arrays: dict, *, metric: str = "ndci", n: int, min_separation_m: float, scale_m: int) -> dict` where `arrays` is the stored-cells dict as `storage.read_cells` returns (keys `lat`, `lng`, `ndci`, `bda2`, `bda3`, `b2_b3`, `date_ms`, …; read `storage.py`/`pixel.py` for the exact dtypes). Valid cells = `bridge.valid_cell_mask(date_ms)` & finite metric. Returns `{"cohort_size": int, "pins": [pin dicts], "reason": str | None}`. Pin: `rank, cell_lat, cell_lng, pixel_centre_lat, pixel_centre_lng, index_values{ndci,bda2,bda3,b2_b3 (null when unreadable)}, percentile, date_ms, acquired_date, acquired_at, edge_of_no_data, metric_value`.
- Order: metric descending, tie-break lower row then lower column (derive row/col from `pixel.grid_for_run`/`OverlayGrid.cell_indices`); greedy non-maximum suppression with great-circle (haversine) distance `< min_separation_m` against already-selected pins; `percentile` = share of cohort cells with a strictly lower metric × 100; `edge_of_no_data` = any 8-neighbour in the grid is not a valid cell (cells on the polygon bounding edge count only if the neighbour is inside the polygon and unmeasured — document the rule); fewer than `n` separable cells → fewer pins and `reason = "only k separable measured cells"`; empty cohort → `pins == []`, `reason = "no measured cells"`.
- Endpoint: `GET /raster-scan/highlights?run_id=&n=5&min_separation_m=3000&mode=ndci` — `n` 3..10, `min_separation_m` 1000..10000, `mode` ∈ `ndci` (this task) and `anomaly` (returns **501** with detail "anomaly mode requires the Level B baseline" until Task 11, keeping the contract); run resolution identical to `/raster-scan/pixel` (`_rendered_run`); 404 wording as pixel; response: `run_id, mode, metric, ranking: "descending value within this run; not a risk level", n_requested, min_separation_m, cohort_size, pins, reason, baseline: None, disclaimer`; every pin has `risk_tier: null` and the response **has no code path that sets it** (assert in a test by grepping the module for `risk_tier =` assignments other than `None`).

- [ ] **Step 1: Failing tests** with a synthetic 20×20 cell grid at a fake scale: ordering, NMS drops adjacent cells, deterministic tie-break, percentile math on a tiny cohort, `edge_of_no_data` true next to a hole and false in the interior, fewer-than-n reason, empty cohort, unreadable secondary index → `null`, invalid params → 422, no run → 404, `mode=anomaly` → 501.
- [ ] **Step 2–4:** fail, implement, green, full suite. **Step 5:** report.

---

## Task 10: `GET /methods`

**Files:**
- Modify: `detection/src/indices.py` — add `INDEX_METADATA` beside `INDEX_FUNCTIONS` (per key: `name`, `formula`, `bands`, `role` ∈ `primary|derived|exploratory`, `note`); wavelengths dict `BAND_WAVELENGTHS_NM = {"B2": 490, "B3": 560, "B4": 665, "B5": 705, "B6": 740}` **only after confirming each value in the module docstrings/`LIMITATIONS.md`/`DETECTION_PLAN.md`; otherwise omit that band** and say so in the report
- Create: `backend/src/routers/methods.py`, `backend/src/methods_info.py` (static references; the two verified DOIs from `LIMITATIONS.md` §"Scientific references and transfer limits")
- Modify: `backend/src/schemas.py` (`MethodsResponse` and parts), `backend/src/main.py` (include router), `backend/src/_detection.py` (re-export indices metadata + signal constants if not already)
- Test: `backend/tests/test_methods.py`, `detection/tests/test_indices_metadata.py`

**Behaviour:** response shape per dashboard spec §6, plus `baseline: baseline_status()` and the baseline's `base_rates` when available. `worked_example.value` is computed by calling the **real** `INDEX_FUNCTIONS[key]` on fixed sample bands (`{"B2": 800, "B3": 900, "B4": 600, "B5": 700, "B6": 650}` unless a different set avoids a zero denominator); `display_domain` from the data-pipeline `BAND_DOMAINS` (None when absent); `gates` from `scientific_status` + the detection constants; `sentinel2.max_scene_age_days` from `default_max_scene_age_days()`; no GEE, no DB.

- [ ] **Step 1: Failing tests:** keys of `INDEX_METADATA` == keys of `INDEX_FUNCTIONS`; each worked example equals hand arithmetic of its displayed formula (NDCI `(700-600)/(700+600)`, 2BDA `700/600`, 3BDA `(1/600-1/700)*650`, B2/B3 `800/900`); gates equal `scientific_status` outputs (monkeypatch both true/false); floors equal detection constants; every DOI in `/methods` appears in `LIMITATIONS.md`; `baseline` block mirrors `baseline_status()`; route is GET-only and makes no GEE call (monkeypatch GEE entry points to raise).
- [ ] **Step 2–4:** fail, implement, green; backend + detection suites. **Step 5:** report.

---

## Task 11: Level B feasibility spike — DONE (controller-run, 2026-10-09)

Result: season window Sep–Nov (calendar months 9–11, 140 distinct acquisition dates, 2017-12 → 2026-10) at 200 m over the study polygon: per-day mosaic (`raster._index_bands`) → median / MAD of daily NDCI / count, one `getDownloadURL` NPY (618×620 grid, 7.7 MB) in **27 s**. 289,921 cells have ≥ 1 observation (the polygon has ≈ 300,614 water cells); **99.4 %** of those have n ≥ 30, 84.8 % n ≥ 40; n median 45, max 62; **no cell has MAD = 0**; MAD pctl 5/50/95 = 0.020/0.037/0.056; median NDCI pctl 5/50/95 = −0.006/0.043/0.066. Gate (≤ 15 min and ≥ 70 % of cells with n ≥ 30) **passed** → Tasks 12–13 proceed. Script: scratchpad `levelB_spike.py`.

---

## Task 12: Level B per-cell baseline (builder, artefact, loader)

**Files:**
- Create: `data-pipeline/src/baseline_raster.py`
- Modify: `data-pipeline/src/__init__.py`, `detection/src/_data_pipeline.py`, `backend/src/_detection.py` (additive re-exports: `build_cell_baseline`, `cell_baseline_params`)
- Modify: `detection/src/baseline.py` (pure helpers listed below), `backend/src/baseline_store.py` (cells IO + loader), `scripts/build_test_baseline.py` (`--level B`, default `--level A`; `--level AB` builds both)
- Test: `data-pipeline/tests/test_baseline_raster.py`, `detection/tests/test_baseline_cells.py`, `backend/tests/test_baseline_store_cells.py`, `backend/tests/test_build_test_baseline.py` (add cases)

**Interfaces:**
- `baseline_raster.cell_baseline_params() -> dict` — canonical preprocessing description of the CELL baseline from live constants: `{"collection", "bands", "cloud_classes", "min_water_occurrence_pct", "scale_m": RASTER scale (200), "sampling": "raster-nearest-native-pixel-per-day-mosaic", "index": "ndci=(B5-B4)/(B5+B4)", "per_day_reduction": "mosaic of same-UTC-date tiles", "statistic": "median / MAD(median of |x-median|) over daily values", "polygon_id": <hash of study polygon vertices>}`; its signature = `preprocessing_signature(params)` (different from the site signature).
- `baseline_raster.build_cell_baseline(polygon_latlng, months: tuple[int, int, int], start: str, end: str, scale_m: int = 200, *, _fetch=None) -> dict` — returns `{"lat": float64[N], "lng": float64[N], "median": float32[N], "mad": float32[N], "n": uint16[N], "scale_m", "months", "start", "end", "n_dates": int}` with ONE entry per cell having n ≥ 1 and finite median (flat arrays like `download_composite_arrays`). GEE seam `_fetch(polygon, months, start, end, scale_m) -> structured numpy array with fields median, mad, n, longitude, latitude` (default implementation = the spike script's logic: calendarRange month filter, distinct UTC dates, per-day mosaic of `_index_bands` ndci with the production water mask / cloud classes, median, MAD = median of |daily − median|, count, `ee.Image.pixelLonLat()`, NPY at `scale_m`). `end` is exclusive.
- Season windows: `baseline.season_months(M)` (existing) gives the 3 calendar months for target month `M`; the builder loops M = 1..12.
- `detection/src/baseline.py` additions (pure): `cell_key(lat, lng, scale_m) -> tuple[int, int]` = integer grid index `(round((lat - LAT0)/dlat), round((lng - LNG0)/dlng))` — design it so that the SAME key is produced for a production raster cell and the baseline cell at the same location even with float noise (document tolerance: half a cell); `assess_cell(ndci, median, mad, n, *, min_dates, mad_scale, watch_at_z, high_at_z) -> dict {level, robust_z, reason}` implementing exactly `signal_anomaly`'s formula and thresholds (import the constants; reasons: `insufficient_independent_dates`, `zero_mad`, `invalid_ndci`; reuse `signal_anomaly.classify_robust_z`). Vectorised variant `assess_cells(ndci: ndarray, median, mad, n, ...) -> (z: float32[N] with NaN where not assessable, level_code: uint8[N] (0 not assessable, 1 normal, 2 watch, 3 high), reason_code: uint8[N])` with a documented code table; tested elementwise against `assess_cell`.
- Artefact: Level B files `cells_m{MM}.npz` (arrays above) written into the SAME `backend/data/baselines/<version>/` directory (`write_artifact` / builder: build A and B into one version). Manifest gains `level_b`: `{"scale_m", "cell_preprocessing_signature", "history_start", "history_end", "seasons": {season_key: {"file", "months", "cells", "cells_n_ge_floor", "n_median", "n_min", "n_max", "mad_p05","mad_p50","mad_p95"}}}`. **History end rule (leakage):** the builder's default `--end` for Level B is `today − 15 days` (exclusive) and the manifest records `history_end`; assessment only scores cells whose own acquisition date is strictly later than `level_b.history_end` (enforced in Task 13). A Level B build is REFUSED (`BuilderRefused`) if any season has < 90 % of its cells with n ≥ 30 (`signal_anomaly.MIN_INDEPENDENT_DATES`) — report the share; nothing is written.
- `validate_manifest` additions: when `level_b` is present validate keys, `cell_preprocessing_signature == live`, `history_end` ≤ today, 12 season files named in the manifest exist (checked by the loader, not the pure function).
- Loader: `baseline_store.load_cell_baseline(season_key) -> CellBaseline | None` (`@dataclass(frozen=True)`: lat, lng, median, mad, n, scale_m, season_key, version, history_end, key index `dict[tuple[int,int], int]` built lazily/cached with the same mtime/size/inode discipline as `load_active_baseline`); NEVER raises (None + logged reason); mode off → None.

- [ ] **Step 1: Failing tests** — `cell_key` stability under 1e-7° noise and distinct neighbouring cells; `assess_cells` equals `assess_cell` elementwise over a grid of cases (n=29/30, mad=0, z exactly 2.0 and 3.0 (boundary: z ≥ 2 watch, ≥ 3 high as in `classify_robust_z`), ndci out of [-1, 1], NaN); builder with a fake `_fetch` returns flat arrays with correct dtypes and drops cells with n = 0/NaN; refusal when a season has < 90 % cells n ≥ 30 and nothing is written; manifest `level_b` block shape; round-trip write/read of cells files; loader returns None in mode off and on a missing file, valid otherwise; signature changes when `scale_m` changes; live-signature mismatch → invalid.
- [ ] **Step 2–4: Fail, implement, green; run data-pipeline, detection and backend suites.**
- [ ] **Step 5 (controller, live):** `cd backend && EE_PROJECT_ID=… ./venv/bin/python ../scripts/build_test_baseline.py --level AB --replace` (≈ 6 min). Then check alignment: for the served raster run's stored cells, the share of cells whose `cell_key` exists in the matching season baseline (expect ≥ 99 %).
- [ ] **Step 6: Report.**

---

## Task 13: Anomaly pins and cell inspector (mode=anomaly)

**Files:**
- Modify: `backend/src/raster_scan/highlights.py`, `backend/src/routers/raster_scan.py`, `backend/src/schemas.py`, `backend/src/site_anomaly.py` (if helpers fit there)
- Test: `backend/tests/test_raster_highlights.py` (add), `backend/tests/test_raster_scan_endpoint.py` (add), `backend/tests/test_raster_pixel_anomaly.py` (new)

**Behaviour (spec test-baseline §6):**
- `GET /raster-scan/highlights?mode=anomaly|ndci` — default `anomaly` when `baseline_snapshot()` is valid AND Level B is loadable for the run's season, else `ndci`; explicit `mode=anomaly` without a valid Level B baseline → **409** with detail naming the reason (`mode_off`, `no_cell_baseline`, `invalid: <reason>`), no longer 501. Season = `season_key(month of run.date_used)` (same rule as sites: target-date month).
- Per measured cell (same cohort as the NDCI ranking: cells the map paints): `assess_cells` with the season's median/MAD/n matched by `cell_key`. A cell is **assessable** only if: key present in the baseline; `n ≥ min_independent_dates` (the manifest's declared floor); `mad > 0`; its own acquisition date is strictly after `level_b.history_end`; ndci within [-1, 1]; AND its acquisition date is ≤ 14 days before `date_used` (`signal_anomaly.MAX_OBSERVATION_AGE_DAYS`). Otherwise it carries a reason code, never a default.
- Pin condition: robust z ≥ `WATCH_AT_Z` (2.0) → level `watch`, ≥ `HIGH_AT_Z` (3.0) → `high` (positive anomalies only — higher-than-usual chlorophyll signal; negative z is not a pin). Rank by z desc (tie: ndci desc, lower row, lower column), same NMS / `n` / `min_separation_m` as the NDCI mode, `edge_of_no_data` as before. Pin fields add `robust_z`, `median_ndci`, `mad`, `n_dates`, `anomaly_level`; `risk_tier` stays null with no code path setting it.
- Response (`mode == "anomaly"`) adds `counts`: `{measured, assessable, no_baseline, insufficient_dates, zero_mad, not_after_history, too_old, invalid, watch, high}` (they partition `measured`: `assessable + the five reason counts == measured`; `watch`/`high` count assessable cells over thresholds), a `baseline` block (`baseline_status()` incl. `level_b` summary and `history_end`), and `ranking: "descending robust z against this location's own TEST seasonal baseline; not a risk level"`. `reason` states "no cells meet the condition (k assessable of m measured)" when pins are empty — distinguishable from "nothing assessable".
- `GET /raster-scan/pixel` (single cell) gains `anomaly: {…} | null`: in test mode with a valid Level B baseline, for a `reading` cell: `robust_z`, `median_ndci`, `mad`, `n_dates`, `level`, `reason` (null when computed), `baseline_version`, `season_key`; otherwise null. Mode off: field null and every existing field unchanged.
- Disclaimer: responses carrying anomaly values use `disclaimer_for(status)` (TEST variant) exactly as sites do; `mode=ndci` responses keep the standard disclaimer.
- Blocking work stays off the event loop (sync handlers), one snapshot per request, never raises 500 for baseline problems (409/null with reasons).

- [ ] **Step 1: Failing tests** with synthetic grids and a fixture Level B artefact built through the real builder helpers (tmp_path): z computed exactly `(ndci − median)/(1.4826·mad)` for a hand-checked cell; boundary cells z = 2.0 → watch, 1.999 → none, 3.0 → high; negative z never pins; cells with n < floor / mad = 0 / date ≤ history_end / older than 14 days / missing key each counted in the right reason bucket and `assessable + reasons == measured`; NMS and ordering by z; empty-pins reason distinguishes "none assessable" from "none met"; default mode switches with baseline validity; `mode=anomaly` with mode off / no cell baseline → 409 with reason; pixel `anomaly` block values equal the highlights pin for the same cell; mode off leaves all existing JSON keys/values unchanged; TEST disclaimer on anomaly responses; no source assigns a non-None `risk_tier`; leak guard: a cell dated on `history_end` is not assessable.
- [ ] **Step 2–4: Fail, implement, green; full backend suite.**
- [ ] **Step 5 (controller, live):** with the real artefact and `BASELINE_MODE=test`, call the endpoints on the served run through the running backend and record counts and the top pins.
- [ ] **Step 6: Report.**

---

## Self-Review

1. **Spec coverage.** Test-baseline spec §4 → T1–T3; §5 activation/labelling → T4–T5 (API fields; UI banner is in the frontend plan); §6 pins → T9 (+ T12–T13 conditional); §7 latest-scene policy → T6–T8; dashboard spec §6 `/methods` → T10; §6.1 highlights → T9. Frontend items are deferred to plan B by design.
2. **Placeholders.** None intended; the only conditional content is T11's explicit gate and T10's wavelength confirmation rule.
3. **Names.** `season_key`, `season_months`, `preprocessing_signature`, `scoped_history`, `assess_site`, `self_check`, `build_manifest`, `validate_manifest`, `BaselineInvalid`, `version_for`, `get_ndci_history`, `preprocessing_params`, `rows_from_stats`, `load_active_baseline`, `ActiveBaseline`, `baseline_status`, `assess_new_scenes`, `SceneAssessment`, `scene_thresholds`, `rank_cells` are used consistently across tasks.
4. **Review Focus.** Leakage → T1 test `test_assess_site_no_future_leakage`; signature reuse → T1/T4; missing artefact → T4; gate looseness → T1/T4 hand-edited manifest tests; trigger consumption → T7; "no pins vs nothing assessed" → T9 `cohort_size`/`reason` (the anomaly counts arrive with T12–T13).
