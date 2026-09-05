# Upper Gulf Sentinel-2 NDCI Watch Overlay — Design

> Status correction, 2026-09-06: this is an unimplemented historical proposal in this branch. No `/watch-overlay` route or active spectral-index anomaly layer exists. The current detection path reports raw indices and actual scene dates only; it does not implement the statistic proposed below. The MODIS `/timeseries` anomaly calculation remains separate and valid.

Date: 2026-08-27

## Objective

Add a current, whole-region Sentinel-2 overlay for the upper Gulf of
Thailand that displays only Gulf-connected water pixels whose seasonal NDCI anomaly
is `z >= 1.5`. Cloud, cloud-shadow, invalid, land, insufficient-baseline,
and below-threshold pixels are transparent.

This is a current anomaly screen for human review. It is not the existing
rule-based `risk_level()` prediction and does not use the 14-day trend,
SST, rainfall, or the six-site monitoring grid.

## Truth Boundary

The product label is **NDCI watch signal (z >= 1.5)**, not “forecast,”
“bloom confirmed,” or the existing rule-based “watch” tier. The overlay
shows an unusual Sentinel-2 water-colour signal relative to the seasonal
Sentinel-2 baseline. Sediment, optically complex coastal water, residual
cloud contamination, and other non-bloom causes can produce a signal.

NDCI uses Sentinel-2 B5 (20 m) and B4 (10 m). The requested output grid is
10 m, so B5 is bilinearly resampled to 10 m before the raster is rendered.
The UI and API metadata must state that the output grid is 10 m but the
effective NDCI source resolution is 20 m. Resampling does not create new
20-to-10 m spatial detail.

“Seawater only” is implemented as persistent JRC surface water connected
to open-Gulf seed points within the scan area. JRC does not measure
salinity, so connected estuaries and lower river mouths may remain in the
mask. Isolated inland lakes and ponds are excluded. The UI must call this
“Gulf-connected water,” not claim a salinity measurement.

## Geographic Scope

The scan uses the project owner's supplied quadrilateral, preserved in
latitude/longitude order:

1. Northwest: `(13.92257500, 99.29500833)`
2. Northeast: `(13.92548889, 102.57514444)`
3. Southeast: `(12.06813056, 102.57761667)`
4. Southwest: `(12.10439444, 99.31681111)`

This scan geometry is a new `UPPER_GULF_SCAN_POLYGON_LATLNG` constant. It
does not replace the smaller existing `STUDY_AREA_POLYGON_LATLNG`, because
silently changing that polygon would also change the calibration-scope
warning on arbitrary `/detect` requests. Land inside the scan polygon is
removed by the water mask.

## Selected Architecture

Generate the anomaly image server-side in Google Earth Engine and expose
it as a cached tiled map overlay. A single full-area PNG cannot retain a
10 m grid at this area size, and exporting a persistent COG would require
new object storage and a tile server. Earth Engine map tiles preserve the
requested grid while allowing Leaflet to request only visible tiles.

The flow is:

```text
Sentinel-2 SR collection
  -> per-image SCL cloud/invalid mask
  -> JRC historical-water mask
  -> per-image NDCI at a 10 m output grid
  -> latest valid-pixel composite (last 30 days)
  -> 5-year seasonal baseline (target day +/- 15 days)
  -> per-pixel z-score
  -> mask z < 1.5 and invalid baseline
  -> orange transparent GEE tile layer
  -> scheduled backend cache
  -> /watch-overlay metadata
  -> Leaflet TileLayer
```

## Data-Pipeline Design

Add `data-pipeline/src/watch_overlay.py` with one public operation:

```python
build_ndci_watch_overlay(
    target_date: str,
    *,
    threshold_z: float,
    latest_window_days: int,
    baseline_years: int,
    seasonal_window_days: int,
    min_baseline_observations: int,
    water_occurrence_pct: float,
    output_scale_m: int,
) -> dict
```

The module reuses authentication and mask constants from the existing
Sentinel-2 pipeline. Tunable values live in `detection/src/config.yaml`
under a new `ndci_watch_overlay` section. The detection bridge passes
those values as required keyword arguments, so data-pipeline does not
carry a second set of operating defaults. Tests pass explicit fixtures.

