# Code-Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Verify, then fix, the highest-value findings from the 2026-10-09 `/code-review xhigh` of branch `feature/regional-scan`, without overclaiming and without touching unreviewed design decisions.

**Architecture:** Every finding is first reproduced (Task 0). A finding that does not reproduce is dropped, not "fixed". Each fix is test-first, one commit per task. Findings that need a product decision from the owner are listed under "Deferred" and are not implemented.

**Tech Stack:** FastAPI, SQLAlchemy (SQLite), pytest, React/Vite, earthengine-api.

**Spec:** none written. Source of truth is the review output in this session (16 findings, file:line each). Project rules: `CLAUDE.md` §0 (truth boundary), §1 (locked decisions).

## Global Constraints

- Physics-based, no ML. Do not touch `backend/ensemble_service.py`, `train_dual_models.py`, `forecast_service.py`, `models/*.joblib` (CLAUDE.md §9).
- Detection and prediction stay separate claims. An unevaluated value must never read as "zero" or "all clear".
- Backend tests: `cd backend && ./venv/bin/python -m pytest tests -q --ignore=tests/test_ensemble_service.py --ignore=tests/test_forecast_engine.py --ignore=tests/test_realistic_scenarios.py` (those 3 fail collection on missing `joblib`, orphaned ML code). Baseline before any change: 216 passed, 2 skipped.
- No live GEE calls in tests; mock at typed boundaries. `SCHEDULER_ENABLED=false` is set by `tests/conftest.py`.
- Config via env vars + `.env.example` only; no secrets.
- Commit trailer: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- The working tree already holds many uncommitted user changes. Stage only the files named in each task (`git add <paths>`), never `git add -A`.

## Review Focus

- `/alerts` with the risk gate off: a client must be able to tell "not evaluated" from "evaluated, none". (Task 1)
- A raster scan that ends in `error`: next poll must be allowed to retry the same scene. (Task 2)
- A map click while another request is in flight: the pixel handler must not block the event loop. (Task 3)
- Raster metadata pointing at a PNG that was deleted from disk: no dead `true_color_url`. (Task 4)
- `GEE_REQUEST_TIMEOUT_SECONDS=abc` or `0`: error must say config problem, not "not authenticated". (Task 5)

---

## Task 0: Reproduce every finding before changing code

Debugging rule: no fix without a reproduced cause. Output is a short table in `docs/superpowers/plans/2026-10-09-code-review-verification.md` marking each finding CONFIRMED / NOT REPRODUCED.

**Files:**
- Create: `docs/superpowers/plans/2026-10-09-code-review-verification.md`

- [ ] **Step 1: Baseline.** Run the Global Constraints test command. Expected: `216 passed, 2 skipped`. If not, stop and report.

- [ ] **Step 2: Confirm by reading code + a one-line check each** (record result per finding):
  - F1 alerts: `curl`-equivalent via TestClient; gate off returns `total_active_alerts: 0`, fresh `updated_at`, no status field. Already visible in `backend/src/routers/alerts.py:55-62`.
  - F2 trigger: in `backend/src/raster_scan/trigger.py:56-60`, `latest_triggered` filters only on `trigger_scene_timestamp IS NOT NULL`, not on status. Confirm `RasterScanRun` has a `status` column: `grep -n "class RasterScanRun" -A30 backend/src/db_models.py`.
  - F3 pixel: `backend/src/routers/raster_scan.py:204` is `async def` and calls blocking `pixel_lookup.inspect_run`. Confirm with `inspect.iscoroutinefunction`.
  - F4 true_color_url: `backend/src/routers/raster_scan.py:149` checks key only. Compare to `_rendered_run`'s `Path(...).exists()` check.
  - F5 auth: `GEE_REQUEST_TIMEOUT_SECONDS=abc` with `initialize_ee(force=True)` raises `GEEAuthError` containing the "not authenticated" text. Run in a throwaway script under the scratchpad with `ee.Initialize` untouched (the parse fails before it).
  - F6-F16: for each remaining finding, open the cited line and record whether the described code is present. Do not fix.

- [ ] **Step 3: Commit the verification note**

