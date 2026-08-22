# Limitations

This document exists so nobody has to ask. It transcribes, in the writer's own words, every limitation `docs/DETECTION_PLAN.md` §8 called out before the build started, plus the real findings this build surfaced along the way that the plan doc did not anticipate. Read this before trusting any output of the Gulf of Thailand Algal Bloom Monitor — the dashboard, the API, or the reports in `detection/reports/`.

## The truth boundary (repeated from `CLAUDE.md`, on purpose)

Two different claims live in this system, and they must never be read as one:

- **Detection** — is there a chlorophyll anomaly at this pixel, right now? Standard remote sensing, high confidence, but still bounded by everything below (resolution, cloud, turbidity).
- **Prediction** — is bloom risk trending up? Rule-based (config.yaml conditions on anomaly z-score, trend, SST, rainfall), explicitly labelled `"indicative, rule-based -- not a validated forecast"` everywhere it's surfaced (API responses, the dashboard). Never a validated forecast, never assigned a lead-time accuracy number.

Every response from the API carries these as separate fields (`backend/src/schemas.py`), never merged into one score, and the backend and frontend both enforce this structurally (see the integration tests added in Phase 5, `backend/tests/test_integration_e2e.py`).

## Limitations anticipated in the plan (`docs/DETECTION_PLAN.md` §8)

**Detection floor — blooms smaller than a pixel are invisible.** MODIS's ~4.6 km Level-3 grid needs a bloom covering a meaningful fraction of that pixel (literature puts this around 13% areal coverage) before it registers at all. Sentinel-2's 10 m resolution shrinks this floor by roughly three orders of magnitude, but does not remove it — a small, dispersed, or very early-stage bloom can still sit entirely inside one pixel's noise.

**Turbid water degrades the indices.** NDCI, 2BDA, and 3BDA were designed against relatively clear open-ocean water. The upper Gulf's own bloom hotspots are river mouths — exactly where suspended sediment is heaviest and these indices are least trustworthy. 3BDA is carried specifically because it corrects for some of this backscatter, but per `detection/reports/index_comparison.md`, this correction has not actually been checked against a real river-mouth bloom event yet (no validation event has a usable coordinate there — see below).

**Clouds are a hard stop, not a soft one.** Optical sensors see nothing through cloud. The upper Gulf's monsoon months carry real blind periods where no usable Sentinel-2 or MODIS reading exists at all — this system reports `no_imagery`/gap status honestly in that case rather than substituting a stale or nearby-date reading silently.

**Surface signal only.** Everything here reads the top few metres of water column. A bloom developing below the surface, or one that has already sunk, produces no signal at all — absence of a satellite anomaly is not the same claim as absence of a bloom.

**Fourteen validation events is a small, imprecise sample.** Results reported against it are indicative, never statistically robust, and are always reported per-event — see below for exactly how small "usable" turned out to be.

**Prediction is rule-based, not a validated forecast model.** It encodes known bloom drivers (rising anomaly, warming SST, recent rainfall) as legible if/then rules in `detection/src/config.yaml`, not a model fit to outcome data. No lead-time accuracy figure is computed or reported anywhere in this codebase — with 14 events (0 matchable, see below), there is no sound way to compute one.

**Sediment plumes can look like a bloom.** A heavy-rainfall sediment plume from any of the four river mouths this system watches (Chao Phraya, Tha Chin, Mae Klong, Bang Pakong) can raise an index without any bloom being present. The rainfall proxy is used as a supporting signal for the prediction layer specifically because of this confounder, not as a substitute for it.

**Geographic scope is the upper Gulf of Thailand only.** Nothing here is calibrated, or claimed to generalize, beyond that area.

## What the build actually found, beyond what the plan anticipated

### 1. Zero of the 14 validation events could be matched to a real satellite reading

This is the single most consequential finding of the whole build, and it changes how every number downstream should be read. `data/validation/events.csv` records where each documented event happened exactly as its source described it — and every one of the 14 sources describes a named place (a beach, a river mouth, a province), not a coordinate. Per `docs/DETECTION_PLAN.md` §3, this project never invents a lat/lng for a place name, so all 14 rows carry `location_precision = named_site` or `province_level`, and `lat`/`lng` are blank for all 14.

One exception was attempted: `th_001` is the only event described at the scale of the whole study area ("upper Gulf of Thailand") rather than a specific site, so a same-scale regional-proxy point was tried as a real check. It found zero Sentinel-2 scenes in a 25-day search window around the event date, and a genuine ~2-month gap in the MODIS `chlor_a` archive spanning the event date — confirmed live during this build, not a bug in the code.

The practical consequence: the leave-one-out threshold sweep in `detection/src/thresholds.py` ran with **zero real (index value, known-outcome) pairs**. The z-score cutoffs in `detection/src/config.yaml` are literature/convention defaults — the same illustrative shape `docs/DETECTION_PLAN.md` itself proposed as an example — not values tuned against real Thai bloom data. This is stated in that file's own header, in `detection/reports/event_table.md`, and in the `/validation` API response's `calibration_caveat` field. Treat every threshold in this system as a starting point pending real coordinate data, not a calibrated result.