### Current-image composite

Use `COPERNICUS/S2_SR_HARMONIZED`, filtered to the scan polygon and the
30 days ending on `target_date`. For each image:

- remove SCL classes already treated as invalid by the project: no data,
  saturated/defective, cloud shadow, unclassified, medium/high cloud, and
  cirrus;
- require JRC Global Surface Water occurrence `>= 50%` and connectivity
  through water pixels to configured open-Gulf seed points;
- compute NDCI `(B5 - B4) / (B5 + B4)` after bilinear B5 resampling to the
  10 m output grid;
- add the image acquisition timestamp as a quality band.

Build the Gulf-connectivity mask once per run from JRC occurrence using
Earth Engine cumulative cost over water-only pixels, seeded at the two
existing confirmed open-water reference points `(13.00, 100.70)` and
`(13.15, 100.82)`. A pixel is marine-connected when a water-only path to
either seed exists within the scan polygon. This removes isolated inland
water without inventing a salinity value.

Use `qualityMosaic` on the timestamp band so every output pixel is the
most recent valid water pixel in the 30-day window. The result can contain
pixels from different acquisition dates. Metadata therefore reports the
window and newest contributing scene date, not one misleading “scene
date” for the entire Gulf. Pixels with no valid clear-water observation
remain masked.

### Seasonal baseline

For each of the five calendar years before `target_date`, collect images
within `target month/day +/- 15 days`, including correct year-boundary
handling. Apply the identical cloud, invalid-pixel, water, resampling, and
NDCI steps. Reduce the combined collection per pixel to mean, standard
deviation, and valid-observation count.

Only calculate z where count is at least 5 and standard deviation is
finite and greater than a small numerical epsilon. Other pixels remain
transparent rather than being assigned zero anomaly.

```text
z = (latest_ndci - seasonal_mean_ndci) / seasonal_std_ndci
watch_mask = z >= 1.5
```

The visualization has one semantic color: project watch orange
`#FF9F0A`. All non-watch values are masked, not painted as normal.

The result contains the Earth Engine image/map tile information plus
metadata: generation time, requested target date, source window,
baseline range, threshold, valid-observation minimum, water threshold,
output grid, effective resolution, and caveat text.

## Backend Design

Extend the existing namespaced bridge instead of importing
`data-pipeline/src` directly from backend code.

Add a singleton `WatchOverlayCache` database model. It stores status,
tile URL template/map identifier, generated time, target date, source
window, baseline parameters, threshold, resolution metadata, stale flag,
and the last error. It does not store Earth Engine credentials.

Add `refresh_watch_overlay()` to the scheduler. It runs once per normal
scheduler cycle, independently of the six per-site refreshes. A failed
refresh preserves the last successful tile metadata and marks it stale;
if no successful overlay exists, the cache records an explicit error.
Page loads never trigger the expensive Earth Engine computation.

Add:

```text
GET /watch-overlay
```

The response returns:

- `status`: `ok | no_imagery | error`
- `tile_url`: present only when a cached overlay is available
- `generated_at`, `target_date`, source-window metadata
- `threshold_z: 1.5`
- `output_grid_m: 10`
- `effective_resolution_m: 20`
- `baseline_years: 5`, `seasonal_window_days: 15`
- `water_occurrence_pct: 50`
- `water_mask: gulf_connected_historical_surface_water`
- `stale`, `error`, and the mandatory caveat

The route is a cache read and does not call Earth Engine. Response models
remain separate from `/risk-map`; this avoids pretending the raster is a
collection of the existing rule-based monitoring-site predictions.

## Frontend Design

Add `getWatchOverlay()` to the API client and fetch it on the overview
page alongside `/risk-map`.

Rename the rule-based map tab to **NDCI Watch (z >= 1.5)**. In this mode:

- render the cached Earth Engine tile URL as a Leaflet `TileLayer` above
  the true-color basemap;
- do not render the six monitoring-site risk markers;
- show only orange watch pixels; transparency reveals the basemap for
  below-threshold, cloud, land, and insufficient-baseline pixels;
- replace the four-tier risk legend with one orange watch row and compact
  explanations for transparent/cloud/land/no-baseline areas;
