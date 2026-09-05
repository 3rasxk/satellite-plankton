# Gulf of Thailand Algal Bloom Monitor

Software-only monitoring system for harmful algal blooms (green *Noctiluca* / red tide) in the upper Gulf of Thailand, targeting SDG 14. **Physics-based, not machine learning** — the detection path reports spectral index values with actual scene dates. Anomaly scoring and rule-based risk evaluation are disabled: no valid baseline exists for those indices. MODIS `chlor_a` history and its same-quantity seasonal anomalies remain available separately. See `CLAUDE.md` and `LIMITATIONS.md` for the current scope, and `docs/DETECTION_PLAN.md` §0 for why supervised ML was rejected.

**Read `LIMITATIONS.md` before trusting any output.** The detection path supplies index readings only; it has no valid anomaly statistic or presence/absence verdict. Its prediction rules cannot evaluate risk without that input. The 14-event set is a **record of documented blooms, not a validation gate**: one event has a satellite reading, but all 14 cannot be evaluated. th_010's former miss claim rested on an invalid calculation and is withdrawn.

## Layout

```
data-pipeline/   Sentinel-2 + MODIS + rainfall via Google Earth Engine
detection/       spectral indices, MODIS climatology, threshold calibration, rule-based prediction
backend/         FastAPI service (5 endpoints + scheduler + SQLite/Postgres DB)
frontend/        React + Leaflet dashboard
data/validation/ the 14-event Thai ground-truth set (locked scope — see data/validation/README.md)
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

Starts the backend (`uvicorn src.main:app --reload`, port 8000) and frontend (`npm run dev`, Vite — default port 5173, auto-increments if taken) together, backgrounded, with a single Ctrl-C stopping both. The script checks for the three venvs, `frontend/node_modules`, and an `EE_PROJECT_ID` in `detection/.env`/`data-pipeline/.env` before starting, and warns (not fails) if GEE auth looks unset — the backend still boots either way, but every satellite-backed endpoint (`/detect`, `/risk-map` after its first scheduled refresh, `/validation`, `/timeseries`) will return a 503 until auth is fixed, per the never-fabricate-data rule above.

Once running:
- API: http://localhost:8000 (interactive docs at `/docs`)
- Dashboard: http://localhost:5173 (watch `scripts/dev.sh`'s own log output for the actual port Vite picked)

If you'd rather run the two processes by hand instead of the script (e.g. to see each one's logs in its own terminal):

```bash
# terminal 1
cd backend && source venv/bin/activate && uvicorn src.main:app --reload

# terminal 2
cd frontend && npm run dev
```

### 4. Run the tests

```bash
cd data-pipeline && ./venv/bin/python -m pytest tests/ -q   # 28 tests, pure logic, no live GEE needed
cd detection      && ./venv/bin/python -m pytest tests/ -q   # 50 tests, pure logic, no live GEE needed
cd backend        && ./venv/bin/python -m pytest tests/ -q   # 23 tests, TestClient + isolated SQLite,
                                                                # GEE mocked at the bridge boundary
```

101 tests total, all real (no live GEE credentials required to run any of them — GEE calls are mocked or bypassed at a typed boundary, per this project's existing per-file test convention). No automated frontend test suite exists (no Vitest/React Testing Library configured) — see "What's not automated" below.

### 5. Regenerate the detection reports (optional, needs live GEE)

```bash
cd detection && source venv/bin/activate
python src/generate_reports.py
```

Regenerates `detection/reports/event_table.md`, `index_comparison.md`, and `threshold_sweep.png` from a live run against real Sentinel-2/MODIS data and `data/validation/events.csv`. Slow (real GEE round-trips) and requires GEE auth from step 1.

## The 14-event validation set

Lives at `data/validation/events.csv` — 14 documented Thai HAB events (1981–2020), extracted from Luang-on et al. (2023, *Frontiers in Marine Science* 10:1031901), a SEAFDEC-archived 1984 paper, and a 2018 MOAC bulletin. **This set is locked — no further data collection is in scope** (`CLAUDE.md` §4, `data/validation/README.md`).

**Current match status: 1 of 14**, and that one settles nothing — see `LIMITATIONS.md` §1 for the three qualifiers that apply to it together. 7 rows carry a real, human-confirmed coordinate; the other 7 are `named_site` or `province_level`, because the sources describe events by place name and this project never invents a lat/lng for one (`docs/DETECTION_PLAN.md` §3). Of the 7 with coordinates, 4 predate Sentinel-2, 1 hit a coverage gap, 1 was entirely cloud-covered, and 1 (th_010) produces a reading. One regional-proxy attempt (`th_001`, at the scale the source actually supports — "upper Gulf of Thailand," not a named site) found zero Sentinel-2 scenes and a real ~2-month MODIS `chlor_a` gap for that window. See:
- `data/validation/README.md` — schema and folder guide.
- `data/validation/CALIBRATION_NOTES.md` — the methodology decisions this reality forces (same-episode cluster hold-out grouping for leave-one-out, species diversity across the 14 events, historical-event weighting, date-precision tiers, `cell_count` range handling).
- `detection/reports/event_table.md` — the live per-event table, all 14 rows.
- `detection/src/config.yaml` — states plainly that escalation thresholds are literature/convention defaults, not empirically calibrated, and why.
- `GET /validation` — the same table, served live from the running API.

## Manual end-to-end verification

In addition to the 101 automated tests, this build was verified against a real running stack during Phase 5: `scripts/dev.sh` started, backend confirmed serving real GEE-backed data (`/risk-map` returning 6 real monitored-grid readings, `/summary` and `/validation` returning live-computed payloads), and the frontend loaded against the real running backend in an actual Chrome browser (not a mock server) — map rendered, a site marker was clicked, no console errors. The one thing this could **not** confirm: whether the site panel correctly renders as a full-width bottom sheet at a genuine 375px mobile viewport — the available browser-automation tooling in this environment cannot actually shrink the rendered viewport below the desktop breakpoint (confirmed directly: after a resize call, `window.innerWidth` still read 976px). The CSS rule itself (`frontend/src/styles/global.css`, `@media (max-width: 720px)`, `.site-panel` -> full-width slide-up sheet) was read and is logically correct, but this specific behavior remains **unconfirmed by an actual narrow-viewport render** — verify by hand with real Chrome DevTools' device toolbar if this matters for a release.

## What's not automated

There is no Vitest/React Testing Library (or any other frontend unit/component test) set up in `frontend/`. Frontend correctness was instead verified by hand — a real browser driven against the real running backend during Phase 4's build (two real bugs found and fixed that way: a z-index overlap, and a chart incorrectly rendering no-history sites as a flat zero line instead of excluding them) and again briefly during Phase 5 (above). This is a real gap, not a hidden one: a regression in `frontend/src/` today would only be caught by a human looking at the running app, not by `npm test`. Left as-is rather than retrofitted, because introducing a first test framework and a real test suite for five pages/nine components is a project-shaping decision (which pages get real coverage vs. smoke-only, whether to mock the API or run against a test backend) that deserves its own review, not a quick pass at the end of Phase 5.

## Design decisions, locked

See `CLAUDE.md` §1 for the full table (physics not ML, NDCI/2BDA/3BDA/B2-B3, MODIS climatology baseline, 14-event ground truth, leave-one-out validation reported per-event, React+Leaflet, FastAPI, no LINE/push). Not re-litigated here.
