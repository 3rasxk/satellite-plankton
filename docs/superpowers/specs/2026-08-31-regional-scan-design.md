# Full-polygon regional bloom scan — design spec

> Correction, 2026-09-06: the anomaly and tier portions of this historical design are superseded. `detect()` returns raw indices and actual scene dates only. Its former comparison against MODIS `chlor_a` mixed units and is removed. `spatial_anomaly_z` is a null placeholder, not a replacement statistic; tiers are null and the scan produces no anomaly clusters. The threshold/cluster examples below describe the withdrawn design and are not current implementation instructions. See `LIMITATIONS.md` §1 and `docs/DETECTION_PLAN.md` §2.

Status: approved, not yet implemented. Written 2026-08-31, after three design
revisions (whole-polygon/24h-timer → whole-polygon/event-driven-poll+cooldown
→ per-tile partial scanning considered and explicitly deferred). This
document reflects the final approved design only; see "Deferred" (§10) for
what was considered and rejected, and why.

## 0. What this is, and what it is not

This reopens a prior scope decision: `data-pipeline/src/study_area.py`'s
`STUDY_AREA_POLYGON_LATLNG` was, until now, a boundary-check constant only
("is this point inside the study area?") — never a scan area. This design
adds the first real scan over that polygon: a periodic, event-triggered grid
of real Sentinel-2 readings across the whole upper Gulf, output as
individual and clustered map pins.

It does **not** touch, weaken, or replace:
- `backend/src/grid.py`'s fixed 6-site monitoring grid, or `/risk-map`.
- `study_area.py`'s `check_point_in_study_area` boundary-check use in
  `/detect`.
- The unvalidated Ang Sila spatial-trend test (a separate, prior
  experiment) — this scan's output must be labeled distinctly from it in
  the API response (see §7).

Every value this feature ever plots comes from a real, live Sentinel-2
query via the existing `detect()` pipeline. No point is ever fabricated,
interpolated, or filled in from a neighbor — a point with no valid reading
(cloud, land-masked, no MODIS climatology at that location/date) is stored
and returned with its real status, never silently dropped.

## 1. Grid generation

A regular lat/lng grid at **5 km spacing** is generated across the
polygon's bounding box, then filtered to points actually inside
`STUDY_AREA_POLYGON_LATLNG` via the existing `point_in_polygon` function.
Measured against the real polygon (bounding box 120.6 km E-W × 123.2 km
N-S): **500 in-polygon points**.

Backend has no existing import bridge to `data-pipeline/src` (only
`detection/src` does, via `detection/src/_data_pipeline.py`). This adds
one small new file, **`backend/src/_study_area.py`**, following the exact
same `importlib.util.spec_from_file_location` namespaced-import pattern
`_data_pipeline.py` already established — not a new mechanism, the same
one this codebase already uses twice.

Grid points are indexed by `(row_idx, col_idx)` at generation time (their
position in the regular pre-filter grid), so adjacency for clustering
(§4) is an O(1) dict lookup, never a distance computation.

## 2. Per-point extraction — reuses `detect()`, unchanged

For every grid point, `detect(lat, lng, date)` — the existing public
function from `detection/src/prediction.py`, reached via the existing
`backend/src/_detection.py` bridge — is called exactly as-is. No
detection/prediction logic is duplicated or reimplemented. Its return
(`index_values` for NDCI/2BDA/3BDA, `spatial_anomaly_z`, `status`) is stored
per point.

**Measured real cost** (live GEE calls, 2026-08-31, `date=2026-08-15`):
a point resolving to real imagery (Sentinel-2 scene found + full MODIS
`chlor_a` climatology pull) took **25.8s**; a point failing fast on
`no_imagery` took **6–10s**. Blended estimate for a mixed grid: **~15s/point
average, 8–26s range**. For 500 points: **~2.1 hr average per full scan,
1–3.6 hr range**.

## 3. Threshold tiers — reuses `config.yaml`, no new numbers

A point is tiered using the exact `elevated_z`/`warning_z` cutoffs
(1.5/2.0) already governing every other rule in this project
(`detection/src/config.yaml`):
- `spatial_anomaly_z >= warning_z` → tier `warning`
- `spatial_anomaly_z >= elevated_z` (but below `warning_z`) → tier `elevated`
- otherwise → untiered (not flagged, not pinned individually)

## 4. Clustering — grid-adjacency connected-components

