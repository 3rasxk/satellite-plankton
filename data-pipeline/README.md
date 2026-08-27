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

**Do not use the default `python3` on PATH if it resolves to a PlatformIO/Arduino toolchain Python** — it ships an old LibreSSL build and `earthengine authenticate` fails with an SSL certificate error. Check with `which python3`; use the Homebrew or `/usr/bin` system Python instead.

## Whole-upper-Gulf NDCI Watch overlay

`src/watch_overlay.py` builds the cached watch raster for the supplied upper-Gulf scan quadrilateral. It selects the latest clear Sentinel-2 imagery in the configured 30-day window, applies Sentinel-2 SCL cloud/shadow filtering, and compares NDCI against five prior seasonal years with ±15-day windows. No 14-day trend, SST, rainfall, or species inference is used.

The mask is Gulf-connected historical surface water from JRC water occurrence and connectivity, not a salinity measurement. Pixels are emitted only when `z >= 1.5`, at least five baseline observations exist, and baseline variance is usable. The output grid is 10 m; NDCI's effective source resolution is 20 m because its B5 input is 20 m. Qualifying pixels use orange; all other pixels are transparent. This is an indicative rule-based watch signal, not bloom confirmation or a validated forecast. The latest composite is a mosaic, so different pixels may come from different scene dates.

The source collection is `COPERNICUS/S2_SR_HARMONIZED`. SCL classes 0 (no data), 1 (saturated/defective), 3 (cloud shadow), 7 (unclassified), 8 and 9 (cloud), and 10 (cirrus) are invalid. JRC Global Surface Water occurrence is thresholded at `>=50%`; cumulative-cost connectivity from open-Gulf seed points removes isolated inland water. The latest valid pixel is selected by timestamp quality mosaic, while the baseline uses seasonal mean, standard deviation, and observation count. B5 is resampled to the 10 m output grid, so the effective NDCI source resolution remains 20 m.

For an optional credentialed smoke check only, run `earthengine authenticate`, then from this repository run `cd detection && ./venv/bin/python -c "from src.watch_overlay import build_configured_ndci_watch_overlay; r=build_configured_ndci_watch_overlay('2026-08-27'); print({k: r[k] for k in ('status','target_date','source_window_start','source_window_end','newest_scene_date','threshold_z','output_grid_m','effective_resolution_m','water_mask')}); print(r['tile_url'])"`. This makes a real Earth Engine request and prints the tile URL; network/auth failure must be reported as unavailable, not replaced with a normal or clear reading.
