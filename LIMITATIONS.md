# Limitations

Read this before interpreting dashboard or API output.

## Truth boundary

- Detection reports real Sentinel-2 spectral index values and each point's
  actual scene date. No valid baseline exists for those indices, so no anomaly
  statistic or presence/absence verdict is computed.
- `signal_anomaly_level` is a separate nullable statistical-signal field. It is
  not a synonym for `risk_level`; both remain null in production today.
- Rule-based escalation depends on that unavailable anomaly statistic and
  therefore cannot currently evaluate bloom risk.
- `/timeseries` is separate and dimensionally valid: it compares MODIS
  `chlor_a` with a MODIS `chlor_a` climatology.

Every API response carries a disclaimer, and detection and prediction fields
remain structurally separate.

## Sensor and interpretation limits

**MODIS resolution.** The MODIS `chlor_a` series is a Level-3 mapped product
sampled on its ~4.6 km grid (the API reports 4638 m), not the instrument's ~1 km
native pixel. A MODIS reading describes an area of that size, so it says little
about features near the coast or smaller than a grid cell.

**Small blooms may be invisible.** A bloom smaller than, dispersed within, or
below a sensor pixel can produce no detectable surface signal. Absence of an
index signal is not evidence that no bloom exists.

**Cloud is a hard stop.** Optical sensors cannot see through cloud. The system
reports `no_imagery` rather than inventing or silently substituting data.

**A reading is only as current as its own scene date.** Every reading comes from
the newest *usable* image on or before the date asked about, up to 14 days old
by default; past that the system reports no imagery instead of a staler value.
Cloud makes that limit bite hard in the southwest monsoon. A 2026-09-06
measurement of the now-retired 501-point sampler found only 74 points with a
scene that recent, and 221 more only at 19 days. The raster leaves missing cells
fully transparent. Absence of a reading means "no recent usable image here",
never "no bloom here". Each measured cell carries its own scene date, never the
requested target date.

**A clicked cell is one pixel, not an area.** The raster view reports the
reading stored for the single 10 m pixel that was sampled for that cell, at
200 m spacing by default — not an average of the 200 m square it appears to
fill on screen. A feature smaller than the sampling interval is hit or missed
depending on where the sample landed, so a low reading in one cell is not
evidence about the water beside it. Each cell carries its own acquisition
date, and adjacent cells routinely come from different scenes.

**Unmeasured is not zero.** Water inside the study area with no usable
observation is reported as `not_measured` and drawn fully transparent, never as
a reading or the bottom colour of the ramp. Click lookup uses the same `run_id`,
stored raster grid, polygon, date-validity mask, and sparse cells as the overlay,
so transparent locations remain queryable. Cloud, land-masking and "no scene
covered it" are one state, not three: the stored raster cannot tell them apart,
and inventing the difference would be a claim the data does not support.

**Turbidity and sediment confound optical indices.** River plumes and shallow
coastal water can resemble a bloom signal. The indices are not species
classifiers. The B2/B3 ratio is exploratory context and has not been validated
as a *Noctiluca* discriminator.

**Near-shore sampling is fragile.** A fixed 30 m buffer around a pier, jetty, or
coastline coordinate can contain land or structure. The pipeline does not move
coordinates or widen buffers to force a usable result.

**Geographic scope is limited.** Nothing is calibrated or claimed to
generalize beyond the upper Gulf of Thailand.

**Prediction is not validated.** The retained rule interface is labelled
`indicative, rule-based -- not a validated forecast`; no lead-time accuracy is
reported.

## No spectral-index anomaly layer is active

The raster scan shows raw indices and per-cell scene dates. Because no valid
spectral-index anomaly statistic exists, there is no active anomaly threshold,
risk tier, or anomaly cluster. The retired 501-point path is no longer run or
shown. Numeric threshold entries in
`detection/src/config.yaml` are inactive placeholders and all `calibrated_*`
values remain null.

The proposed separate UI field is **ระดับความผิดปกติของสัญญาณดาวเทียม**.
Its future statistic is
`robust_z = (current_ndci - median_ndci) / (1.4826 * MAD)`, with provisional
labels `ปกติ` below 2, `เฝ้าระวัง` from 2 inclusive to below 3, and
`ผิดปกติสูง` at 3 or above. Missing or invalid input, imagery older than 14
days, fewer than 30 independent valid acquisition dates, zero MAD, or
incompatible preprocessing yields `ไม่มีข้อมูลประเมิน`. The values 2, 3, and
the 30-date minimum are engineering starting points that require sensitivity
testing. They are not biological thresholds or validated bloom-risk levels.

The repository cannot activate that calculation yet. A valid builder must
persist history for the same location and seasonal bucket, use only acquisition
dates strictly before the evaluated observation, and record a preprocessing
identity covering the same Sentinel-2 product, water/cloud masks, NDCI formula,
grid, resolution, and aggregation. It must exclude missing pixels and collapse
repeat samples to independent acquisition dates. The current database has only
the latest point cache and raster-run files; the existing climatology is MODIS
`chlor_a`, so it cannot supply this history. A concrete next step is an
append-only Sentinel-2 baseline table keyed by cell/location, acquisition date,
season definition, and versioned preprocessing signature, followed by leakage
tests, minimum-history sensitivity analysis, and retrospective comparison with
independent field observations before enabling scheduler output.

