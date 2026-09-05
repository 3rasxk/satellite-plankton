# Index comparison -- NDCI vs 2BDA vs 3BDA vs B2/B3

**Cannot be compared against the 14 validation events** -- see `event_table.md`: 1 of 14 events produces a real matched satellite reading, and one event cannot rank four indices against each other, so there is still no per-event ground truth to score any index against. What follows instead is a live demonstration that all four indices compute correctly on real Sentinel-2 data, at non-event points/dates chosen only because they returned cloud-clear imagery during this build -- **not a validation result.**

| point | date | actual_date | cloud_fraction | NDCI | 2BDA | 3BDA | B2/B3 |
|---|---|---|---|---|---|---|---|
| koh_sichang_area | 2020-01-15 | 2020-01-17 | 0.00 | 0.0863 | 1.1889 | 0.1767 | 0.8533 |
| offshore_gulf_center | 2020-02-05 | 2020-02-06 | 0.15 | 0.0369 | 1.0767 | 0.0749 | 1.0223 |
| offshore_gulf_center | 2019-12-15 | 2019-12-13 | 0.00 | 0.0606 | 1.1289 | 0.0955 | 1.3112 |

## 14-event validation attempt -- still not a real comparison, but for a new reason

As of 2026-08-22, 7 of the 14 events (`data/validation/events.csv` commit d9811d7) have a real coordinate and were genuinely queried against live Sentinel-2 (see `reports/event_table.md`'s 'newly-coordinate events' section for the full per-event detail). None of the 7 produced a usable Sentinel-2 band reading this run (four predate Sentinel-2's 2015 launch, one hit a tiling gap, one hit full cloud cover, one hit a land/water mask limitation at its coordinate) -- so there is still no real per-event NDCI/2BDA/3BDA/B2-B3 value to compare against a documented bloom outcome. This is a different, more specific limitation than the prior phase's (missing coordinates); it is not yet a resolved one. The demo-point table above remains the only real, live confirmation that the four index functions compute correctly end-to-end.

## What these numbers do and don't show

- Confirms all four index functions in `src/indices.py` run against real band values pulled live from Google Earth Engine (`COPERNICUS/S2_SR_HARMONIZED`) -- not synthetic test fixtures.
- Does NOT show which index best discriminates a real documented bloom, because none of the three demo points/dates above coincide with a documented event, and none of the 7 now-coordinate-bearing events produced a real Sentinel-2 reading this run either (see the section above and `event_table.md`).
- Per `docs/DETECTION_PLAN.md` §2, 3BDA is expected to outperform NDCI/2BDA specifically near river mouths (turbid water) -- still untested against a real event: th_003/th_008/th_012 (Tha Chin river mouth, the site this prediction is specifically about) all predate Sentinel-2 or hit an archive gap this run.
- B2/B3 (green *Noctiluca* discrimination) is secondary/lower-confidence by design (`.claude/agents/bloom-detection.md` §1) and, per `data/validation/CALIBRATION_NOTES.md` §2, is only expected to be meaningful for *Noctiluca* events specifically -- none of the demo points above are events at all, so this column is shown only to confirm the function runs, not that it discriminates anything.
