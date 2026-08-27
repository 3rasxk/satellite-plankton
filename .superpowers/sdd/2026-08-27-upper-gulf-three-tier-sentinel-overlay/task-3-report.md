# Task 3 report: integrated SST-supported three-tier overlay

Status: complete

Commit: `feat(data-pipeline): build three-tier Gulf tiles` (the commit containing this report)

## Outcome

- Built current MODIS-Aqua SST with a per-pixel nearest-date quality mosaic and later-date tie breaker.
- Built seasonal SST from every prior archive year and masked the seasonal mean where its observation count is zero.
- Replaced the single orange threshold raster with level codes 1-3 and the required green/orange/red visualization.
- Added the seven evidence bands to the final analysis image and sampled monitoring sites from that same image at the 20 m effective NDCI resolution.
- Filtered site alerts to class codes 1-3, retained nullable evidence and UTC source dates, and preserved input-site ordering.
- Preserved top-level legacy `threshold_z` and watch-orange `color` while adding version-2 `analysis_metadata`.

## TDD evidence

RED:

- Initial focused run: `2 failed, 10 passed`; failures were the expected missing `sst_seasonal_windows` and `_parse_site_alerts` helpers.
- Integration focused run: `4 failed, 11 passed`; failures were the expected missing SST image builder, classification graph, same-image sampler, and expanded builder path.
- Self-review regression run: `2 failed, 14 passed`; failures proved masked support bands were not yet protected from `sampleRegions` row dropping and no-data values were not restored to `None`.

GREEN:

- Pure-helper cycle: `12 passed`.
- Integrated graph cycle: `15 passed`.
- Nullable-support regression cycle: `16 passed`.

Final verification:

- `./venv/bin/python -m pytest tests/test_watch_overlay.py tests/test_watch_rules.py -q` — `20 passed in 0.35s`.
- `./venv/bin/python -m pytest tests/ -q` — `81 passed in 3.85s`.
- `git diff --check` — clean.

All tests were credential-free and used pure functions or fake Earth Engine graphs. No live GEE request was made.

## Changed files

- `data-pipeline/src/watch_overlay.py`
- `data-pipeline/src/__init__.py`
- `data-pipeline/tests/test_watch_overlay.py`
- `.superpowers/sdd/2026-08-27-upper-gulf-three-tier-sentinel-overlay/task-3-report.md`

Pre-existing untracked virtual-environment symlinks were ignored.

## Metadata contract review

- The builder signature matches the Task 3 contract, including warning, trend, SST, level-color, and monitoring-site inputs.
- Top-level `threshold_z` remains the elevated threshold and top-level `color` remains `level_colors["watch"]`.
- `analysis_metadata.version` is `2`; levels are ordered `elevated`, `watch`, `warning` with exact class codes, Thai labels, configured colors, z thresholds, and rule flags.
- Trend metadata records its window, distinct-date minimum, `ndci_per_day` units, and strict `slope_per_day > 0` rule.
- SST metadata records the required collection, windows, resolution, and strict current-above-seasonal rule.
- Mask, resolution, newest-source-date, mosaic-caveat, and filtered `site_alerts` fields match the brief.

## Earth Engine graph review and concerns

- Zero and negative count-valid slopes remain evidence bands; `slope.gt(0)` appears only in class escalation.
- SST quality is masked by the SST band before `qualityMosaic("sst_quality")`, so nearest available dates can differ by pixel. The `0.1` later-date tie breaker cannot override a one-day distance.
- The final `level_code` stays masked outside elevated pixels. Support bands use an internal `-9999` sample no-data value so `sampleRegions` does not drop an elevated site when trend or SST evidence is masked; the parser converts that value back to `None`.
- Sentinel and SST pixels can carry different dates, as stated in metadata. The fake graph verifies construction but cannot validate credentialed collection availability, native-projection behavior, or tile latency.
- There is no live-GEE fallback test for an entirely empty current SST collection; MODIS-Aqua coverage is expected in the configured archive/search period, but this remains the main runtime concern.

## Fix Round 1

- Added a schema-stable, fully masked current-SST fallback for an empty MODIS-Aqua collection. Its newest-scene metadata is nullable, so missing SST cannot escalate class 1 or 2 to class 3.
- Made site-alert class parsing strict: only finite, exact numeric classes 1, 2, and 3 are accepted; fractional values, booleans, NaN/infinity, strings, and out-of-range values are rejected.

Changed files:

- `data-pipeline/src/watch_overlay.py`
- `data-pipeline/tests/test_watch_overlay.py`
- `.superpowers/sdd/2026-08-27-upper-gulf-three-tier-sentinel-overlay/task-3-report.md`

Verification:

- RED: `./venv/bin/python -m pytest tests/test_watch_overlay.py -q` — `2 failed, 16 passed` (expected regressions).
- `./venv/bin/python -m pytest tests/test_watch_overlay.py tests/test_watch_rules.py -q` — `22 passed in 0.35s`.
- `./venv/bin/python -m pytest tests/ -q` — `83 passed in 3.08s`.
- `git diff --check` — clean.