```bash
git add docs/superpowers/plans/2026-10-09-code-review-verification.md
git commit -m "docs: record verification of code-review findings

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

**Gate:** Tasks 1-5 run only for findings marked CONFIRMED.

---

## Task 1: `/alerts` must say "not evaluated"

**Files:**
- Modify: `backend/src/routers/alerts.py:33-62`
- Test: `backend/tests/test_alerts_not_evaluated.py` (create)

**Interfaces:**
- Produces: `AlertsResponse.evaluation_status: Literal["active", "not_evaluated"]`; `updated_at: Optional[str]` is `None` when `not_evaluated`.

- [ ] **Step 1: Find consumers.** `grep -rn "total_active_alerts\|updated_at" frontend/src backend/tests | grep -i alert`. If a consumer requires non-null `updated_at`, keep it a string and only add `evaluation_status`. Record the decision in the commit message.

- [ ] **Step 2: Write the failing test**

```python
"""/alerts must distinguish 'not evaluated' from 'evaluated, none' (CLAUDE.md §0)."""

from __future__ import annotations

from src.routers import alerts as alerts_module


def test_alerts_reports_not_evaluated_when_risk_gate_off(client, monkeypatch):
    monkeypatch.setattr(alerts_module, "risk_evaluation_active", lambda: False)
    body = client.get("/alerts").json()
    assert body["evaluation_status"] == "not_evaluated"
    assert body["stations"] == []
    assert body["highest_risk_tier"] is None


def test_alerts_reports_active_when_risk_gate_on(client, monkeypatch):
    monkeypatch.setattr(alerts_module, "risk_evaluation_active", lambda: True)
    body = client.get("/alerts").json()
    assert body["evaluation_status"] == "active"
```

- [ ] **Step 3: Run, expect FAIL** (`KeyError: 'evaluation_status'`):
`cd backend && ./venv/bin/python -m pytest tests/test_alerts_not_evaluated.py -q`

- [ ] **Step 4: Implement.** In `alerts.py`: add `from typing import Literal`; add `evaluation_status: Literal["active", "not_evaluated"] = "active"` to `AlertsResponse`; in the gate-off branch pass `evaluation_status="not_evaluated"`; set `updated_at` per Step 1's decision (`None` if no consumer needs a string). Update the endpoint docstring: "Empty and `not_evaluated` while calibrated risk evaluation is disabled."

- [ ] **Step 5: Run new tests + full suite.** Expect all pass.

- [ ] **Step 6: Commit** `fix(alerts): flag not_evaluated instead of reporting zero alerts` (stage the two files only, add trailer).

---

## Task 2: Errored scan must not consume its scene

**Files:**
- Modify: `backend/src/raster_scan/trigger.py:56-60`
- Test: `backend/tests/test_raster_scan_trigger.py` (modify; read it first and reuse its fixtures/style)

**Interfaces:**
- Consumes: `RasterScanRun.status` (verify exact column and error value in Task 0 Step 2).

- [ ] **Step 1: Write the failing test** in `test_raster_scan_trigger.py`: insert a `RasterScanRun` with `status="error"`, `trigger_scene_timestamp="2024-03-14T03:00:00Z"`, `started_at` older than the cooldown; monkeypatch `bridge.get_newest_scene_timestamp` to return the same timestamp and `trigger.run_raster_scan` to a recorder; call `poll_and_maybe_scan()`; assert the recorder was called once. Add the mirror case with `status="ok"` asserting it was NOT called.

- [ ] **Step 2: Run, expect FAIL** on the error case.

- [ ] **Step 3: Implement.** Add `RasterScanRun.status != "error"` to the `latest_triggered` query's `.where(...)`. Leave `latest_attempt` (cooldown) untouched: a failed run still starts the cooldown, so retries are spaced by `RASTER_SCAN_COOLDOWN_HOURS`.

- [ ] **Step 4: Run trigger tests + full suite.**

- [ ] **Step 5: Commit** `fix(raster): let a failed scan retry its own scene`.

---

## Task 3: Pixel endpoint off the event loop

**Files:**
- Modify: `backend/src/routers/raster_scan.py:204` (`async def` to `def`)
- Test: `backend/tests/test_raster_scan_endpoint.py` (modify)

- [ ] **Step 1: Failing test**

```python
import inspect
from src.routers import raster_scan as raster_scan_router


def test_pixel_handler_is_sync_so_blob_read_runs_in_threadpool():
    assert not inspect.iscoroutinefunction(raster_scan_router.get_raster_pixel)
