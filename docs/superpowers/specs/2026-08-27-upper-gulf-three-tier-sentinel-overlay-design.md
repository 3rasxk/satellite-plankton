# Upper Gulf Three-Tier Sentinel-2 Overlay Design

**Date:** 2026-08-27  
**Status:** Approved in chat; pending written-spec review  
**Supersedes for the regional overlay:** the orange-only presentation in
`2026-08-27-upper-gulf-ndci-watch-overlay-design.md`. The earlier document remains
the implementation history for the existing cached overlay.

## Objective

Scan every usable water pixel in the established upper-Gulf scan polygon and
render one cached raster tile with three indicative anomaly levels. Keep normal,
land, cloud, invalid, and insufficient-data pixels transparent. Sample the same
classified raster at the six existing monitored sites and show pins only when a
site has one of the three visible levels.

This is an uncalibrated, rule-based optical warning aid. It is not bloom
confirmation, species identification, salinity measurement, a concentration
estimate, or a validated forecast.

## Confirmed Product Rules

The latest user-approved rules replace the earlier instruction not to use a
14-day trend:

| Internal code | Thai label | Rule | Color |
| --- | --- | --- | --- |
| `elevated` | เริ่มผิดปกติ | NDCI seasonal anomaly `z >= 1.5` | `#34C759` |
| `watch` | เฝ้าระวัง | `z >= 1.5` and 14-day Sentinel-2 NDCI trend is rising | `#FF9F0A` |
| `warning` | เตือนภัย | `z >= 2.0`, trend is rising, and current SST is above its seasonal normal | `#FF3B30` |

The most severe satisfied rule wins. A pixel with `z >= 2.0` but no rising
trend remains `elevated`. A rising pixel with missing SST can reach `watch` but
not `warning`. Missing trend never gets inferred: an otherwise valid
`z >= 1.5` pixel remains `elevated`.

Pixels with `z < 1.5` are computed but transparent. Transparency must never be
described as a confirmed normal reading because it can also mean cloud, land,
invalid reflectance, an unusable baseline, or missing current imagery.

## Geographic Scope and Water/Land Separation

Use the already approved upper-Gulf polygon:

- northwest: `(13.92257500, 99.29500833)`
- northeast: `(13.92548889, 102.57514444)`
- southeast: `(12.06813056, 102.57761667)`
- southwest: `(12.10439444, 99.31681111)`

The static candidate-water mask remains JRC Global Surface Water occurrence at
or above 50%, restricted to water connected to the approved Gulf seed points.
For each Sentinel-2 observation, also require SCL class 6 (`water`). The
intersection separates current water observations from land while retaining
the existing Gulf-connectivity guard against isolated inland water.

This is a remote-sensing water mask, not a salinity or present-day coastline
measurement. It can miss turbid water that SCL does not classify as water and
can include connected estuarine water.

## Sentinel-2 Input and Quality Mask

Use `COPERNICUS/S2_SR_HARMONIZED` and select B2, B3, B4, B5, B6, SCL, and QA60.
Scale surface reflectance bands by `0.0001`.

A Sentinel-2 pixel is usable only when all of these are true:

1. it is inside the connected historical-water mask;
2. SCL equals 6 (`water`);
3. SCL is not defective, cloud shadow, medium/high cloud, cirrus, or snow/ice;
4. QA60 cloud bit 10 and cirrus bit 11 are both clear;
5. B2 through B6 are finite and within the physically usable scaled-reflectance
   range accepted by the implementation;
6. the B5+B4 NDCI denominator is safely above a numerical epsilon.

B4 and B5 determine NDCI. B2, B3, and B6 are retained for quality diagnostics
and validity checks, but they do not add an uncalibrated risk score or override
the approved NDCI/trend/SST rules. No spectral turbidity threshold is invented.

NDCI is:

```text
NDCI = (B5 - B4) / (B5 + B4)
```

B5 is a 20 m source band. The display grid may remain 10 m for alignment and
rendering, but both current NDCI and NDCI trend have 20 m effective source
resolution.

## Current NDCI and Seasonal Anomaly

Keep the existing current-source and baseline contract:

- current search window: latest 30 calendar days ending on the target date;
- current value: latest usable per-pixel NDCI observation;
- baseline: five prior seasonal years, each within +/-15 days of the target
  day-of-year;