Flagged points (`status == 'ok'` and tiered `elevated`/`warning`) whose
`(row_idx, col_idx)` differ by ≤1 in both directions (8-connectivity) merge
into one cluster via union-find over the `{(row,col): point}` dict — O(n),
deterministic, no tunable parameter, no new dependency. (DBSCAN was
considered and rejected: its `eps`/`min_samples` would be an unvalidated
parameter with no real spatial ground-truth to tune against, the same
"no calibration data" problem `config.yaml` already documents for the
z-score thresholds — and it would add `scikit-learn` as a new backend
dependency, currently pulled in only by the orphaned, unwired
`ensemble_service.py` files flagged in `CLAUDE.md` §9.)

Each cluster stores: centroid (mean of member lat/lng), `cell_count`,
`mean_spatial_anomaly_z`/`max_spatial_anomaly_z` (computed only over real, `status='ok'`
member cells — a no-data cell is never counted or averaged in), and
`threshold_tier` (the highest tier among its members). Member point ids
are stored as a JSON list for traceability back to individual readings.

## 5. Trigger model — event-driven poll, with a cooldown floor

**Not** a blind fixed-interval timer. A cheap, frequent poll job checks
for new Sentinel-2 imagery anywhere in the polygon; only a real new scene
triggers the expensive full scan, and a cooldown floor prevents that from
converging into near-continuous scanning.

**The poll query** (measured, live, 2026-08-31):
```python
ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
  .filterBounds(polygon)
  .filterDate(since, now)
  .aggregate_max('system:time_start')
```
A single server-side metadata query — no per-point loop, no pixel
reduction. **Measured: 0.75s.** That is ~10,000x cheaper than the scan it
gates (2.1 hr ≈ 7,560s).

**Scene arrival rate** (measured, live, 16-day window 2026-08-15 to
2026-08-31): 32 distinct Sentinel-2 scenes intersected the polygon,
spanning 6 UTM tile columns — confirms different parts of the polygon get
new scenes on different days, roughly 2 new scenes/day system-wide.

**Why a cooldown floor is necessary, not optional**: at that arrival rate,
a trigger on "any new scene anywhere" with no floor would fire roughly
daily at minimum and could fire more than once a day — worse than the
fixed-timer design this replaces, not better, given a single scan costs
1–3.6 hr. True "scan the instant relevant data lands" is not the right
target at this scene-arrival density.

**Final design**: poll every **3 hours** (8x/day, ~6s/day total polling
cost — negligible). Trigger `run_scan()` only when **both**: (a) the
poll's max scene timestamp is newer than the last completed run's stored
`newest_scene_date`, **and** (b) at least **20 hours** have elapsed since
the last run started (cooldown floor).

Net effect vs. the fixed-24h-timer design it replaces: latency from
"new scene lands" to "scan starts" drops from up to 24h to at most ~3h;
during a genuine cloud-siege stretch with no usable new scene for days,
**no scan runs at all** — a real saving an all-cloud blind-timer scan
could not avoid (that would still burn ~500 × 6–10s ≈ 3,000–5,000s of
GEE calls for a scan that finds nothing).

## 6. Data model (new tables, `backend/src/db_models.py`)

- **`regional_scan_runs`** — one row per run (history kept; small rows,
  cheap): `started_at`, `completed_at`, `status`
  (`running`/`ok`/`partial_error`/`error`), `grid_spacing_km`,
  `date_used`, `newest_scene_date` (the max scene timestamp considered as
  of this run — read by the poll job as the comparison baseline for the
  *next* trigger decision), `total_points`, and per-outcome counts
  (`ok`/`no_imagery`/`no_water_pixels`/`no_climatology`/`error`).
- **`regional_scan_points`** — latest-run snapshot, upserted (not
  appended) on each successful run, matching the existing `detection_cache`
  overwrite-latest pattern: `lat`, `lng`, `row_idx`, `col_idx`, `status`,
  `index_values` (JSON: ndci/2bda/3bda), `spatial_anomaly_z`, `threshold_tier`.
  No-data points are stored with their real status, never omitted.
- **`regional_scan_clusters`** — latest-run snapshot: `centroid_lat`,
  `centroid_lng`, `cell_count`, `mean_spatial_anomaly_z`, `max_spatial_anomaly_z`,
  `threshold_tier`, member point ids (JSON list).

## 7. New endpoint — `GET /regional-scan`

Pure cache read — never calls GEE live, same convention as `/risk-map`
and `/summary`. Returns the latest run's metadata, all points (including
no-data ones), and clusters. Carries the standard `disclaimer` field plus
an explicit `caveat` labeling this a **detection scan** (current anomaly
state from real Sentinel-2 data), distinct from the unvalidated Ang Sila
spatial-trend test — the two outputs must never be blurred together in
the response or the frontend.

## 8. Scheduler / job architecture