```

- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.** Change `async def get_raster_pixel` to `def get_raster_pixel`. Body unchanged (no `await` inside; confirm with grep).
- [ ] **Step 4: Run endpoint tests + full suite.**
- [ ] **Step 5: Commit** `perf(raster): run pixel lookup in the threadpool`.

Decoded-cells caching is deferred (see below).

---

## Task 4: No dead `true_color_url`

**Files:**
- Modify: `backend/src/routers/raster_scan.py:~149`
- Test: `backend/tests/test_raster_scan_endpoint.py`

- [ ] **Step 1: Read** `_rendered_run` and the existing endpoint test that builds a run with assets; copy its setup.
- [ ] **Step 2: Failing test:** build a run whose overlay metadata has `assets.true_color.path` pointing at a nonexistent file; GET the metadata endpoint; assert `true_color_url is None`. Second case with an existing file asserts the URL is present.
- [ ] **Step 3: Implement.** Replace the key-only check with `true_color_asset = (overlay.get("assets") or {}).get("true_color")` and `Path(true_color_asset["path"]).exists()` guarded for a missing `path` key.
- [ ] **Step 4: Run, full suite.**
- [ ] **Step 5: Commit** `fix(raster): advertise true-color only when the PNG exists`.

---

## Task 5: GEE timeout typo is a config error

**Files:**
- Modify: `data-pipeline/src/auth.py:110-120`
- Test: `data-pipeline/tests/` (new `test_auth_timeout_config.py`; follow the existing test style there)

- [ ] **Step 1: Failing test:** set `GEE_REQUEST_TIMEOUT_SECONDS` to `"abc"` and `"0"`; call `initialize_ee(force=True)`; assert `pytest.raises(ValueError, match="GEE_REQUEST_TIMEOUT_SECONDS")` and that the raised type is not `GEEAuthError`. `ee.Initialize` must not be reached.
- [ ] **Step 2: Run** `cd data-pipeline && ./venv/bin/python -m pytest tests/test_auth_timeout_config.py -q`; expect FAIL (a `GEEAuthError` is raised).
- [ ] **Step 3: Implement.** Move the `timeout_value`/`timeout_seconds` parse and the `isfinite`/`> 0` check into a helper `_gee_timeout_seconds()` called before the `try:`. It raises `ValueError(f"{GEE_REQUEST_TIMEOUT_ENV_VAR} must be a finite positive number, got {value!r}")`.
- [ ] **Step 4: Run data-pipeline suite** and backend `test_gee_auth_503.py`.
- [ ] **Step 5: Commit** `fix(auth): report a bad GEE timeout as config, not auth`.

---

## Deferred (need owner decision or larger design; not in this plan)

| Finding | Why deferred |
|---|---|
| `render.py:497` unmeasured water now transparent, guard tests deleted | Product/truth-boundary decision; needs owner to choose between restoring a "no reading" fill or accepting the legend caption. Highest remaining risk. |
| `main.py:82` shutdown `wait=True` blocks on full job | Needs a cooperative stop flag across scheduler jobs; design first. |
| `scan.py:54` unbounded bootstrap + `STALE_RUN_HOURS=1` | Needs a wall-clock budget policy. |
| `scan.py:180` hard-coded 14-day scene age | Touches a test rewritten on purpose; confirm intent first. |
| `scheduler.py:182` second scene read for `cloud_fraction` | Cross-project change in `detect()` return shape. |
| `scientific_status.py:30` config re-parsed per call | Safe, small; do after Task 5 if wanted (mtime-keyed cache). |
| `signal_anomaly.py:47` thresholds in three places | Config-design change. |
| `auth.py:138` double `ee.Initialize` | Comment says it is deliberate; needs a measurement before touching. |
| Frontend: layer-switcher click-through, banner overlaps legend | Needs browser check; separate frontend plan. |
| `scan.py:95` Python list over date band | Minor perf. |

## Self-Review

- Coverage: the five confirmed-by-reading items with a clear, local fix each have a task; everything else is listed with a reason.
- No placeholders: Tasks 2 and 4 say "read the existing test first" because exact fixture names were not inspected; Task 0 Step 2 resolves column names before they are used.
- Names: `evaluation_status`, `_gee_timeout_seconds`, `get_raster_pixel` used consistently.
