# Test Baseline, Anomaly Pins and Latest-Scene Policy — Design Spec

Date: 2026-10-09 · Status: draft for review · Amends `2026-10-09-academic-dashboard-design.md` §4.6 (pins)

## 1. Intent

The user asked for (a) a **temporary baseline, found from data, to test with and to use as the criterion for now**, (b) **pins at the locations that meet the condition**, and (c) **always use the latest image whenever that day's scene passes the cloud mask criterion**.

This spec delivers all three while keeping the project's truth boundary (CLAUDE.md §0): the baseline is a **TEST baseline** — statistical, provisional, uncalibrated — and what it produces is an **anomaly against the location's own seasonal history**, never a bloom diagnosis and never a validated risk tier.

## 2. What the data search found (probe run 2026-10-09)

Sentinel-2 SR Harmonized, same cloud classes and water mask as production (`sentinel2._cloud_flag_image`, `_water_mask_image`, 30 m buffer, cloud fraction ≤ 0.5, ≥ 1 water pixel), 2017-03-28 → 2026-10-09:

| Site | Usable acquisition dates | First | Last |
|---|---|---|---|
| bangsaen | 307 | 2017-12-13 | 2026-09-29 |
| siracha | 301 | 2017-12-23 | 2026-09-22 |
| thachin_mouth | 290 | 2017-12-13 | 2026-10-07 |
| chaophraya_mouth | 292 | 2017-12-13 | 2026-10-07 |
| chaam | 269 | 2017-12-23 | 2026-09-29 |
| bangpakong_mouth | 305 | 2017-12-13 | 2026-10-02 |
| pattaya | 276 | 2017-12-23 | 2026-09-29 |

Per calendar month the count ranges 8–44, so a one-month season bucket fails the 30-date floor in Jul–Sep; a **±1 calendar-month window (3 months centred on the target month)** gives ≥ 35 at every site in every month (worst cases from the probe: Cha-am Sep window Aug+Sep+Oct = 35; Bang Saen Aug window = 43). Probe artefacts: `scratchpad/probe_history.json`; the probe script is the prototype for the builder in §4.

## 3. Method (existing, unchanged)

`detection/src/signal_anomaly.py::assess_signal_anomaly`: `robust_z = (NDCI_now − median) / (1.4826 · MAD)` over the daily medians of compatible history; **watch at z ≥ 2, high at z ≥ 3** (provisional engineering boundaries, not validated Noctiluca thresholds); floors of 30 independent dates and ≤ 14-day-old imagery. Nothing in that module is loosened. Output vocabulary is `normal | watch | high` + `None` with a reason.

## 4. Baseline artefact and builder

### 4.1 Scope (two levels, built in this order)

- **Level A — 7 monitoring sites (committed scope).** One history per `site_id`: rows `{location_id, season_key, preprocessing_signature, acquisition_date, ndci}` exactly as `assess_signal_anomaly` expects.
- **Level B — per-cell baseline raster (conditional).** Gated on a feasibility spike (§9): per-cell `median`, `MAD`, `n_dates` of NDCI for each season window at the raster's own sampling (200 m, one nearest-neighbour native pixel per cell — the same sampling as production cells, otherwise the baseline is incompatible), built with the raster pipeline's `_index_bands` so masking is identical. Cells with `n_dates < 30` get **no baseline** (no assessment, never a default).

### 4.2 Season key

`season_key = "m{M}±1"` where `M` is the target month; history for that key = acquisitions whose calendar month is in `{M−1, M, M+1}` (cyclic). Documented on `/methods`.

### 4.3 Preprocessing signature

`preprocessing_signature` = short hash over a canonical JSON of: collection id, bands, cloud classes, `max_cloud_fraction`, water-mask rule (JRC min occurrence), `buffer_m`/`scale_m`, sampling mode (point-buffer mean vs raster nearest-neighbour), index definition id. Built from the live pipeline constants, so **any preprocessing change makes the baseline incompatible** (`incompatible_preprocessing`) rather than silently reused.

### 4.4 Artefact

`backend/data/baselines/<baseline_version>/` (gitignored, like `backend/data/rasters/`):

- `manifest.json`: `baseline_kind: "test"`, `baseline_version` (`TEST-YYYYMMDD-<sig8>`), `built_at`, `history_start`, `history_end`, per-location counts, `preprocessing_signature`, `season_rule`, `location_specific: true`, `season_specific: true`, `history_before_target_only: true`, builder git SHA, source collection ids and GEE project-agnostic query parameters, **and a self-check** (§4.5).
- Level A: `sites.json` (history rows). Level B: `cells_<season>.npz` (median, mad, n).

`history_end` must be earlier than every observation it is later used on; an observation acquired on or before `history_end` is assessed with the existing leave-future-out rule (strictly earlier history only), so the artefact can never leak the target.

### 4.5 Self-check (verifiability)