- show source-window and stale/error state without fabricating a clear
  reading when the overlay is unavailable.

True Color remains the default reload mode. The existing per-site cache,
summary pages, and rule-based backend endpoints remain intact. Point
markers may remain in non-watch modes, but they are not presented as the
whole-Gulf raster scan.

The current decorative `NdciRasterOverlay` must not be reused as evidence.
It remains explicitly illustrative unless a later task replaces it with a
separate real continuous-NDCI product.

## Error and Empty States

- No Sentinel-2 scenes in 30 days: `no_imagery`; no overlay is rendered.
- Clouds cover a pixel for the whole current window: that pixel is
  transparent.
- Land/non-historical-water: transparent.
- Isolated inland water not connected to an open-Gulf seed: transparent.
- Fewer than five baseline observations or zero standard deviation:
  transparent and counted as insufficient baseline, not normal.
- Earth Engine/auth/network failure: preserve last successful overlay,
  mark stale, and return the actual error summary.
- Tile URL absent/expired: show an overlay-unavailable message and keep
  the true-color map operational.

## Configuration

Add to `detection/src/config.yaml`:

```yaml
ndci_watch_overlay:
  threshold_z: 1.5
  latest_window_days: 30
  baseline_years: 5
  seasonal_window_days: 15
  min_baseline_observations: 5
  water_occurrence_pct: 50.0
  gulf_seed_points:
    - [13.00, 100.70]
    - [13.15, 100.82]
  output_scale_m: 10
  effective_resolution_m: 20
  color: "#FF9F0A"
```

These values are project defaults chosen for this product view, not
calibrated performance claims. The API exposes them so the UI describes
the actual run rather than repeating hard-coded copy.

## Testing and Verification

### Data pipeline

- Pure tests for five-year seasonal date windows, including dates near
  January 1 and December 31.
- Pure/config tests for z thresholding, minimum count, zero standard
  deviation, and metadata truth labels.
- Mocked Earth Engine boundary tests proving the same cloud/water mask is
  applied to current and baseline collections.
- Existing Sentinel-2 masking tests remain green.

### Backend

- Scheduler success writes the singleton cache.
- Scheduler failure preserves the last success and marks it stale.
- Empty cache/error cache responses never invent a tile URL.
- `/watch-overlay` is a DB/cache read with the complete resolution and
  caveat metadata.
- Existing `/risk-map`, scheduler, and integration suites remain green.

### Frontend

- API client shape and mode-selection logic receive focused Node-native
  tests where practical; no frontend test framework is currently
  configured.
- `npm run lint` and `npm run build` are required.
- Manual verification against the running API checks: true-color default,
  orange-only watch overlay, marker suppression in watch mode, transparent
  land/cloud/below-threshold areas, and stale/error states.

### Optional live Earth Engine smoke check

With project credentials configured, generate one overlay and verify that
the returned tile endpoint serves an image. This is not part of the
deterministic test suite and must not be required in CI.

## Non-Goals

- No 14-day trend, SST, rainfall, or `risk_level()` evaluation.
- No claim that z >= 1.5 confirms a harmful algal bloom.
- No per-pixel species or cell-density estimate.
- No claim that the water mask measures salinity; Gulf-connected
  estuarine water can remain.
- No persistent GeoTIFF/COG archive or new object-storage service.
- No replacement of the existing point-reading or rule-based summary endpoints.

## Acceptance Criteria

1. The scan covers the supplied upper-Gulf quadrilateral.
2. The current layer uses the latest valid clear-water Sentinel-2 pixel
   available in the preceding 30 days.
3. Baseline is five preceding years at target day +/- 15 days.
4. Cloud/invalid SCL pixels, JRC occurrence below 50%, and isolated
   inland water are excluded in both current and baseline imagery.
5. The overlay renders only pixels with valid baseline and `z >= 1.5`.
6. Output tiles use a 10 m grid and disclose 20 m effective NDCI source
   resolution.
7. The frontend watch mode renders no normal/elevated/warning markers or
   pixels.
8. Reloading the page does not trigger a live Earth Engine scan.
9. Failures and stale data are explicit; no missing pixel is labeled
   normal.
10. All affected Python tests, the focused frontend tests, lint, and build
    pass.