## TEST baseline (provisional)

An optional mode, `BASELINE_MODE=test`, is off by default. When on, the backend
computes `robust_z = (current_ndci - median) / (1.4826 * MAD)` of a Sentinel-2
NDCI reading against that same site's (Level A) or 200 m cell's (Level B) own
history, taken from the same calendar month +/- 1 (cyclic) and only from dates
before the evaluated one. Everything it produces is labelled TEST and
`risk_level` stays null.

- **Provisional, uncalibrated.** The boundaries 2 (watch) and 3 (high) are
  engineering starting points, never checked against recorded bloom events. They
  are not biological thresholds.
- **Level A self-check is circular.** The base rates in the build manifest are
  measured on the baseline's own past. For the artefact built 2026-10-09
  (`backend/data/baselines/TEST-20261009-9fc9a022/manifest.json`,
  `self_check.total`): of 2,861 site-date evaluations, 1,706 were assessable
  (60 flagged watch, 123 high, i.e. about 3.5% and 7.2% of the assessable ones)
  and 1,155 had no assessment (`insufficient_independent_dates`). This says how
  often the statistic exceeds 2 and 3 on its own history, not how often it
  coincides with a bloom. See `/methods` for the current artefact.
- **Level B has no self-check.** The per-cell baseline has no equivalent
  base-rate measurement. Cells with too few independent dates get no assessment.
- **Quality screens are developer-chosen, not validated.** Pins exclude cells
  whose NDCI is exactly +/-1 (`|NDCI| >= 1 - 1e-6`, a zero band) and cells where
  a visible band (B4, B3 or B2) is below 50 DN (near-black pixels, where NDCI is
  a ratio of noise).
- **Anomaly is not bloom.** A high z means the value is unusual against that
  location's own history. Suspended sediment and river-mouth plumes, shallow
  bottom, sun glint and cloud edges can all produce it. A bloom can also sit
  inside the normal range.
- **No assessment is not "normal".** The reasons `zero_mad`,
  `insufficient_independent_dates` and `incompatible_preprocessing` mean no
  statistic was computed and are reported as reasons, never as a normal result.
  A wide MAD (river-mouth and shallow sites) lowers z for the same departure.
- **No validation.** No TEST anomaly has been compared with recorded bloom
  events or independent field observations.
- **Pins are descriptive.** The highlight pins are either "highest NDCI" within
  one scan or "anomaly vs own history", never risk. The word "risk" is not used for baseline output.

## Numerical threshold register

These are the scientific, data-quality, and interpretation cutoffs present in
the current code. None is a calibrated Sentinel-2 bloom threshold.

