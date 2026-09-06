# Gulf of Thailand Algal Bloom Monitor

Software-only monitoring system for harmful algal blooms (green *Noctiluca* / red tide) in the upper Gulf of Thailand, targeting SDG 14. **Physics-based, not machine learning** — the detection path reports spectral index values with actual scene dates. Anomaly scoring and rule-based risk evaluation are disabled: no valid baseline exists for those indices. MODIS `chlor_a` history and its same-quantity seasonal anomalies remain available separately. See `CLAUDE.md` and `LIMITATIONS.md` for the current scope, and `docs/DETECTION_PLAN.md` §0 for why supervised ML was rejected.

**Read `LIMITATIONS.md` before trusting any output.** The detection path supplies index readings only; it has no valid anomaly statistic or presence/absence verdict. Its prediction rules cannot evaluate risk without that input.

## Layout

```
data-pipeline/   Sentinel-2 + MODIS + rainfall via Google Earth Engine
detection/       spectral indices, MODIS climatology, rule-based prediction
backend/         FastAPI service + scheduler + SQLite/Postgres DB
frontend/        React + Leaflet dashboard
data/validation/ water-mask regression fixture
docs/            detection & frontend build plans
scripts/dev.sh   one-command local dev run (backend + frontend)
```

## Setup from a clean clone

### 0. Prerequisites

- **Python 3.11+**, installed via **Homebrew or the system installer — not whatever `python3` happens to already be on `PATH`.** On the machine this was built on, the default `python3` resolved to a PlatformIO/Arduino-bundled Python with an old LibreSSL build, and `earthengine authenticate` failed with an opaque SSL certificate error until the venvs were rebuilt with `/opt/homebrew/bin/python3` instead. Run `which python3` first — if it points anywhere under a PlatformIO/Arduino install, don't use it for these venvs. This is real: it happened during this project's Phase 1 build, not a hypothetical.
- **Node 18+** (built and tested against Node 20).
- **A Google Earth Engine account**, approved for the Cloud project you'll use. Sign up at https://code.earthengine.google.com — free for research/nonprofit use, but the approval step is not instant; do this first if you haven't already.
- **Supabase — optional.** No real Supabase project was provisioned for this build. `backend/` runs against a local SQLite file out of the box (`backend/data/app.db`, gitignored) with zero configuration. Swapping to real Postgres/Supabase later is a single environment variable (`DATABASE_URL`) — see `backend/README.md` "DB — SQLite now, Postgres/Supabase later".

### 1. Google Earth Engine auth

```bash
cd data-pipeline
/opt/homebrew/bin/python3 -m venv venv        # NOT the PATH-default python3 — see prerequisite above
source venv/bin/activate
pip install -r requirements.txt
earthengine authenticate
```

