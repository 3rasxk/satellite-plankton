# Gulf of Thailand Algal Bloom Monitor

Software-only early-warning system for harmful algal blooms (green *Noctiluca* / red tide) in the upper Gulf of Thailand, targeting SDG 14. Physics-based (spectral indices + MODIS climatology + rule-based risk escalation) — no machine learning. See `CLAUDE.md` for the full spec and `docs/DETECTION_PLAN.md` §0 for why ML was rejected.

Full reproduce-from-scratch instructions land in Phase 5, written by the `integration-docs` agent. This stub will be replaced then.

## Layout
- `data-pipeline/` — Sentinel-2 + MODIS via Google Earth Engine
- `detection/` — spectral indices, climatology, threshold calibration, rule-based prediction
- `backend/` — FastAPI service
- `frontend/` — React + Leaflet dashboard
- `data/validation/` — the 14-event Thai ground-truth set (locked, see `data/validation/README.md`)
- `docs/` — detection and frontend build plans