| Value | Purpose | Status |
| --- | --- | --- |
| NDCI `-0.05` to `0.15` | Five-stop raster display domain; values outside clamp to endpoint colours | Active visualization only; never a risk tier |
| Sentinel-2 scene age `14` days | Latest allowed ordinary point/raster observation; first-install bootstrap uses bounded pages of the same width | Active data-freshness rule |
| Bootstrap archive floor `2017-03-28` | Earliest date searched for `COPERNICUS/S2_SR_HARMONIZED` | Active stopping condition |
| SCL classes `0, 1, 3, 7, 8, 9, 10` | No-data, defective, shadow, unclassified, cloud, and cirrus pixels excluded | Active categorical quality mask |
| Cloud fraction `0.5` | Reject a point-scene candidate above 50% invalid/cloud pixels in its sample | Active point data-quality rule; not a raster risk threshold |
| JRC occurrence `50%` | Water classification where JRC has data; ETOPO1 `< 0 m` is fallback only where JRC is missing | Active water mask; not a bloom threshold |
| Point buffer `30 m`, point scale `10 m`, raster scale `200 m` | Sampling geometry defaults | Active engineering settings |
| True-colour stretch `0` to `1500` DN | Human-legibility stretch for B4/B3/B2 | Active visualization only |
| MODIS climatology `±7` days, reliability `n=5` | Day-of-year mean/std window and low-sample reliability flag | Active for MODIS `chlor_a` only; `n<5` is flagged, not discarded |
| MODIS SST age `5` days | Maximum age for contextual SST | Active supporting context only |
| Rainfall lookback `7` days | CHIRPS contextual accumulation | Active supporting context only |
| Trend windows `7` and `14` days; rising slope `>0` | MODIS chlorophyll trend/acceleration context | Active context calculation; cannot activate risk while anomaly is null |
| z `1.5` / `2.0` for NDCI, 2BDA, and 3BDA; escalation z `1.5` / `2.0`, rising trend, SST z `>0` | Old threshold and rule shape | Inactive, uncalibrated legacy placeholders; every `calibrated_*` value is null |
| Robust-z scale `1.4826`, boundaries `2` / `3`, minimum `30` dates | Proposed satellite-signal classifier | Implemented as a pure guarded contract, provisional and inactive in production |
| NDCI mathematical input bounds `-1` to `1` | Reject impossible current/history inputs at the provisional robust-z boundary | Provisional validation guard; inactive in production |
| UI MODIS z colour breaks `0`, `1`, `2` | Colour bucketing for the separate MODIS anomaly strip | Active display convention, not calibrated risk |
| Numeric-confidence breaks `0.33`, `0.66` | Generic translation of an optional numeric confidence value | Active UI formatting only; current prediction supplies a text caveat |
| Ensemble probability `0.35` for a positive decision/Watch and `0.65` for Warning | Thresholds in the duplicated `ensemble_service.py` experiment and its training export | Legacy, uncalibrated, and orphaned; nothing in `backend/src/` imports the model or exposes these tiers |
| Ensemble input guards: chlorophyll-a `0–500`, SST `0–50`, nFLH `-5–10`, POC `0–10,000`, anomaly z `-10–20`, seasonal sine/cosine `-1.01–1.01` | Physical-range rejection in the same model experiment | Legacy orphaned input validation; not detection or risk thresholds |
| Forecast context: chlorophyll change `>0.4` / `≥1.5`, SST `≥31` or change `≥1`, anomaly z `≥0.8` / `≥1.5` | Explanatory text in `backend/forecast_service.py` | Legacy, uncalibrated, and orphaned; the service has no import path from `backend/src/` |
| Forecast arrival/risk: 1-day probability `≥0.60` or z `≥2.5` plus chlorophyll change `≥3`; 3-day `≥0.50` or z/change `≥1.5`; 7-day `≥0.50`; 14-day `≥0.40`; 7-day tiers `0.35` / `0.60` | Heuristic arrival windows and risk tiers in `backend/forecast_service.py` | Legacy, uncalibrated, and orphaned; absent from the API and UI |

There are no active calibrated risk thresholds. NDCI and 2BDA also cannot be
used as two independent confirmations: both are transformations of the same
B5/B4 ratio, since `NDCI = (r - 1) / (r + 1)` for `r = B5/B4`. Rainfall, SST,
and MODIS values remain supporting context unless retrospective validation shows
that they improve detection or reduce false alarms.

The orphaned ensemble and forecast files remain in the working tree because
removing historical experiments was outside this change. Their tests exercise
the files directly, but application startup, routers, scheduler, detection
bridge, database responses, and frontend do not import their outputs.

## Scientific references and transfer limits

Mishra, S. and Mishra, D.R. (2012), “Normalized difference chlorophyll index:
A novel model for remote estimation of chlorophyll-a concentration in turbid
productive waters,” DOI: `10.1016/j.rse.2011.10.016`, used water-leaving
reflectance near 665 and 708 nm. This project uses Sentinel-2 B4/B5 surface
reflectance. Similar wavelengths and formula do not make fitted values or raw
thresholds interchangeable.

Luang-on et al. (2023), “MODIS-derived green Noctiluca blooms in the upper Gulf
of Thailand: Algorithm development and seasonal variation mapping,” DOI:
`10.3389/fmars.2023.1031901`, treated approximately chlorophyll-a ≥ 10 mg/m³ as
bloom water and reported green *Noctiluca* examples around 29–30 mg/m³ (weak),
32–37 mg/m³ (strong), and greater than 1,469 mg/m³ (super bloom). Those are
chlorophyll-a observations and MODIS/in-situ classifications. They are not
Sentinel-2 NDCI thresholds and are not inserted into this raster or API.

## Data-pipeline findings

The MODIS Ocean Color catalog in Earth Engine was measured roughly nine months
behind the present during the 2026-08 build. Historical climatology can still
use the archive, but callers must not assume its newest observation is near real
time.

Google Earth Engine's `reduceRegion(ee.Reducer.toList())` reduces bands
independently and can return misaligned lists when masks differ. The water mask
is therefore applied server-side before a combined mean/count reduction.

JRC Global Surface Water has gaps over open ocean. Treating those gaps as land
discarded real marine pixels. The mask now uses JRC where available and falls
back to NOAA ETOPO1 `bedrock < 0` only where JRC is silent. Against the retained
499-point fixture `data/validation/water_mask_truth.json`, the former mask kept
295 of 400 water points and leaked 1 of 99 land points; the corrected mask keeps
395 of 400 water points and leaks 3 of 99. ETOPO1 is coarse (about 1.85 km at
this latitude), so near-shore fallback readings still deserve caution.

## Plain interpretation

- Read detection output as index values with provenance, not a bloom verdict.
- Treat null anomaly, tier, and risk fields as “not computed — no valid
  baseline exists.”
- Do not convert index magnitude into a probability or confidence score.
- Confirm consequential observations with field sampling or another independent
  source.
