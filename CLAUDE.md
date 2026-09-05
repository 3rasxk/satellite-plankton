# CLAUDE.md — Gulf of Thailand Algal Bloom Monitor

> How to use: place this file + the `.claude/agents/` folder at the repo root.
> Open Claude Code (Fable 5) and say: "Read CLAUDE.md and all agent files, then build in Build Order."

## 0. Project (do not deviate)

Software-only early-warning system for harmful algal blooms (green *Noctiluca* / red tide) in the upper Gulf of Thailand, targeting SDG 14. **Physics-based, not machine learning.** Two layers + a web app:

1. **Satellite layer** Sentinel-2 (10 m, current detail) + MODIS (~1 km, 2002–present, climatology baseline) via Google Earth Engine.
2. **Detection & prediction layer** Spectral indices (NDCI / 2BDA / 3BDA), reading status and actual scene dates. Anomaly scoring and rule-based risk evaluation are disabled: no valid baseline exists for the indices. MODIS `chlor_a` climatology is valid for `chlor_a` only. No trained model.
3. **Web dashboard** for viewing/inspection — no LINE, no push. Risk shown as colours on a map.

### Why no ML
Public HAB databases (HAEDAT, FWC, HABSOS, PMN — 836K rows) contain **zero usable Thailand coastal records in the satellite era**. Only 14 documented Thai events were recoverable, and those are the validation set, not training data. Florida *Karenia brevis* does not transfer to green *Noctiluca* (different optical mechanism), and self-labelling from a satellite threshold is circular. See `docs/DETECTION_PLAN.md` §0.

### Truth boundary (mandatory in every output — no overclaiming)
- Detection is at **satellite pixel resolution** (Sentinel-2 ~10 m, MODIS ~1 km) — water colour signatures only, never individual organisms.
- Small or dispersed blooms may be **missed**; state this.
- **Detection and prediction are separate claims.** Detection currently returns index readings only, with no valid anomaly statistic or verdict. Prediction cannot evaluate risk while that input is unavailable; it is never a validated forecast. The independent MODIS `/timeseries` calculation compares `chlor_a` with a `chlor_a` baseline and is unaffected.
- The **14 documented Thai events** are a historical record, not a validation gate. 1 of 14 has produced a real satellite reading; 13 cannot, for verified reasons (7 have no coordinate, 4 predate Sentinel-2, 1 coverage gap, 1 total cloud cover). **All 14 cannot be evaluated for detection:** no valid anomaly baseline exists. th_010's former anomaly values mixed units and its claimed miss is withdrawn. Never cite this set as evidence that detection works — or that it fails. Always report **per-event, never as a percentage**.

## 1. Locked decisions (do not propose alternatives unless the human asks)

| Topic | Decided | Rejected |
|-------|---------|----------|
| Approach | Physics: spectral index readings; anomaly scoring and escalation currently disabled | ❌ supervised ML / trained classifier |
| Indices | NDCI, 2BDA, 3BDA, B2/B3 *Noctiluca* discrimination — compare, don't assume | |
| Baseline | MODIS `chlor_a` climatology for `chlor_a` only; no valid spectral-index baseline exists | ❌ comparing dimensionless indices with concentration baselines |
| Primary satellite | Sentinel-2 (10 m) via GEE | |
| Secondary satellite | MODIS via GEE — climatology + SST | |
| Ground truth | 14 documented Thai events — a record, not a pass/fail gate (§0) | ❌ labels derived from a satellite threshold |
| Validation | Leave-one-out over the 14 events, reported per-event | ❌ 70/30 split on self-generated labels |
| Frontend | React (Vite) + Leaflet/MapLibre | |
| Backend | FastAPI (Python) | |
| Alerting | Colours on the map in the web app | ❌ LINE/email push |

## 2. Agents (full detail in `.claude/agents/<name>.md`)

| Agent | Responsibility (short) |
|-------|------------------------|
| `satellite-data` | Sentinel-2 + MODIS pipeline via GEE; band extraction, cloud masking |
| `bloom-detection` | Indices, climatology z-scores, threshold calibration, rule-based prediction |
| `backend-api` | FastAPI: risk-map / timeseries / detect / summary + scheduler + DB |
| `frontend-dashboard` | React web: map + charts + summary (no LINE) |
| `integration-docs` | Assembly, e2e tests, README, LIMITATIONS.md, overclaim guard |

## 3. Build Order

