# backend

FastAPI service for `/risk-map`, `/risk-map/{site_id}/image`, `/timeseries`,
`/detect`, `/satellite-image`, `/summary`, `/regional-scan`, and alerts.
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
Active tables store monitored sites, their latest detection cache, and regional
scan runs/points/clusters. Startup permanently drops the retired
`validation_events` and `validation_cache` tables if an older database has them.

## Runtime behavior

The scheduler refreshes the fixed monitoring grid every
`SCHEDULER_INTERVAL_MINUTES` (default 360) and once at startup. `/risk-map` and
`/summary` read that cache; `/detect` and `/satellite-image` call Earth Engine on
demand. Every response carries a disclaimer.

No spectral-index anomaly statistic currently exists. Detection endpoints return
real index values and actual scene dates with `spatial_anomaly_z: null`; risk
levels and scan tiers are unavailable. `/timeseries` remains a separate,
dimensionally valid comparison of MODIS `chlor_a` with a `chlor_a` baseline.