- minimum baseline observations: five per pixel;
- zero or near-zero baseline standard deviation: invalid and transparent.

For valid pixels:

```text
z = (latest_ndci - seasonal_mean_ndci) / seasonal_std_ndci
```

The current output can be a per-pixel mosaic of different Sentinel-2 dates.
The API and UI must continue to disclose this.

## Fourteen-Day Sentinel-2 Trend

The trend window is the 14 calendar days ending on the target date. Apply the
same B2-B6, SCL, QA60, and water masks used by the current NDCI path.

Overlapping Sentinel-2 tiles from the same UTC acquisition date are first
reduced to one per-pixel daily NDCI observation so tile overlap cannot satisfy
the observation minimum. A pixel needs at least two distinct usable dates.

Fit NDCI against elapsed days using a per-pixel linear regression:

```text
trend_rising = distinct_date_count >= 2 and ndci_slope_per_day > 0
```

No minimum positive slope beyond zero is claimed because no local calibration
supports one. The API reports the slope, units, date count, and configured
window so the rule remains auditable.

## SST Condition

Use NASA MODIS-Aqua Level-3 mapped SST from
`NASA/OCEANDATA/MODIS-Aqua/L3SMI`.

- current SST: nearest valid daily SST within five days of the target date;
- seasonal normal: mean SST from prior archive years within +/-7 day-of-year;
- warning condition: current SST is strictly greater than the seasonal mean;
- missing current or baseline SST: SST condition is false, never fabricated.

MODIS L3SMI has an approximately 4.6 km grid. Reprojection may align it with the
10 m tile, but does not create 10 m SST information. A red pixel has 20 m NDCI
structure supported by a much coarser SST condition; this limitation must be
present in API metadata, the map explanation, and `LIMITATIONS.md`.

## Classification Image and Tile

Create one integer classification image after all masks and metrics exist:

```text
class = masked
if z >= 1.5:
    class = 1                         # elevated
if z >= 1.5 and trend_rising:
    class = 2                         # watch
if z >= 2.0 and trend_rising and sst_above_normal:
    class = 3                         # warning
```

Visualize classes 1, 2, and 3 with the approved green, orange, and red palette.
Class 0 and invalid data remain masked rather than painted normal. Return one
Earth Engine tile URL and map ID, preserving the existing low-latency Leaflet
integration.

## Conditional Monitoring-Site Pins

The regional raster is the source of truth for pins. During the same Earth
Engine build, sample the final class image and its supporting metric bands at
the six sites from `backend/src/grid.py`.

The scheduler supplies stable site IDs, names, and coordinates to the configured
overlay builder. The builder returns a `site_alerts` item only for sampled class
1, 2, or 3. Class 0, masked, land, cloud, and no-data sites are omitted rather
than sent as normal pins.

Each alert item contains:

- site ID, name, latitude, and longitude;
- internal level, Thai label, and color;
- NDCI z-score and latest per-pixel Sentinel-2 date;
- 14-day slope, distinct-date count, and rising flag;
- current SST, SST seasonal mean, SST source date, and above-normal flag;
- explicit nullable fields when a supporting value is unavailable.

The frontend may render these alert pins in True Color and the three-tier scan
mode so alerts remain visible on the default reload view. It must not render
them in the illustrative NDCI mode. Popup content comes from `site_alerts`, not
from the legacy `/risk-map` prediction fields, ensuring pin and raster rules
cannot disagree.

## Pipeline, Cache, and API Flow

```text
scheduled refresh
  -> build masked Sentinel-2 current/baseline/trend images
  -> build MODIS SST current/seasonal images
  -> classify one three-tier raster
  -> sample the same raster at six monitored sites
  -> create one Earth Engine tile
  -> store tile + complete metadata + non-normal site_alerts
  -> GET /watch-overlay reads only the database cache
  -> Leaflet renders the cached tile and conditional pins
```

Browser reloads must never start a live Earth Engine request. The scheduler
refreshes the overlay once per normal cycle and writes a singleton snapshot.
On refresh failure, preserve the complete last-good tile, classification
metadata, and site alerts, mark the snapshot stale, and attach the new error.
An empty cache or no usable imagery is explicit and must not be represented as
normal.