```
[human: GEE approved + authenticated]
        │
        ▼
satellite-data ──► bloom-detection
                        │
                        ▼
                   backend-api
                        ▼
                 frontend-dashboard
                        ▼
                  integration-docs
```

`bloom-detection` depends on `satellite-data` (it needs real band values and MODIS history), so these run in sequence, not parallel.

## 4. What the human must do (agents cannot — remind the user)

1. **Google Earth Engine** — sign up (free for research, needs approval), authenticate locally. If auth fails with an SSL certificate error, a Python from another toolchain (e.g. PlatformIO) is being used — create a clean virtualenv from the system Python instead.
2. **Confirm the 14 Thai events file** — `data/validation/events.csv`, extracted from Luang-on et al. (2023, *Frontiers in Marine Science* 10:1031901), a SEAFDEC-archived 1984 paper, and a 2018 MOAC bulletin. This set is locked — no further data collection is planned. Verify coordinates where the source gives only a place-name.
3. **Study area** — confirmed 2026-08-24 as a real polygon (not an axis-aligned bounding box), stored in `data-pipeline/src/study_area.py` (`STUDY_AREA_POLYGON_LATLNG`). This is a boundary-check only (`check_point_in_study_area`), not a scan area — `/risk-map` does not enumerate points inside it. The actual monitored sites are the fixed, hand-picked list in `backend/src/grid.py` — seven of them (Bang Saen, Si Racha, Tha Chin mouth, Chao Phraya mouth, Cha-am, Bang Pakong mouth, Pattaya), independent of this polygon. This list previously named six sites including upper-Gulf open water; that site is no longer in `MONITORED_GRID`, and Bang Pakong mouth and Pattaya were added, so `GET /` reporting `total_sites: 7` is correct.
4. **Supabase/DB keys** + hosting account.
5. **Review thresholds and escalation rules** in `detection/src/config.yaml` — accept or change.

## 5. Shared conventions

- Repo: `/data-pipeline` `/detection` `/backend` `/frontend` `/docs`
- Validation dataset lives in `/data/validation/` — see `data/validation/README.md` for the schema. `data/validation/events.csv` is the single file other agents read; `data/validation/thailand/` (source subfolders + `REPORT_THAILAND.md`) is a citation archive only, not read by any agent. **This set is fixed at 14 events — no further data collection is in scope.**
- Config via env vars + `.env.example` only — never commit secrets.
- Every module has a docstring stating data source + limitations.
- Comments/docs may be English; identifiers in English.

## 6. Definition of Done

- [ ] Sentinel-2 + MODIS pipeline pulling real data for the upper Gulf
- [ ] All three indices implemented, with per-event results published for the 14 documented events — a record, not a pass/fail gate (§0)
- [ ] MODIS `chlor_a` climatology used only for `chlor_a`; spectral-index anomaly scoring explicitly disabled
- [ ] Leave-one-out status **reported honestly**: 7 of 14 have a coordinate and 1 has a satellite reading, but all 14 cannot be evaluated without a valid anomaly baseline; `calibrated_*` remains null
- [ ] Rule-based prediction layer with every rule readable in config
- [ ] Web: map + click-to-chart + summary page
- [ ] LIMITATIONS.md states the truth boundary; no percentage claims on n=14; no overclaiming
- [ ] README reproducible from scratch

## 7. Common commands

Full setup from a clean clone (three Python venvs + frontend) is in `README.md` "Setup from a clean clone" — read it first if any of this fails. Quick reference:

```bash
# full dev stack: backend :8000 + frontend :5173, one Ctrl-C stops both
./scripts/dev.sh

# or run each by hand
cd backend  && source venv/bin/activate && uvicorn src.main:app --reload
cd frontend && npm run dev
```

Tests — three separate pytest suites, each with its own venv, no live GEE credentials required (GEE is mocked/bypassed at typed boundaries):

```bash
cd data-pipeline && ./venv/bin/python -m pytest tests/ -q   # 82 tests
cd detection      && ./venv/bin/python -m pytest tests/ -q   # 59 tests
cd backend        && ./venv/bin/python -m pytest tests/ -q   # 130 tests
```

Single test: `./venv/bin/python -m pytest tests/test_climatology.py::test_name -q` (run from the relevant subproject directory, with its venv active).

Frontend lint/build (root `package.json` proxies the same scripts via an npm workspace, so these also work unprefixed from the repo root):

