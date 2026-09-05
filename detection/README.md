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
- `src/climatology.py` — MODIS `chlor_a` per-location/per-day-of-year mean+std, valid for comparison with `chlor_a` only.
- `src/thresholds.py` — event matching against `data/validation/events.csv` + leave-one-out reporting (11 iterations: 9 single events + 2 same-episode clusters). **7 of 14 events have coordinates; 1 (th_010) has a satellite index reading; all 14 cannot be evaluated for detection.** Anomaly scoring is explicitly disabled with `z_score_status: not_computed_no_valid_baseline`. th_010's former miss claim rested on a calculation mixing incompatible units and is withdrawn — see `LIMITATIONS.md` §1.
- `src/prediction.py` — `detect(lat, lng, date)` reports real index values, reading status and actual scene date, with no anomaly score or detection verdict. `risk_level` cannot evaluate risk while its anomaly input is unavailable.
- `src/config.yaml` — retained threshold/rule shapes are inactive placeholders; every `calibrated_*` remains null until a valid statistic exists and can be calibrated.
- `src/generate_reports.py` — regenerates `reports/event_table.md`, `reports/index_comparison.md`, `reports/threshold_sweep.png` from a live run (real GEE calls). Run it with:
  ```bash
  source venv/bin/activate && python src/generate_reports.py
  ```
