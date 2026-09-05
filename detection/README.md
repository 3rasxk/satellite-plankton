# detection

Physics-based bloom detection & prediction engine (indices, climatology, thresholds, rules). Owned by the `bloom-detection` agent — see `.claude/agents/bloom-detection.md`. No ML — see `docs/DETECTION_PLAN.md` §0.

## Setup

`detection/` and `data-pipeline/` are separate projects with separate venvs (CLAUDE.md §5). `detection`'s venv also needs `data-pipeline`'s own dependencies (`earthengine-api`, etc.) installed into it, because `src/_data_pipeline.py` imports `data-pipeline/src` directly at runtime rather than duplicating any GEE code:

```bash
cd detection
/opt/homebrew/bin/python3 -m venv venv   # NOT the PlatformIO python3 on PATH — see CLAUDE.md §4.1
source venv/bin/activate
pip install -r requirements.txt -r ../data-pipeline/requirements.txt
earthengine authenticate   # if not already done for data-pipeline
```

`EE_PROJECT_ID` is read from `detection/.env` (falls back to `../data-pipeline/.env` if absent) — see `.env.example`. Both are gitignored.

## Cross-project import

`detection/src/` and `data-pipeline/src/` are both literally named `src`, so a plain `sys.path` + `import src` would collide if both were ever imported in one process. `detection/src/_data_pipeline.py` loads `data-pipeline/src/__init__.py` via `importlib.util` under the unambiguous name `data_pipeline_src` instead, and re-exports the four public functions (`get_sentinel2_bands`, `get_modis_chlorophyll_history`, `get_modis_sst`, `get_rainfall_proxy`) plus `day_of_year_climatology` and the two typed data-unavailability errors. No data-pipeline logic is duplicated — every name is the original object from `data-pipeline/src`.

## Modules

- `src/indices.py` — NDCI, 2BDA, 3BDA, B2/B3 (green *Noctiluca* discrimination, secondary/lower-confidence).
- `src/climatology.py` — MODIS `chlor_a` per-location/per-day-of-year mean+std, anomaly z-score.
- `src/thresholds.py` — event matching against `data/validation/events.csv` + leave-one-out calibration (12 iterations: 10 events + 2 same-episode clusters, per `data/validation/CALIBRATION_NOTES.md` §1). **Headline finding: 7 of 14 events carry a real coordinate; 1 of 14 (th_010) has produced a real satellite reading.** One matched pair is not a calibration set, so thresholds stay literature defaults — see `reports/event_table.md` and `LIMITATIONS.md` §1.
- `src/prediction.py` — `detect(lat, lng, date)` and `risk_level(lat, lng, date)`, the public handoff functions for `backend-api`. Rule-based escalation (`elevated`/`watch`/`warning`) read entirely from `src/config.yaml`.
- `src/config.yaml` — every threshold and rule, human-readable. Its own header explains why the z-score cutoffs are literature defaults, not empirically calibrated (see thresholds.py finding above).
- `src/generate_reports.py` — regenerates `reports/event_table.md`, `reports/index_comparison.md`, `reports/threshold_sweep.png` from a live run (real GEE calls). Run it with:
  ```bash
  source venv/bin/activate && python src/generate_reports.py
  ```
