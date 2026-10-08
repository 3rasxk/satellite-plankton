# Code-review findings: verification (2026-10-09)

Baseline: `cd backend && ./venv/bin/python -m pytest tests -q --ignore=tests/test_ensemble_service.py --ignore=tests/test_forecast_engine.py --ignore=tests/test_realistic_scenarios.py` gave `216 passed, 2 skipped, 1 warning`.

No source file was modified. Scratch scripts live outside the repo.

| ID | Result | Evidence |
|----|--------|----------|
| F1 | CONFIRMED-BY-READING | `backend/src/routers/alerts.py:55-62`: when `risk_evaluation_active()` is false the handler returns `total_active_alerts=0`, `updated_at=now()`, `stations=[]`; `AlertsResponse` (alerts.py ~38-42) has no status field. |
| F2 | CONFIRMED-BY-READING | `trigger.py:54-58` `latest_triggered` filters only `trigger_scene_timestamp IS NOT NULL`, not status. Column is `RasterScanRun.status` (`db_models.py`, class at line 132); errors are written as `status = "error"` (`scan.py:238` stale-run path, `scan.py:20` GEEAuthError abort). Other values: `running`, `ok`, `no_data`. `scan.py:360` stores the trigger timestamp on the row at creation, so an errored run still holds it. |
| F3 | CONFIRMED | `routers/raster_scan.py:204` `async def get_raster_pixel`; `inspect.iscoroutinefunction(get_raster_pixel)` printed `True`. The handler body (lines ~204-250) contains no `await`; it calls the blocking `pixel_lookup.inspect_run(...)` and `_rendered_run` (sync DB) directly on the event loop. |
| F4 | CONFIRMED-BY-READING | `routers/raster_scan.py:~149-153` sets `true_color_url` when `(overlay.get("assets") or {}).get("true_color")` is truthy (key only). `_rendered_run` (lines 80-102) checks `Path(asset["path"]).exists()` for `OVERLAY_BAND` only, never for `true_color`. The true-color route returns 404 when the file is missing, so the URL can be advertised for a missing file. |
| F5 | CONFIRMED | `data-pipeline/venv` is absent, so the repro used `backend/venv` (has `ee`) with `ee.Initialize` stubbed. `GEE_REQUEST_TIMEOUT_SECONDS=abc` plus `auth.initialize_ee(force=True)` raised `GEEAuthError` whose message starts "Google Earth Engine is not authenticated..." and ends "Original error (ValueError): could not convert string to float: 'abc'". `ee.Initialize calls: 0`: the parse (`auth.py:112-120`) is inside the broad `try` and fails before Initialize. |
| F6 | CONFIRMED-BY-READING | `backend/src/main.py:82` `scheduler.shutdown(wait=True)`; the comment says the wait is bounded by the GEE deadline only. |
| F7 | CONFIRMED-BY-READING | `scan.py:49` module constant `NORMAL_MAX_SCENE_AGE_DAYS = 14`, used at `scan.py:172-182` and in `_source_metadata` (~line 111); not read from config or env. |
| F8 | CONFIRMED-BY-READING | `scan.py:54`-area: `STALE_RUN_HOURS = 1` (`scan.py:~44-47`, used at `scan.py:226`) is fixed; the bootstrap path is not bounded by it. Only the constant and its use were checked, not the bootstrap loop. |
| F9 | CONFIRMED-BY-READING | `global.css:2075` `.raster-scan-banner { top: 174px; max-height: min(60%, 560px); }` vs `.raster-legend { bottom: 16px; left: 16px }` (line 2048); same left column, so the banner and legend can overlap on short viewports. No browser run. |
| F10 | CONFIRMED-BY-READING | `render.py:497-512`: pixels without a finite value and valid date stay `rgba=OUTSIDE_RGBA` and alpha 0 (counted as `no_data_pixels` / `transparent_pixels`); unmeasured water is transparent. `git diff HEAD` on `backend/tests/test_raster_scan_render.py` shows removed tests: `test_the_no_data_hatch_is_achromatic_and_the_ramp_never_is`, `test_unmeasured_water_inside_the_polygon_is_never_transparent`, `test_every_pixel_is_exactly_one_of_the_three_states`, `test_alpha_alone_says_which_state_a_pixel_is_in`, `test_a_measured_cell_outside_the_polygon_is_still_drawn`, `test_a_low_reading_and_an_unmeasured_cell_are_far_apart_in_colour`. Replacements assert transparency. Those edits are uncommitted user changes. No browser run. |
| F11 | CONFIRMED | `auth.py:~140` and `auth.py:150` call `ee.Initialize` twice per `initialize_ee` (first with `http_transport=initialization_transport`, then `http_transport=None`), followed by `ee.Number(1).getInfo()`. |
| F12 | CONFIRMED-BY-READING | `scientific_status.py:~42-52`: `risk_evaluation_active()` and `signal_anomaly_active()` each call `bridge.load_prediction_config()` on every call. Whether `load_prediction_config` caches internally was not checked. |
| F13 | CONFIRMED | `detection/src/signal_anomaly.py:38-43` hard-codes `MIN_INDEPENDENT_DATES=30`, `MAX_OBSERVATION_AGE_DAYS=14`, `MAD_SCALE=1.4826`, `WATCH_AT_Z=2.0`, `HIGH_AT_Z=3.0`. `_config` (lines 47-70) reads the same values from config and rejects any that differ. `backend/src/scientific_status.py:~19` repeats `>= 30` and `<= 14`. |
| F14 | CONFIRMED | `scheduler.py:180-182`: `bridge.risk_level(...)` (runs detect, reads Sentinel-2) then `fetch_satellite_meta(...)`, which calls `bridge.get_sentinel2_bands` again (`satellite_meta.py:22`) just for `cloud_fraction`. Two reads of the same scene per site. |
| F15 | CONFIRMED-BY-READING | `scan.py:95-98`: `[int(value) for value in np.asarray(arrays[RASTER_DATE_BAND]).tolist()]` builds a Python list over the whole date band (~50k+ cells). |
| F16 | CONFIRMED-BY-READING | `RasterLayerSwitcher.jsx:25-31` already calls `stopPropagation` on `mouseDown`, `doubleClick` and `click`. It does not use `L.DomEvent.disableClickPropagation`, and it does not stop `pointerdown`, `touchstart` or `wheel`. Whether Leaflet receives those was not tested. No browser run. |

## F1 consumers of `total_active_alerts` / `updated_at`

- Frontend: `frontend/src/api/client.js:87-90` defines `getAlerts()` (GET `/api/alerts`). A grep of `frontend/src` finds no caller, so no component reads either field.
- Backend tests: `backend/tests/test_alert_service_latency.py:41-42` asserts only that both keys are present. `backend/tests/test_signal_anomaly_contract.py:104` asserts `total_active_alerts == 0` with the gate off. Line 120 supplies a cached payload with `"total_active_alerts": 1`, and line 135 asserts `payload["total_active_alerts"] == 0` after the gate turns off.
- Adding an optional status field is safe for these consumers.

## F2 detail

- Status column: `RasterScanRun.status`.
- Error value: the string `"error"`.
- `trigger.py` never checks it, so an errored run still consumes `trigger_scene_timestamp`.