- **If `earthengine authenticate` fails with an SSL certificate error:** the active Python resolves to a non-system toolchain (PlatformIO/Arduino's bundled Python is the confirmed culprit on the reference machine — it ships an old LibreSSL). Run `which python3` to check, then recreate the venv with your Homebrew/system Python (`/opt/homebrew/bin/python3` on Apple Silicon, confirmed clean with OpenSSL 3.x). Do not work around this with `--trust-env` flags or disabled cert verification — fix the interpreter, not the symptom.
- **Newer GEE accounts require a registered Cloud project.** Set `EE_PROJECT_ID` in `data-pipeline/.env` (copy from `.env.example`) to the project id registered at https://code.earthengine.google.com.
- `detection/.env` needs the same `EE_PROJECT_ID` (it falls back to `../data-pipeline/.env` if its own `.env` is absent, but an explicit copy avoids surprises).
- Every module that talks to GEE guards itself with a typed `GEEAuthError` (`data-pipeline/src/auth.py`) — a missing/expired credential fails loudly with a fix-it message at request time (surfaced by the API as an HTTP 503), never as fabricated satellite data.

### 2. Install each subproject

`data-pipeline`, `detection`, and `backend` are **three separate Python projects with three separate venvs** (by design — see `CLAUDE.md` §5), even though `detection` and `backend` both import code from the others directly at runtime (via `importlib`, not package installs — see `detection/README.md` and `backend/README.md` "Cross-project imports").

```bash
# data-pipeline (done above if you followed step 1)

# detection — needs data-pipeline's own dependencies too, since
# detection/src/_data_pipeline.py imports data-pipeline/src directly
cd detection
/opt/homebrew/bin/python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt -r ../data-pipeline/requirements.txt
cp .env.example .env   # set EE_PROJECT_ID, or rely on the data-pipeline/.env fallback

# backend — needs earthengine-api/numpy/PyYAML too, for the same reason
# (see backend/requirements.txt's own comment on this)
cd ../backend
/opt/homebrew/bin/python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # blank is fine — falls back to local SQLite

# frontend
cd ../frontend
npm install
cp .env.example .env   # VITE_API_BASE_URL=/api by default -- Vite proxies it to :8000
```

### 3. Run the dev stack

```bash
./scripts/dev.sh
```

Starts the backend (`uvicorn src.main:app --reload`, port 8000) and frontend (`npm run dev`, Vite — default port 5173, auto-increments if taken) together. The script checks dependencies and Earth Engine configuration; satellite-backed endpoints return a clear 503 when authentication is unavailable.

Once running:
- API: http://localhost:8000 (interactive docs at `/docs`)
- Dashboard: http://localhost:5173 (watch `scripts/dev.sh`'s own log output for the actual port Vite picked)

The dashboard opens on the full upper-Gulf sampling grid (501 points at the
default 5 km spacing), without threshold filtering. Click any pin for all four
available indices, its status, and its actual scene date. Before a scan has
saved results, the grid is still visible with `no_data_yet` and null readings;
the browser checks the cache every 30 seconds, without triggering imagery
requests. The named monitoring-station layer is not shown on this map.
Every satellite reading in the system — the regional grid, `/detect`, the
scheduler's site cache, and the true-color / NDCI thumbnails beside them — comes
from the newest usable image acquired **on or before** the day being asked
about, never one acquired after it. How old that image may be before the system
gives up and reports no data is the one thing configurable about it:
`SENTINEL2_MAX_SCENE_AGE_DAYS` in `data-pipeline/.env`, 60 days by default.
Each pin keeps its own scene date and shows its age against the scan target, so
a 3-day-old reading and a 5-week-old one are never presented as the same thing.
Nothing usable inside the ceiling means a no-data pin — not a relaxed cloud
mask, not a made-up index value.

Expect the dates to differ pin to pin, and to be old in the monsoon: on the
2026-09-06 scan of 501 points, 295 returned a reading, 221 of them from a single
clear pass on 2026-08-18, because every later acquisition over that water was
fully clouded.

If you'd rather run the two processes by hand instead of the script (e.g. to see each one's logs in its own terminal):

```bash
# terminal 1
cd backend && source venv/bin/activate && uvicorn src.main:app --reload

# terminal 2
cd frontend && npm run dev
```

### 4. Run the tests

```bash
cd data-pipeline && ./venv/bin/python -m pytest tests/ -q
cd detection      && ./venv/bin/python -m pytest tests/ -q
cd backend        && ./venv/bin/python -m pytest tests/ -q
cd frontend       && npm test
```

The service suites need no live GEE credentials; external calls are mocked or bypassed at typed boundaries.

## Manual end-to-end verification

The stack has been manually exercised against real Earth Engine-backed data. Automated service suites mock or bypass external calls at typed boundaries; frontend lint, unit tests, and production build are separate gates.

## What's not automated

Frontend tests cover map bounds, unevaluated monitoring pins, and rendering all
regional grid statuses and per-point readings. Regional components are rendered
with only the browser-dependent Leaflet/API boundaries stubbed; real map
interaction coverage remains limited, so UI changes still need a browser check
against the running API.

## Design decisions, locked

See `CLAUDE.md` §1 for the full decision table.
