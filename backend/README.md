# backend

FastAPI service — `/risk-map`, `/risk-map/{site_id}/image`, `/timeseries`, `/detect`, `/satellite-image`, `/summary`, `/validation` — + scheduler. Owned by the `backend-api` agent — see `.claude/agents/backend-api.md`. Wraps `detection/src`'s `detect()`/`risk_level()` (Phase 2) in HTTP responses — no detection/prediction logic lives here.

`/detect` and `/satellite-image` render a true-color/NDCI-heatmap satellite image on demand (live GEE call, several seconds — no small enumerable key space to cache). `/risk-map`'s fixed 6-site grid instead gets its images pre-rendered and cached by the scheduler alongside the numeric refresh, then served from the DB in milliseconds via `/risk-map/{site_id}/image` — see `src/scheduler.py`'s module docstring for the real, measured-latency reasoning behind that split.

## Setup

```bash
cd backend
/opt/homebrew/bin/python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in real Supabase keys later; blank is fine for now (see below)
uvicorn src.main:app --reload
```

Requires `detection/` and `data-pipeline/` to exist as sibling directories with their own `.env` files carrying `EE_PROJECT_ID` (see `data-pipeline/.env.example`) — `backend/src/_detection.py` loads `detection/src/prediction.py`/`thresholds.py` directly (see "Cross-project imports" below), which transitively load `data-pipeline/src`'s GEE-authenticated functions.

`backend/requirements.txt` includes `earthengine-api`, `numpy`, `PyYAML` in addition to the FastAPI/DB stack — these are transitive runtime dependencies of the detection/data-pipeline import chain, not backend's own logic. `backend/` has its own venv (CLAUDE.md §5: separate projects, separate venvs), so it needs these installed directly, same as `detection/venv` needed `earthengine-api` even though `detection/requirements.txt` doesn't list it.

## Cross-project imports

`backend/` needs to call into `detection/src`, which itself calls into `data-pipeline/src` — three separate projects, two of which are both named `src`. `detection/src/_data_pipeline.py` already solved the `detection/` → `data-pipeline/` collision via `importlib.util.spec_from_file_location` under an explicit module name. `backend/src/_detection.py` replicates the same pattern for `backend/` → `detection/src`: it loads `prediction.py` and `thresholds.py` directly from `detection/src/*.py` under namespaced module names (`detection_src_prediction`, `detection_src_thresholds`), rather than letting them (or their own `_data_pipeline`/`climatology`/`indices` imports) register under bare names in `sys.modules`. No detection/prediction logic is duplicated — every function `backend/` calls is the exact object from `detection/src`.

## DB — SQLite now, Postgres/Supabase later

No real Supabase project exists yet (`backend/.env.example`'s `SUPABASE_URL`/`SUPABASE_KEY`/`DATABASE_URL` are blank) — a real gap, not a shortcut. Leaving `DATABASE_URL` unset makes `src/config.py` fall back to a local SQLite file at `backend/data/app.db` (gitignored), so the full DB-backed flow — schema, scheduler cache writes, `/risk-map`, `/summary` — can be built and tested now.

**To swap to real Supabase/Postgres:** set `DATABASE_URL` to a real connection string (e.g. `postgresql+psycopg2://postgres:<password>@<host>:5432/postgres`) in `.env`. That is the entire swap — `src/db.py`/`src/db_models.py` never branch on "is this sqlite" (the one SQLite-specific line is `connect_args={"check_same_thread": False}` in `src/db.py`, applied only `if config.DATABASE_URL.startswith("sqlite")`). You would need to add `psycopg2-binary` to `requirements.txt` for a real Postgres URL to work — not added yet since there's nothing to connect to.

Tables (`src/db_models.py`):
- `monitored_sites` — the grid `/risk-map`/`/summary`/the scheduler operate over (`src/grid.py`, 6 points, upserted at startup). Not the validation set.
- `detection_cache` — one row per site, upserted by the scheduler with the latest `risk_level()`/`detect()` result. `/risk-map` and `/summary` read this, never GEE live. `stale` + `error` distinguish "last refresh failed, this is old data" from "this is fresh." Also carries `true_color_png`/`ndci_heatmap_png` (BLOB, pre-rendered PNG bytes) + `image_status`/`image_error`, refreshed on the same cycle — see `src/scheduler.py`.
- `validation_events` — mirrors `data/validation/events.csv` (14 rows), upserted read-only at startup. Never written to via any API route.
- `validation_cache` — caches `thresholds.run()`'s output (`/validation`'s data source) for `VALIDATION_CACHE_TTL_HOURS`, since `run()` makes a real, slow GEE call.

## Scheduler

`src/scheduler.py`'s `refresh_grid()` job runs on `SCHEDULER_INTERVAL_MINUTES` (default 360 = 6h; satellite imagery doesn't update faster than that) and also fires once immediately at startup. Each site's refresh is independently guarded — a failure (network blip, `GEEAuthError`, anything) logs and marks that site's cache row `stale=True` with an `error` message, leaving every substantive field (including `fetched_at`) untouched, so a stale row never silently looks fresh.

## Endpoints

### NDCI Watch overlay

`GET /watch-overlay` is cache-only. The scheduler refreshes one whole-upper-Gulf Sentinel-2 overlay per cycle and stores its tile URL plus source-window, newest-scene, resolution, threshold, stale, and error metadata. A browser reload never calls Earth Engine. Failed refreshes preserve the last-good tile as stale; no usable imagery returns no tile and an explicit status.

This indicative NDCI watch signal (`z >= 1.5`) is not bloom confirmation, salinity measurement, species inference, concentration estimation, or a validated forecast. It uses a 30-day latest clear-image window, five prior seasonal years at ±15 days, cloud/SCL filtering, Gulf-connected historical surface water, and no 14-day trend. Only orange qualifying pixels are opaque; everything else is transparent. The output grid is 10 m, with 20 m effective NDCI source resolution, and a mosaic may contain pixels from different dates.

See `.claude/agents/backend-api.md` and `docs/FRONTEND_PLAN.md` §3 for the contract. Every response model carries a `disclaimer` field (enforced via Pydantic, visible in `/docs`). Detection (`detect()`) and prediction (`risk_level()`) fields are always kept in separate parts of the response shape — never merged into one score.