```bash
cd frontend && npm run lint     # oxlint — no Python formatter/linter is configured anywhere in this repo
cd frontend && npm run build    # vite build
cd frontend && npm run preview
```

Regenerate `detection/reports/*` from a live run (slow, needs real GEE auth):

```bash
cd detection && source venv/bin/activate && python src/generate_reports.py
```

Runs locally only. There is no deployed instance: the Render backend and Vercel frontend were dropped on 2026-09-05, and `render.yaml`/`vercel.json` deleted with them. Render's free tier destroyed the SQLite database on every idle spin-down (measured: `first_refresh` went from `state: "complete", sites_attempted: 7` back to `state: "not_started", sites_attempted: 0`, with a 53-second cold start), so the deployed copy re-ran its whole scheduler and recomputed `/validation` live on every wake, and served superseded code besides. For demos, `scripts/dev.sh` plus one tunnel to `:5173` is enough — Vite proxies `/api` to the backend (see `frontend/vite.config.js`), so only one port needs exposing and there is no rebuild per demo.

## 8. Architecture: cross-project import bridges

`data-pipeline/`, `detection/`, and `backend/` are separate projects with separate venvs by design (§5), but at runtime each imports the previous one's `src/` **directly**, via `importlib.util.spec_from_file_location` under a namespaced module name — not a package install. This is necessary because `data-pipeline/src` and `detection/src` are both literally named `src` and would collide in `sys.modules` under a plain import.

- `detection/src/_data_pipeline.py` loads `data-pipeline/src/__init__.py` as `data_pipeline_src`, re-exporting `get_sentinel2_bands`, `get_modis_chlorophyll_history`, `get_modis_sst`, `get_rainfall_proxy`, `day_of_year_climatology`.
- `backend/src/_detection.py` loads `detection/src/prediction.py` / `thresholds.py` as `detection_src_prediction` / `detection_src_thresholds`.

Consequence: `detection/venv` and `backend/venv` each need the *full* transitive dependency chain installed directly (`earthengine-api`, `numpy`, `PyYAML`), even where the importing project's own `requirements.txt` doesn't list them — see each subproject's README "Cross-project import(s)" section.

Request flow: frontend (React/Vite) → `backend/src/routers/*.py` → `backend/src/_detection.py` bridge → `detection/src/prediction.py`'s `detect()` / `risk_level()` → `detection/src/_data_pipeline.py` bridge → `data-pipeline/src` GEE calls. `backend/src/scheduler.py` runs this same chain on a timer (`SCHEDULER_INTERVAL_MINUTES`, default 360) for the fixed 6-site grid (`backend/src/grid.py`) and caches results — plus pre-rendered true-color/NDCI PNGs — in the `detection_cache` table; `/risk-map` and `/summary` read that cache and never call GEE live. `/detect` and `/satellite-image` call the chain live, on demand.

DB defaults to local SQLite (`backend/data/app.db`, gitignored) via `backend/src/config.py`; swapping to Postgres/Supabase is a single `DATABASE_URL` env var — `src/db.py`/`src/db_models.py` never branch on which DB is in use beyond one SQLite-only `connect_args` line.

## 9. Known inconsistency — do not extend without asking

`backend/ensemble_service.py`, `backend/train_dual_models.py`, `backend/forecast_service.py`, and `backend/models/*.joblib` (a RandomForest + XGBoost soft-voting ensemble, trained via `sklearn`) exist in the tree — duplicated at repo root too (`ensemble_service.py`, `tests/test_ensemble_service.py`, etc.) — and are now **fully orphaned: nothing in `backend/src/` imports them at all**. Until the startup-cost work, `backend/src/main.py`'s startup hook imported the ensemble inside a failure-swallowing try/except; that import always failed (`AttributeError`, then `ModuleNotFoundError: No module named 'backend'`), never loaded a model, and cost 2.26s of the 3.75s blocking startup, so it was deleted. `backend/tests/test_ensemble_service.py` and the root-level copies still import and exercise these files, so they are covered by tests but reachable from no API route and present in no response. This directly contradicts §0/§1's locked "physics-based, not ML" decision and the explicit rejection of "supervised ML / trained classifier" in the decision table, for the reasons §0 gives (no usable Thai training labels in the public HAB databases). It was introduced in commit `b15af00` ("...integrate dual-model ensemble..."). Treat it as orphaned/experimental, not part of the shipped detection pipeline — do not wire it into the API or build on it without the human explicitly overriding §0/§1 first.
