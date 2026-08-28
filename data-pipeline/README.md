# data-pipeline

Sentinel-2 + MODIS extraction via Google Earth Engine. Owned by the `satellite-data` agent — see `.claude/agents/satellite-data.md`.

## Setup

```bash
cd data-pipeline
/opt/homebrew/bin/python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
earthengine authenticate
```

**Do not use the default `python3` on PATH if it resolves to a PlatformIO/Arduino toolchain Python** — it ships an old LibreSSL build and `earthengine authenticate` fails with an SSL certificate error. Check with `which python3`; use the Homebrew or `/usr/bin` system Python instead (confirmed clean on this machine: `/opt/homebrew/bin/python3`, OpenSSL 3.6.3).

## NDCI watch-overlay operation

`src.watch_overlay.build_ndci_watch_overlay()` builds the raster metadata and
Earth Engine tile template used by the whole-upper-Gulf NDCI watch signal. It
uses the Sentinel-2 Level-2A collection `COPERNICUS/S2_SR_HARMONIZED` and
applies the same preprocessing to current and baseline imagery.

For each image, the operation removes SCL classes 0 (no data), 1
(saturated/defective), 3 (cloud shadow), 7 (unclassified), 8 and 9
(medium/high-probability cloud), and 10 (thin cirrus). It retains JRC Global
Surface Water occurrence of at least 50%, then uses water-only cumulative-cost
connectivity to the configured open-Gulf seed points. This produces a
Gulf-connected historical-surface-water mask that excludes isolated inland
water; it is not a salinity measurement, so connected estuaries can remain.

The current layer covers the 30 days ending on the requested date. A timestamp
`qualityMosaic` selects the latest valid water pixel at each location, meaning
one result can contain pixels from different acquisition dates. The seasonal
baseline uses the five preceding calendar years, each within target
month/day +/- 15 days, and applies the same SCL, water, resampling, and NDCI
path. NDCI combines B5 (20 m) with B4 (10 m): B5 is bilinearly resampled to a
10 m output grid, while the effective source resolution remains 20 m.

With Earth Engine credentials and `EE_PROJECT_ID` already configured, this
optional smoke check builds one configured overlay through the detection
bridge. It is not required in CI:

```bash
cd detection
./venv/bin/python -c "from src.watch_overlay import build_configured_ndci_watch_overlay; r=build_configured_ndci_watch_overlay('2026-08-27'); print({k: r[k] for k in ('status','target_date','source_window_start','source_window_end','newest_scene_date','threshold_z','output_grid_m','effective_resolution_m','water_mask')}); print(r['tile_url'])"
```
