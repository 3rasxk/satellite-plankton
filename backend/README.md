# backend

FastAPI service for `/risk-map`, `/risk-map/{site_id}/image`, `/timeseries`,
`/detect`, `/satellite-image`, `/summary`, `/raster-scan`, and alerts.
It imports the physics-based detection engine through `src/_detection.py`;
no detection logic is duplicated here.

## Setup

```bash
cd backend
/opt/homebrew/bin/python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn src.main:app --reload
```

`detection/` and `data-pipeline/` must remain sibling projects. The backend
virtual environment needs their transitive runtime dependencies because the
bridge loads `detection/src/prediction.py` directly.

## Database

With `DATABASE_URL` unset, the service uses the gitignored SQLite database
`backend/data/app.db`. Set `DATABASE_URL` to switch to Postgres/Supabase.
Active tables store monitored sites, their latest detection cache, and raster
scan runs. Old regional scan tables are retained as read-only history. Startup
permanently drops the retired `validation_events` and `validation_cache` tables
if an older database has them.

## Runtime behavior

The scheduler refreshes the fixed monitoring grid every
`SCHEDULER_INTERVAL_MINUTES` (default 360) and once at startup. `/risk-map` and
`/summary` read that cache; `/detect` and `/satellite-image` call Earth Engine on
demand. A separate hourly poll applies the latest-scene policy: each new
Sentinel-2 acquisition date is assessed for cloud over the polygon's water, and
the newest passing date newer than the newest date already used starts a raster
scan at once (then the seven sites refresh). A cloudy date starts nothing and
the previous raster keeps serving. An assessment made under 36 h after the date
began (UTC) is flagged unsettled. The 20 h cooldown now gates only the
first-install bootstrap. Raster blobs expire after 30 days by default while
their run rows and summaries remain. Every response carries a disclaimer.

Environment variables for this flow (defaults; see `.env.example`):

| Variable | Default | Meaning |
| --- | --- | --- |
| `RASTER_SCENE_MAX_CLOUD_FRACTION` | 0.5 (blank) | Max cloud-flagged share of water pixels for a date to pass (set in `data-pipeline/.env`) |
| `RASTER_SCENE_MIN_WATER_PIXELS` | 1000 (blank) | Min observed water pixels for a date to be assessable (`data-pipeline/.env`) |
| `RASTER_SCAN_POLL_INTERVAL_HOURS` | 1 | How often the poll runs |
| `RASTER_SCAN_MIN_INTERVAL_HOURS` | 1 | Minimum time between scan attempts (spaces retries) |
| `RASTER_SCAN_COOLDOWN_HOURS` | 20 | First-install bootstrap only |
| `RASTER_BOOTSTRAP_BUDGET_MINUTES` | 45 | Wall-clock budget of the bootstrap archive search |
| `BASELINE_MODE` | off | `test` enables the provisional TEST seasonal baseline |
| `GEE_REQUEST_TIMEOUT_SECONDS` | 120 (blank) | Earth Engine request deadline (`data-pipeline/.env`) |

`BASELINE_MODE=test` uses the artefact built by
`cd backend && ./venv/bin/python ../scripts/build_test_baseline.py --level AB`
(`--level B --replace` rebuilds the cell baseline; needs GEE, about 6-8 min).
`GET /methods` and `GET /raster-scan/highlights` are served in either mode.

Set `SCHEDULER_ENABLED=false` for processes that must serve the API without
starting background jobs. Production defaults to enabled. Application shutdown
waits for an active job to finish; Earth Engine API requests have a finite
deadline so this wait cannot be held forever by one stalled network read.

Ordinary backend tests disable scheduling and skip the two live Earth Engine
checks:

```bash
./venv/bin/python -m pytest tests/ -q
./venv/bin/python -m pytest tests/test_satellite_image.py --live-gee -m live_gee -q
```

By default no active spectral-index anomaly statistic exists. (With the gated, provisional `BASELINE_MODE=test` the anomaly fields may be filled from the TEST baseline; `risk_level` stays null.) Detection endpoints
return real index values and actual scene dates with `spatial_anomaly_z: null`,
`signal_anomaly_level: null`, and `risk_level: null`. A nullable database/API
field and a pure robust-z validation boundary exist for future use, but the
production scheduler does not populate them because it has no compatible
Sentinel-2 history. `/timeseries` remains a separate, dimensionally valid
comparison of MODIS `chlor_a` with a MODIS `chlor_a` baseline.