The builder replays every historical date of each location through the **production** `assess_signal_anomaly` using only strictly earlier history and records, per location and season: dates assessable, share flagged `watch`, share flagged `high`, and the share with `zero_mad`/insufficient dates. These base rates are shown on `/methods` ("how often this criterion fires on past data") so a reader can see the criterion's false-alarm rate rather than trust it.

### 4.6 Builder CLI

`python -m scripts.build_test_baseline --level A [--since 2017-03-28] [--out …]` (backend venv, needs GEE). Idempotent per `baseline_version`; refuses to write a baseline whose any location has `< 30` independent dates in any season window (reports which). Rebuild is manual or by a monthly scheduler job behind the same env flag (not enabled by default).

## 5. Activation and labelling

- **Off by default.** Without `BASELINE_MODE=test` nothing changes: `signal_anomaly_active()` stays false, all anomaly fields stay null.
- With `BASELINE_MODE=test` **and** a valid artefact (manifest present, signature matches the live pipeline, `history_end` ≤ today): the existing gate function `_signal_anomaly_active` is evaluated on the **manifest's declarations** (same floors and checks, no loosening) and `signal_anomaly_active()` returns true. **`risk_evaluation_active()` stays false** — there are no calibrated risk rules — so `risk_level` remains null everywhere.
- Every response that carries an anomaly value also carries `baseline: {kind:"test", version, built_at, history_start, history_end, season_rule, min/median independent dates, base_rates_url}`. A missing/invalid artefact in test mode yields `baseline: {kind:"test", valid:false, reason}` and anomaly fields stay null.
- UI: a persistent banner on every page while a test baseline is in use — TH: "บรรทัดฐานทดสอบ (TEST): ค่าผิดปกติเทียบกับประวัติของตำแหน่งเดียวกัน ยังไม่สอบเทียบกับเหตุการณ์จริง ไม่ใช่การประเมินความเสี่ยงบลูม" / EN equivalent. Anomaly chips read "Anomaly vs own history (TEST)", never "risk". Tiers use neutral hatching + text, never the `--risk-*` colours (still reserved).

## 6. Pins that meet the condition

Amends dashboard spec §4.6.

- **Condition:** robust z ≥ 2 (`watch`) or ≥ 3 (`high`) against the active test baseline, on a **measured** cell/site of the served run, with imagery ≤ 14 days old.
- **Level A (sites):** the 7 site markers carry the anomaly chip; sites meeting the condition get a numbered pin ordered by z.
- **Level B (cells):** pins at cells meeting the condition, ranked by z (tie-break z, then NDCI, then row, then column), greedy non-maximum suppression (default 3 km, N default 5, 3–10), each with `robust_z`, `median_ndci`, `mad`, `n_dates`, `level`, NDCI and the other indices, acquisition date, `edge_of_no_data`, run_id, baseline version. Caveat text unchanged (sediment, shallow bottom, glint, cloud edges).
- **Not met / not assessable:** no pin; the panel says how many measured cells were assessable, how many lacked baseline (`n_dates < 30`), and how many met the condition (so "no pins" is distinguishable from "nothing assessed").
- **Fallback:** when no test baseline is active the dashboard shows the *highest-NDCI* pins (dashboard spec §4.6) with their own label. The two pin kinds are never mixed on one map and use different marker shapes and legend entries.
- API: `GET /raster-scan/highlights?mode=anomaly|ndci` (default `anomaly` when a valid baseline is active, else `ndci`); response states `mode`, `baseline` block, cohort/assessable/no-baseline counts; `risk_tier` is always null.

## 7. Latest-scene policy

**Goal:** the served raster and the 7 sites always include the newest acquisition whose cloud criterion passes, promptly.

- **Assessment unit:** one acquisition **date** over the study polygon (all tiles/orbits of that UTC date combined).
- **Criterion:** cloud fraction over the *water* part of the study polygon ≤ `RASTER_SCENE_MAX_CLOUD_FRACTION` (default = `sentinel2.DEFAULT_MAX_CLOUD_FRACTION`, 0.5), computed server-side with the production cloud classes and water mask at the raster scale (same masking functions, no second definition); also requires ≥ `RASTER_SCENE_MIN_WATER_PIXELS` unmasked water pixels (default 1000) so an all-masked scene cannot "pass".
- **Poll:** `poll_and_maybe_scan` (default every 1 h, was 3 h; `RASTER_SCAN_POLL_INTERVAL_HOURS`) lists acquisition dates newer than the last *used* scene date, assesses each not yet assessed (newest first), and records the decision.
- **Trigger:** the newest *passing* date newer than the last used date starts a raster scan **immediately** — the 20 h cooldown no longer applies to a qualifying new scene; a minimum interval `RASTER_SCAN_MIN_INTERVAL_HOURS` (default 1) only prevents thrash. The same trigger refreshes the 7 sites so that sites and raster describe the same acquisition. An errored scan does not mark its date used (retry next poll, bounded by the min interval).
- **Rejected scenes:** logged as assessed with `decision="rejected_cloud"` and the measured fraction; they do not consume a trigger and do not block older usable data; the previous raster keeps being served. They are re-assessed only if their assessment failed (GEE error), not every poll.
- **Mosaic unchanged:** the raster remains a per-cell newest-valid-pixel composite inside the scene-age window, so the newest passing scene automatically wins wherever it is valid and older scenes only fill its gaps (each cell keeps its own date).
- **Storage:** table `scene_assessments(acquisition_date PK, cloud_fraction, water_pixels, decision, reason, assessed_at, used_in_run_id NULL)`; additive migration in `db.py` following the existing pattern.
- **API/UI:** `/raster-scan` gains `latest_scene: {acquisition_date, decision, cloud_fraction, threshold, used_in_run_id}`; Overview and Map show "Newest acquisition 2026-10-08 — used (cloud 12 % ≤ 50 %)" or "— not used (cloud 83 % > 50 %); showing earlier data".
- **Failure honesty:** if the poll cannot reach GEE, the UI shows the age of the last successful poll; it never implies "no newer scene exists".

