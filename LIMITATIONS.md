# Limitations

Read this before interpreting dashboard or API output.

## Truth boundary

- Detection reports real Sentinel-2 spectral index values and each point's
  actual scene date. No valid baseline exists for those indices, so no anomaly
  statistic or presence/absence verdict is computed.
- Rule-based escalation depends on that unavailable anomaly statistic and
  therefore cannot currently evaluate bloom risk.
- `/timeseries` is separate and dimensionally valid: it compares MODIS
  `chlor_a` with a MODIS `chlor_a` climatology.

Every API response carries a disclaimer, and detection and prediction fields
remain structurally separate.

## Sensor and interpretation limits

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
scene that recent, and 221 more only at 19 days. The raster now marks missing
cells with a grey hatch. Absence of a reading means "no recent usable image
here", never "no bloom here". Each measured cell carries its own scene date,
never the requested target date.

**A clicked cell is one pixel, not an area.** The raster view reports the
reading stored for the single 10 m pixel that was sampled for that cell, at
200 m spacing by default — not an average of the 200 m square it appears to
fill on screen. A feature smaller than the sampling interval is hit or missed
depending on where the sample landed, so a low reading in one cell is not
evidence about the water beside it. Each cell carries its own acquisition
date, and adjacent cells routinely come from different scenes.

**Unmeasured is not zero.** Water inside the study area with no usable
observation is reported as `not_measured` and drawn as a grey hatch, never as
a reading. Cloud, land-masking and "no scene covered it" are one state, not
three: the stored raster cannot tell them apart, and inventing the difference
would be a claim the data does not support.

**Turbidity and sediment confound optical indices.** River plumes and shallow
coastal water can resemble a bloom signal. The indices are not species
classifiers, and the B2/B3 feature is only a secondary, lower-confidence
*Noctiluca* signal.

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