A new APScheduler job (`max_instances=1`, `coalesce=True`) runs the poll
every 3h, independent of the existing `refresh_grid` (6h, 6-site grid)
and watch-overlay jobs — this job's own scan phase can take up to 3.6 hr
and must never block those faster jobs. It does **not** fire immediately
at process startup (unlike `refresh_grid`) — a job that can run for hours
firing on every `--reload` dev restart would be unworkable.
`max_instances=1` on this job also doubles as overlap protection: if a
triggered scan is still running when the next 3h poll tick fires, that
tick is skipped rather than stacking.

For manual testing without waiting on the poll/cooldown cycle, a small
CLI script, **`backend/scripts/run_regional_scan.py`**, calls the same
`run_scan()` the scheduler calls — mirrors the existing manual-trigger
pattern in `detection/src/generate_reports.py`.

New env-overridable constants in `backend/src/config.py`, following the
existing `SCHEDULER_INTERVAL_MINUTES` convention:
`REGIONAL_SCAN_GRID_SPACING_KM` (default `5`),
`REGIONAL_SCAN_POLL_INTERVAL_HOURS` (default `3`),
`REGIONAL_SCAN_COOLDOWN_HOURS` (default `20`).

## 9. Error handling

`detect()`'s own contract already converts ordinary failure modes
(`no_imagery`/`no_water_pixels`/`no_climatology`) into status fields, never
exceptions — those are stored as-is per point, nothing new needed.
`GEEAuthError` is the one exception `detect()` deliberately never catches
(its docstring: means the whole pipeline is unusable, not that one
reading is unavailable). `run_scan()` catches it once at the top level
and aborts the entire run as `status='error'`, rather than limping through
hundreds of doomed calls. Any other unexpected exception is caught
per-point (mirroring `scheduler.py`'s existing per-site guard in
`refresh_grid`) and stored as that point's `error` status, without
killing the run.

## 10. Frontend

A new map layer (individual + cluster markers, Leaflet, reusing
`RiskMap.jsx`'s existing setup) showing real NDCI/2BDA/3BDA/`spatial_anomaly_z`
values in each pin's popup — never a colored dot with no data behind it,
per the no-fabrication rule. A last-scanned/stale banner reuses the
existing disclaimer pattern already used elsewhere in the dashboard.
Scoped as its own component; does not touch the existing 6-site grid,
`RiskMap.jsx`'s existing markers, or any existing endpoint.

## 11. Testing

Grid generation and adjacency-clustering are pure functions,
unit-testable without GEE, matching this repo's existing convention
(`data-pipeline`/`detection`/`backend` suites all mock or bypass live
Earth Engine at typed boundaries). `run_scan()`'s and the poll job's
GEE-calling paths are tested the way `scheduler.py`/`detect()` already
are: mocked/bypassed at the typed boundary, not against live GEE.

## 12. Deferred — per-tile partial scanning

Considered and explicitly rejected for this iteration (not "not thought
of" — evaluated with real numbers and rejected on complexity-to-benefit
grounds):

Scanning only the sub-region (S2 tile) with new imagery, rather than the
whole polygon on every trigger, would cut sustained point-level GEE call
volume by an estimated 65–70% (measured scene-arrival pattern: ~1 update
per tile per ~3 days × 6 tiles ≈ 165 points/day vs. the current ~500/day)
and would shrink worst-case per-trigger duration from ~3.6 hr to ~36 min
(83 points/tile × 26s worst-case).

It was rejected because: (1) this feature has not shipped in any form
yet — this is the third design revision without a line of code written;
(2) the problem this would additionally solve (worst-case trigger
duration) is a known, bounded risk under the approved design (3.6 hr,
not unbounded), not an active problem; (3) it introduces real new
complexity this codebase has never needed before — S2/MGRS tile-footprint
handling, a schema shift from clean snapshot-per-run to per-point
upsert-with-provenance, and non-trivial correctness work; and (4) most
importantly, it introduces a genuine truth-boundary risk: a cluster
spanning a tile boundary could merge a just-updated point with a
several-days-stale one under a single, undifferentiated pin, unless
every cluster is given a real freshness range and that range is surfaced
in the API response — exactly the kind of quiet overclaim this project's
disclaimer/truth-boundary discipline (`LIMITATIONS.md`, the `disclaimer`
field on every response) exists to prevent.

Revisit if, once this design is running in production, real observed
behavior (rate-limit errors, an actual need for sub-hour freshness) shows
it is needed — evidence over projection, the same stance this project
already takes on the "no ML, no usable labels" and "0/14 events reported
honestly" decisions.