## Cache Compatibility

Preserve existing `WatchOverlayCache` fields for backward compatibility. Add one
nullable JSON field, `analysis_metadata`, containing:

- ordered level rules and colors;
- current/baseline settings;
- trend window, minimum distinct dates, and slope units;
- cloud, QA60, and water-mask descriptions;
- NDCI/output/SST resolutions;
- SST source, source date, and climatology contract;
- filtered `site_alerts`;
- per-run source dates and mosaic caveat.

Use a compatibility-safe additive database migration. Existing rows remain
readable with `analysis_metadata = null`; the API supplies no fabricated alerts
for such rows. Do not delete or rebuild a user's database.

`GET /watch-overlay` keeps its existing status and tile fields and adds a typed,
nullable `analysis_metadata` object. The endpoint remains a database-only read.

## Frontend Presentation

Keep True Color selected on reload, retain the complete scan bounds and zoom-out
lock, and do not restore the removed right-side panel.

The scan tab renders the single three-color tile. Its compact legend contains
only:

- green: เริ่มผิดปกติ;
- orange: เฝ้าระวัง;
- red: เตือนภัย;
- a transparency note that does not call transparent pixels normal.

Render only `site_alerts` pins. Pin colors match their class. Normal or no-data
pin objects do not exist in the response and therefore cannot be drawn. Popups
show the supporting fields and preserve the rule-based/indicative caveat.

When the overlay is stale, unavailable, or has no imagery, keep the basemap
usable and show the existing compact state control. Do not substitute old
`/risk-map` pins.

## Error and Missing-Data Behavior

- No current Sentinel-2 imagery: `no_imagery`, no tile, no pins.
- No valid baseline at a pixel: transparent at that pixel.
- Fewer than two trend dates: no trend escalation; valid `z >= 1.5` may remain
  elevated.
- Missing SST: no warning escalation; a rising signal may remain watch.
- Refresh exception with a last-good snapshot: retain tile and pins, mark stale,
  expose error.
- Refresh exception without a snapshot: explicit error, no tile, no pins.
- Expired tile URL: unavailable/stale state, never a normal state.

## Verification

### Credential-free tests

- pure class assignment covers masked, class 1, class 2, class 3, and
  highest-severity-wins behavior;
- missing trend and missing SST downgrade safely without inventing evidence;
- trend requires two distinct dates and positive slope;
- same-day overlapping tiles do not count as separate trend observations;
- SCL and QA60 cloud/cirrus rejection is applied;
- SCL water and connected historical-water masks both gate pixels;
- B2-B6 validity and NDCI denominator guards mask invalid inputs;
- pipeline returns only non-normal site alerts;
- scheduler stores the complete snapshot and preserves it on failure;
- additive cache migration preserves an existing row;
- `/watch-overlay` remains cache-only and validates typed metadata;
- frontend filters defensively to the three allowed alert levels;
- True Color/scan modes render alerts, illustrative NDCI does not;
- legend contains the three approved labels and no normal row;
- frontend tests, lint, and production build pass.

### Optional credentialed smoke check

With Earth Engine credentials and network access, build one current overlay and
verify:

- tile generation succeeds over the complete scan polygon;
- map metadata reports Sentinel-2 and SST source dates;
- cloud/land pixels are transparent;
- all three classes use the approved palette when present;
- returned site alerts are a subset of the six configured sites and contain no
  normal/no-data entries;
- a browser reload performs only cached API reads.

## Truth Boundaries

The three levels are deterministic rule labels, not calibrated probabilities.
Sediment, colored dissolved organic matter, bottom reflectance, adjacency
effects, residual cloud, and imperfect SCL water classification can alter NDCI.
Two dates are the minimum needed to estimate a slope, but a two-point positive
slope is still sensitive to noise. SST is much coarser than Sentinel-2. The
product indicates where the approved rules fired; it does not establish that a
harmful algal bloom exists.

## Out of Scope

- machine-learning classification or probability estimates;
- species or toxin identification;
- replacing the six-site list or inventing new monitoring coordinates;
- vectorizing every 10 m hotspot into polygons;
- normal pins;
- push notifications;
- modifying the locked 14-event validation set or reporting a validation
  percentage;
- treating 10 m display alignment as 10 m NDCI or SST source information.
