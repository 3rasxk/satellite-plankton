# Index comparison -- NDCI vs 2BDA vs 3BDA vs B2/B3

**Cannot be compared against the 14 validation events** -- see `event_table.md`: 0 of 14 events produced a real matched satellite reading in this run, so there is no per-event ground truth to score any index against yet. What follows instead is a live demonstration that all four indices compute correctly on real Sentinel-2 data, at non-event points/dates chosen only because they returned cloud-clear imagery during this build -- **not a validation result.**

| point | date | actual_date | cloud_fraction | NDCI | 2BDA | 3BDA | B2/B3 |
|---|---|---|---|---|---|---|---|
| koh_sichang_area | 2020-01-15 | 2020-01-17 | 0.00 | 0.0859 | 1.1880 | 0.1759 | 0.8486 |
| offshore_gulf_center | 2020-02-05 | 2020-02-06 | 0.12 | 0.0400 | 1.0834 | 0.0814 | 1.0236 |
| offshore_gulf_center | 2019-12-15 | 2019-12-13 | 0.00 | 0.0519 | 1.1095 | 0.0834 | 1.3063 |

## What these numbers do and don't show

- Confirms all four index functions in `src/indices.py` run against real band values pulled live from Google Earth Engine (`COPERNICUS/S2_SR_HARMONIZED`) -- not synthetic test fixtures.
- Does NOT show which index best discriminates a real documented bloom, because none of the three points/dates above coincide with a documented event (`data/validation/events.csv` has no matchable coordinate for comparison, per `event_table.md`).
- Per `docs/DETECTION_PLAN.md` §2, 3BDA is expected to outperform NDCI/2BDA specifically near river mouths (turbid water) -- untested here for the same reason: no real event coordinate near a river mouth was available to check against.
- B2/B3 (green *Noctiluca* discrimination) is secondary/lower-confidence by design (`.claude/agents/bloom-detection.md` §1) and, per `data/validation/CALIBRATION_NOTES.md` §2, is only expected to be meaningful for *Noctiluca* events specifically -- none of the demo points above are events at all, so this column is shown only to confirm the function runs, not that it discriminates anything.
