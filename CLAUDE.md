# CLAUDE.md — Gulf of Thailand Algal Bloom Monitor

> How to use: place this file + the `.claude/agents/` folder at the repo root.
> Open Claude Code (Fable 5) and say: "Read CLAUDE.md and all agent files, then build in Build Order."

## 0. Project (do not deviate)

Software-only early-warning system for harmful algal blooms (green *Noctiluca* / red tide) in the Gulf of Thailand, Thai side, targeting SDG 14 (widened from the upper Gulf on 2026-09-06 — see §4.2). **Physics-based, not machine learning.** Two layers + a web app:

1. **Satellite layer** Sentinel-2 (10 m, current detail) + MODIS (~1 km, 2002–present, climatology baseline) via Google Earth Engine.
2. **Detection & prediction layer** Spectral indices (NDCI / 2BDA / 3BDA), reading status and actual scene dates. Anomaly scoring and rule-based risk evaluation are disabled: no valid baseline exists for the indices. MODIS `chlor_a` climatology is valid for `chlor_a` only. No trained model.
3. **Web dashboard** for viewing/inspection — no LINE, no push. Risk shown as colours on a map.

### Why no ML
No suitable local labelled dataset is active in this repository. Florida *Karenia brevis* does not transfer to green *Noctiluca* (different optical mechanism), and self-labelling from a satellite threshold is circular. See `docs/DETECTION_PLAN.md`.

### Truth boundary (mandatory in every output — no overclaiming)
- Detection is at **satellite pixel resolution** (Sentinel-2 ~10 m, MODIS ~1 km) — water colour signatures only, never individual organisms.
- Small or dispersed blooms may be **missed**; state this.
- **Detection and prediction are separate claims.** Detection currently returns index readings only, with no valid anomaly statistic or verdict. Prediction cannot evaluate risk while that input is unavailable; it is never a validated forecast. The independent MODIS `/timeseries` calculation compares `chlor_a` with a `chlor_a` baseline and is unaffected.

## 1. Locked decisions (do not propose alternatives unless the human asks)

| Topic | Decided | Rejected |
|-------|---------|----------|
| Approach | Physics: spectral index readings; anomaly scoring and escalation currently disabled | ❌ supervised ML / trained classifier |
| Indices | NDCI, 2BDA, 3BDA, B2/B3 *Noctiluca* discrimination — compare, don't assume | |
| Baseline | MODIS `chlor_a` climatology for `chlor_a` only; no valid spectral-index baseline exists | ❌ comparing dimensionless indices with concentration baselines |
| Primary satellite | Sentinel-2 (10 m) via GEE | |
| Secondary satellite | MODIS via GEE — climatology + SST | |
| Frontend | React (Vite) + Leaflet/MapLibre | |
| Backend | FastAPI (Python) | |
| Alerting | Colours on the map in the web app | ❌ LINE/email push |

## 2. Agents (full detail in `.claude/agents/<name>.md`)

| Agent | Responsibility (short) |
|-------|------------------------|
| `satellite-data` | Sentinel-2 + MODIS pipeline via GEE; band extraction, cloud masking |
| `bloom-detection` | Indices, same-quantity climatology, inactive rule-based prediction |
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
2. **Study area** — confirmed 2026-08-24 as a real polygon (not an axis-aligned bounding box), stored in `data-pipeline/src/study_area.py` (`STUDY_AREA_POLYGON_LATLNG`); widened 2026-09-06 from the upper-Gulf quadrilateral to 16 vertices covering the Thai side of the whole Gulf, Bangkok bight to the Malaysian border. Its offshore edge is a hand-drawn approximation, **not** a maritime boundary — it encodes no EEZ, no Thailand–Cambodia overlapping claims area and no Thailand–Malaysia JDA, and must not be cited as any of them. It now serves two purposes: the boundary check (`check_point_in_study_area`) for arbitrary `/detect` queries, and the source of the regional scan grid (`backend/src/regional_scan/grid.py`, ~9,100 points at 5 km). `/risk-map` still does not enumerate points inside it — those are the fixed, hand-picked seven-point list in `backend/src/grid.py`. Widening changed where the system *reads*; it validated nothing anywhere.
3. **Supabase/DB keys** + hosting account.
4. **Review thresholds and escalation rules** in `detection/src/config.yaml` — accept or change.

## 5. Shared conventions

- Repo: `/data-pipeline` `/detection` `/backend` `/frontend` `/docs`
- The retained `data/validation/water_mask_truth.json` fixture tests the water mask; it is not bloom-event ground truth.
- Config via env vars + `.env.example` only — never commit secrets.
- Every module has a docstring stating data source + limitations.
- Comments/docs may be English; identifiers in English.

## 6. Definition of Done

