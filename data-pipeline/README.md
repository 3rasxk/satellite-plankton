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