## 8. Truth boundary additions

1. A test baseline's anomaly is *relative to the location's own 2017-12→history_end record in the same 3-month season*; it does not say a bloom exists, nor its species, nor that a non-anomalous value is safe.
2. The z thresholds are provisional; the base rates from §4.5 are shown beside them.
3. River-mouth and shallow sites have broad NDCI distributions driven by sediment; a wide MAD lowers z — stated on `/methods`.
4. `zero_mad`, `insufficient_independent_dates` and `incompatible_preprocessing` are shown as reasons, never as "normal".
5. Within this spec the word "risk" is not used for baseline output.

## 9. Phases

1. **Builder + artefact + self-check, Level A** (+ tests with a fake GEE client; one live run for the real artefact).
2. **Gate/test-mode integration:** bridge loading, `baseline` block on `/risk-map`, `/summary`, `/detect`; scheduler fills `spatial_anomaly_z`/`signal_anomaly_level` for sites; banner flag in API.
3. **Latest-scene policy:** assessment function (data-pipeline), `scene_assessments`, trigger rewrite, sites refresh on trigger, API/UI fields.
4. **Level B feasibility spike** (GEE compute/time for per-cell median/MAD over a 3-month window × 9 years at 200 m; cell count with `n ≥ 30`); proceed only if a run completes within an acceptable bound, otherwise stay at Level A and say so.
5. **Level B baseline + anomaly pins** (`/raster-scan/highlights?mode=anomaly`).
6. **Frontend:** banner, chips, pins, legend, `/methods` baseline section (merged into the dashboard plan's phases 2–7).

Each phase is tested and committed separately; phases 4–5 are optional on the spike result.

## 10. Testing

- Builder: fake GEE returning scripted histories → exact rows/signature/manifest; refuses `< 30`; self-check numbers match a hand-computed small example.
- Gate: off by default; on only with env + valid manifest + matching signature; `risk_evaluation_active()` stays false; looser manifests rejected (floors).
- Assessment: scripted per-scene stats → pass/reject/min-water cases; multi-tile same-date combination; GEE error leaves the date unassessed.
- Trigger: qualifying new scene bypasses cooldown; rejected scene triggers nothing; errored scan retried after min interval; sites refreshed on trigger.
- Pins: ranking, NMS, tie-break, counts (assessable / no-baseline / met), `risk_tier` null, mode fallback.
- Live (opt-in `--live-gee`): one site built end-to-end; one assessment against today's real scenes.
- Browser: banner on every page in test mode, pins and counts, "not used" scene message.

## 11. Rulings taken on the user's behalf

- Scope = Level A committed; Level B only if the spike passes.
- Season = ±1 calendar month (the narrowest window that meets the 30-date floor everywhere).
- Test mode is env-flag gated, never the default; `risk_level` stays null.
- Cloud criterion reuses the system's 0.5 constant; poll hourly; 1 h minimum scan interval replaces the 20 h cooldown for qualifying scenes.
- Pins use anomaly wording ("anomaly vs own history (TEST)"), not "risk".

## 12. Risks

- GEE compute/time/quota for Level B and the historical builder (the Level A probe took ≈ 90 s total).
- A baseline that includes a past bloom year inflates the MAD and hides future anomalies — shown through the base rates, not corrected.
- Hourly polling cost: one cheap aggregate query per poll; assessments only for new dates.
- Naming drift: `watch`/`high` Thai labels ("เฝ้าระวัง", "ผิดปกติสูง") exist in code; UI must pair them with "(TEST)" and the banner.

## 13. Out of scope

Calibrated risk tiers, bloom/species classification, validation against field events, LINE/push, ML, any change to the locked z boundaries, auto-enabling test mode.