- [ ] Sentinel-2 + MODIS pipeline pulling real data for the Thai-side Gulf
- [ ] All three indices implemented and returned with real scene provenance
- [ ] MODIS `chlor_a` climatology used only for `chlor_a`; spectral-index anomaly scoring explicitly disabled
- [ ] Rule-based prediction layer with every rule readable in config
- [ ] Web: map + click-to-chart + summary page
- [ ] LIMITATIONS.md states the truth boundary; no overclaiming
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
cd data-pipeline && ./venv/bin/python -m pytest tests/ -q
cd detection      && ./venv/bin/python -m pytest tests/ -q
cd backend        && ./venv/bin/python -m pytest tests/ -q
```

Single test: `./venv/bin/python -m pytest tests/test_climatology.py::test_name -q` (run from the relevant subproject directory, with its venv active).

Frontend lint/build (root `package.json` proxies the same scripts via an npm workspace, so these also work unprefixed from the repo root):

```bash
cd frontend && npm run lint     # oxlint — no Python formatter/linter is configured anywhere in this repo
cd frontend && npm run build    # vite build
cd frontend && npm run preview
```

Runs locally only. There is no deployed instance: the Render backend and Vercel frontend were dropped on 2026-09-05. For demos, `scripts/dev.sh` plus one tunnel to `:5173` is enough — Vite proxies `/api` to the backend.

## 8. Architecture: cross-project import bridges

`data-pipeline/`, `detection/`, and `backend/` are separate projects with separate venvs by design (§5), but at runtime each imports the previous one's `src/` **directly**, via `importlib.util.spec_from_file_location` under a namespaced module name — not a package install. This is necessary because `data-pipeline/src` and `detection/src` are both literally named `src` and would collide in `sys.modules` under a plain import.

- `detection/src/_data_pipeline.py` loads `data-pipeline/src/__init__.py` as `data_pipeline_src`, re-exporting `get_sentinel2_bands`, `get_modis_chlorophyll_history`, `get_modis_sst`, `get_rainfall_proxy`, `day_of_year_climatology`.
- `backend/src/_detection.py` loads `detection/src/prediction.py` as `detection_src_prediction`.

Consequence: `detection/venv` and `backend/venv` each need the *full* transitive dependency chain installed directly (`earthengine-api`, `numpy`, `PyYAML`), even where the importing project's own `requirements.txt` doesn't list them — see each subproject's README "Cross-project import(s)" section.

Request flow: frontend (React/Vite) → `backend/src/routers/*.py` → `backend/src/_detection.py` bridge → `detection/src/prediction.py`'s `detect()` / `risk_level()` → `detection/src/_data_pipeline.py` bridge → `data-pipeline/src` GEE calls. `backend/src/scheduler.py` runs this same chain on a timer (`SCHEDULER_INTERVAL_MINUTES`, default 360) for the fixed 7-site grid (`backend/src/grid.py`) and caches results — plus pre-rendered true-color/NDCI PNGs — in the `detection_cache` table; `/risk-map` and `/summary` read that cache and never call GEE live. `/detect` and `/satellite-image` call the chain live, on demand.

DB defaults to local SQLite (`backend/data/app.db`, gitignored) via `backend/src/config.py`; swapping to Postgres/Supabase is a single `DATABASE_URL` env var — `src/db.py`/`src/db_models.py` never branch on which DB is in use beyond one SQLite-only `connect_args` line.

## 9. Known inconsistency — do not extend without asking

`backend/ensemble_service.py`, `backend/train_dual_models.py`, `backend/forecast_service.py`, and `backend/models/*.joblib` (a RandomForest + XGBoost soft-voting ensemble, trained via `sklearn`) exist in the tree — duplicated at repo root too (`ensemble_service.py`, `tests/test_ensemble_service.py`, etc.) — and are now **fully orphaned: nothing in `backend/src/` imports them at all**. Until the startup-cost work, `backend/src/main.py`'s startup hook imported the ensemble inside a failure-swallowing try/except; that import always failed (`AttributeError`, then `ModuleNotFoundError: No module named 'backend'`), never loaded a model, and cost 2.26s of the 3.75s blocking startup, so it was deleted. `backend/tests/test_ensemble_service.py` and the root-level copies still import and exercise these files, so they are covered by tests but reachable from no API route and present in no response. This directly contradicts §0/§1's locked "physics-based, not ML" decision and the explicit rejection of "supervised ML / trained classifier" in the decision table, for the reasons §0 gives (no usable Thai training labels in the public HAB databases). It was introduced in commit `b15af00` ("...integrate dual-model ensemble..."). Treat it as orphaned/experimental, not part of the shipped detection pipeline — do not wire it into the API or build on it without the human explicitly overriding §0/§1 first.
