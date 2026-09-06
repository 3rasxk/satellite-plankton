# Detection & Prediction Plan

## Scope

The project monitors the Gulf of Thailand, Thai side, with a physics-based
pipeline (widened from the upper Gulf on 2026-09-06).
It does not train a classifier: no suitable local labelled dataset is active in
the repository.

## Detection readings

Sentinel-2 supplies NDCI, 2BDA, 3BDA, and a secondary B2/B3 *Noctiluca*
discrimination signal. A successful call returns those dimensionless index
values, status, and the actual cloud-free scene date selected by the search
window.

No spectral-index anomaly score is computed. The former design standardized a
dimensionless index against a MODIS `chlor_a` concentration baseline; that was
dimensionally invalid and has been removed. A future anomaly statistic must
compare like quantities and must define reliability and minimum-pixel rules
before it can activate thresholds.

## Separate environmental context

MODIS `chlor_a` history may be compared with a MODIS `chlor_a` climatology.
MODIS SST and rainfall are supporting environmental signals. These quantities
must not be relabelled as a Sentinel-2 index anomaly or merged into an opaque
score.

## Rule-based prediction

Escalation rules remain readable in `detection/src/config.yaml`, but each level
requires the unavailable spatial anomaly input. Until a valid baseline exists,
the engine returns no level, no triggered rule, and the reason
`not_computed_no_valid_baseline`.

## Regional scan

The regional scan evaluates the same `detect()` pipeline at every grid point in
the study-area polygon. Scene choice is not the scan's decision and cannot be
varied per caller: `get_sentinel2_bands` applies one system-wide rule — the
newest usable scene acquired on or before the requested day, never a later one,
giving up past `SENTINEL2_MAX_SCENE_AGE_DAYS` (14) and reporting no imagery
rather than reaching further back. `/detect`, the scheduler's site cache and the
rendered thumbnails all read under that same rule, which is also what keeps a
thumbnail and the number beside it on the same scene. Cloud and water-mask
criteria are unchanged. The scan stores every point, including explicit no-data
statuses, and preserves the real per-point `actual_date`. With anomaly scoring
inactive, `spatial_anomaly_z`, `threshold_tier`, and clusters remain null/empty.

## Limitations

Clouds, sub-pixel or subsurface blooms, turbid coastal water, mixed land/water
buffers, sediment plumes, and sensor/product latency all limit interpretation.
See `LIMITATIONS.md`. Index values alone establish neither bloom presence nor
absence.
