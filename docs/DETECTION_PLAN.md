# Detection & Prediction Plan

## Scope

The project monitors the upper Gulf of Thailand with a physics-based pipeline.
It does not train a classifier: no suitable local labelled dataset is active in
the repository.

## Detection readings

Sentinel-2 supplies NDCI, 2BDA, 3BDA, and an exploratory B2/B3 context ratio.
A successful call returns those dimensionless index values, status, and the
actual cloud-free scene date selected by the search window. The B2/B3 ratio is
not a validated *Noctiluca* discriminator. NDCI and 2BDA are transformations of
the same B5/B4 ratio and cannot count as independent confirmation.

No spectral-index anomaly score is computed. The former design standardized a
dimensionless index against a MODIS `chlor_a` concentration baseline; that was
dimensionally invalid and has been removed. A future anomaly statistic must
compare like quantities and use a location- and season-specific history with
only prior independent acquisitions and identical product, masks, grid,
resolution, and aggregation. `src/signal_anomaly.py` now pins those validation
conditions and the provisional robust-z boundaries, but remains disconnected
because the necessary Sentinel-2 history is not persisted.

Activation is fail-closed. In addition to 30 or more independent dates and a
maximum age of 14 days, configuration must identify a non-empty baseline
version and preprocessing signature and explicitly declare location-specific,
season-specific, prior-only history. These declarations cannot replace the
missing baseline table; they prevent an old cached risk level from becoming
visible through a single flag change.

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

## Full-area raster

The raster scan evaluates the four Sentinel-2 indices across the study-area
polygon in one composite. Each retained cell stores its own acquisition time;
cloudy, land, and otherwise unmeasured cells stay transparent in the overlay
and remain queryable as `not_measured` through the stored date mask. A
hourly poll assesses each new acquisition date for cloud over the polygon's
water (cloud-flagged share at most 0.5) and starts a scan at once for the newest
passing date newer than the newest date already used (latest-scene policy; the
20 h cooldown now gates only the first-install bootstrap). A date assessed less
than 36 h after it began is marked unsettled. The candidate timestamp is stored separately from retained cell dates
so a wholly cloudy acquisition is still remembered. This product reports index
readings and coverage only; it does not compute anomaly scores, risk tiers, or
bloom verdicts. The fixed seven named stations remain available through
`/risk-map` and use the same system-wide scene-age rule as `/detect`.

## Limitations

Clouds, sub-pixel or subsurface blooms, turbid coastal water, mixed land/water
buffers, sediment plumes, and sensor/product latency all limit interpretation.
See `LIMITATIONS.md`. Index values alone establish neither bloom presence nor
absence.