See `data/validation/CALIBRATION_NOTES.md` for the methodology decisions this reality forced: same-episode clusters (th_005/006/007, th_009/010 — the same physical bloom reported at multiple nearby sites) must be held out together in any future leave-one-out run, not split; th_012/013/014 are pre-monitoring-era (1981–83) with no cell count in any source and carry lower evidentiary weight; and `cell_count` is stored as literal text (a number, a range, or blank) because several sources gave a range and no single number in that range is more truthful than another.

### 2. The species behind these 14 events mostly are not the *Noctiluca* this system's discrimination feature targets

The B2/B3 ratio (secondary, lower-confidence green-*Noctiluca* discrimination) is specific to *Noctiluca scintillans*'s optical signature. Only 6 of the 14 events are that species. The other 8 span `ceratium_furca`, `karenia_sp` (×2), a diatom (`leptocylindrus_sp`), a mixed *Noctiluca miliaris*/*Ceratium furca* event, a cyanobacterium (`trichodesmium_erythraeum`), and a PSP-causing event (`suspected protogonyaulax sp.`) whose two cross-referenced sources disagree on the casualty count (34 hospitalized/1 death vs. 63 victims — unresolved in the source material, reported as-is rather than picking one). A miss on any of these 8 is not evidence the B2/B3 feature doesn't work; it's a different organism with a different optical signature than the feature was designed for. `detection/reports/event_table.md` carries the `species` column specifically so this distinction is never visually flattened into a single miss/hit count.

### 3. The MODIS Ocean Color catalog on Google Earth Engine runs roughly nine months behind the present

Found live during Phase 2 and reconfirmed while writing this document: a query for the full MODIS-Aqua `chlor_a` history at an upper-Gulf point (13.00, 100.70) on 2026-08-22 returned a most-recent observation dated **2025-11-30** — about 8.7 months old. This is not a per-location gap or a masked-pixel artifact; it appears to be the actual currency of NASA's processed Level-3 product as ingested into this GEE collection at the time of this build. Anything relying on "current" MODIS climatology context (the day-of-year baseline itself is unaffected, since it pools all archive years — but any code path expecting a *recent* MODIS chlorophyll reading) should account for this lag explicitly rather than assume near-real-time coverage. Sentinel-2 is unaffected (its ~5-day revisit is current); this is a MODIS-Aqua-catalog-specific finding.

### 4. A real Google Earth Engine `reduceRegion` gotcha cost real debugging time in Phase 1

`reduceRegion` with `ee.Reducer.toList()` reduces each band of a multi-band image **independently**, dropping masked pixels per band rather than returning positionally-aligned lists across bands. The JRC Global Surface Water `occurrence` band is masked (no data) over any pixel never observed as water, while the Sentinel-2 `SCL` (cloud classification) band is populated everywhere. The result: querying both together at a land/beach point can return a full-length `SCL` list alongside a short or empty `occurrence` list — naively zipping them either raises a numpy broadcast error or, worse, silently misaligns which cloud-mask value corresponds to which water-mask value. `data-pipeline/src/sentinel2.py` now checks the two arrays' lengths explicitly and raises a typed `NoWaterPixelsError` rather than guessing at an alignment. Anyone extending this pipeline to pull another per-pixel band alongside these two should check for the same trap — it does not announce itself as an error, it just silently misaligns data unless checked for.

A related, smaller version of the same class of bug: CHIRPS rainfall extraction needed a 12,000 m sample buffer to reliably return a value near the four river mouths this system watches — the CHIRPS pixel size itself (5,566 m) and an intermediate guess (6,000 m) both returned no value at several tested coordinates, for reasons not fully diagnosed beyond "too small a buffer relative to how CHIRPS's own analysis-ready-data resampling handles coastal/near-coastal pixels." 12,000 m was arrived at empirically (tested across 5 coordinates), not derived from a documented CHIRPS specification.

## What this means, plainly

- **Trust the detection layer's presence/absence signal at face value, within the resolution/cloud/turbidity limits above** — this is standard remote sensing, not a novel or fragile technique.
- **Do not trust the specific threshold values in `config.yaml` as calibrated to Thai conditions.** They are defensible literature defaults, explicitly marked as such, pending real coordinate data for the 14 documented events (or new events with usable coordinates).
- **Do not read any per-event result in `detection/reports/event_table.md` or the `/validation` endpoint as a hit/miss rate.** With 0 of 14 events currently matchable, there is no rate to report, and none is reported anywhere in this codebase — every validation claim is per-event, by design.
- **Treat the prediction layer's output as a legible, inspectable set of triggered rules, not a probability.** `triggered_rules` tells you exactly which conditions fired; nothing in this system computes or displays a confidence percentage for that outcome.
