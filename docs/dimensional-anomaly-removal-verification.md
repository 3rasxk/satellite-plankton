# Removal of invalid spectral-index anomaly scores

Verified on 2026-09-06 against the changes following
`dd03d563044c1e2478b877605787bdc5405f1e82` on `feature/regional-scan`.

`detect()` now returns real index values, reading status and the actual
Sentinel-2 scene date. It does not call climatology or compute an anomaly
statistic. API and cache fields reserved as `spatial_anomaly_z` are null;
`detected`, risk levels and scan tiers are also unavailable. Scans produce
no clusters. A real index reading remains `status: ok` even without a
climatology baseline.

Validation explicitly returns `z_scores: null` and
`z_score_status: not_computed_no_valid_baseline`. All 14 events and all
11 held-out units (9 single events plus 2 episode clusters) cannot be
evaluated. th_010 is neither a hit nor a miss. Its real index reading,
2020-02-16 scene date, and all three reading qualifiers are retained.
The corrected checked-in reports retain previously recorded readings;
they do not claim that a new live validation run occurred.

## What broke and what changed in the tests

- The first detection run after removing the dependency reported
  `5 failed, 54 passed in 0.53s`. All five failures patched the removed
  `prediction.build_climatology` symbol in `test_detect_actual_date.py`.
  These were rewritten to prove that no climatology or score function
  is called, while real index values, error statuses and actual dates
  survive. The pure climatology math tests required no changes.
- Prediction rule-parser fixtures use the future `spatial_anomaly_z`
  name. A new regression test exercises real rule evaluation with rising
  chlorophyll and warm SST and requires unavailable risk, no fired rules
  and no detection verdict.
- Integration assertions requiring `anomaly_z == 2.75`, numeric anomaly
  values, a risk enum, or a detected summary were replaced with the null
  contract, retained indices/dates, and `not_evaluated` summary counts.
  The scheduler integration fixture now mocks its image-render boundary;
  the session-visibility race was not changed.
- Scan tests expecting warning tiers and clusters now require null
  scores/tiers and empty clusters. Mixed per-point scene dates are still
  checked through persistence and the HTTP response. Pure clustering
  tests retain explicitly synthetic future-statistic inputs.
- New cache tests prove legacy scores and false validation results are
  discarded without backfill; source sites and validation-event records
  survive, and a second startup preserves new index-only caches.

## Executed verification

Each Python command ran from its own service directory and virtualenv.

```text
data-pipeline: ./venv/bin/python -m pytest tests/ -q
82 passed in 0.43s

detection: ./venv/bin/python -m pytest tests/ -q
66 passed in 3.92s

backend: ./venv/bin/python -m pytest tests/ -q
131 passed, 2531 warnings in 27.37s
exit 0

backend: ./venv/bin/python -m pytest tests/test_cache_schema_reset.py -q
2 passed, 1 warning in 0.06s
```

The backend run includes two existing live satellite-image tests. Its
warnings include dependency/model warnings from orphaned ML tests and
post-summary scheduler logging errors against a closed stream. Those
unrelated issues were not fixed.

A fresh independent reviewer ran the checks with its own shell:
`66 passed` for detection; `131 passed, 2531 warnings in 25.13s`, exit 0,
for backend; frontend build and lint exit 0. The frontend reports three
existing hook-dependency warnings and a bundle-size warning.

The reviewer confirmed no diff in `detection/src/climatology.py`,
`backend/src/routers/timeseries.py`, or `data-pipeline/src/`. The locked
event CSV is unchanged. Documentation about the inactive statistic was
corrected without changing the event data.

Final independent review accepted the scoped change with no remaining
findings after rechecking all five final documentation corrections.
The reviewer also exercised cache reset with foreign keys enabled and
confirmed full source records were preserved without foreign-key violations.
`git diff --check` exited 0 with no output.

A local HTTP `/risk-map` response returned a real open-Gulf reading:
`ndci: 0.040270823935941835`, `actual_date: 2026-09-02`, with
`spatial_anomaly_z`, `detected` and `risk_level` all null. Other sites
reported actual `no_imagery` status. No browser was connected, so visual
UI verification could not be performed.

## Cache change

Startup detects the legacy column names and discards detection and
validation caches, regional point/cluster snapshots, and their run
metadata. Invalid values are never renamed or backfilled. Removing run
metadata prevents old completed-run counts from describing discarded
points. Sites and source validation events remain; disposable readings
can be recomputed. A legacy validation JSON payload is invalidated even
if no legacy SQL score column remains.

No replacement anomaly statistic, raw-index floor, MODIS parallel
detection, minimum-pixel policy, climatology reliability wiring, mask
mirror changes, deployment work or E2E visibility-race fix is included.
