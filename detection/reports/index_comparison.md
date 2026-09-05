# Index comparison -- NDCI vs 2BDA vs 3BDA vs B2/B3

**All 14 events cannot be evaluated for detection.** No valid anomaly baseline exists for the spectral indices. The former comparison with a MODIS `chlor_a` concentration baseline mixed incompatible units and supplies no result for any index. th_010 has a real satellite reading, but no valid anomaly statistic; it is not a miss. The table below preserves previously recorded live Sentinel-2 index readings at three non-event points/dates. It demonstrates that the index functions ran on real data, **not that their outputs detect blooms or rank the indices**. No new live extraction was performed for this documentation correction.

| point | date | actual_date | cloud_fraction | NDCI | 2BDA | 3BDA | B2/B3 |
|---|---|---|---|---|---|---|---|
| koh_sichang_area | 2020-01-15 | 2020-01-17 | 0.00 | 0.0863 | 1.1889 | 0.1767 | 0.8533 |
| offshore_gulf_center | 2020-02-05 | 2020-02-06 | 0.15 | 0.0369 | 1.0767 | 0.0749 | 1.0223 |
| offshore_gulf_center | 2019-12-15 | 2019-12-13 | 0.00 | 0.0606 | 1.1289 | 0.0955 | 1.3112 |

## Satellite availability is separate from anomaly evaluation

Seven of the 14 events have documented coordinates. The recorded satellite checks recovered a reading for th_010 on `actual_date` 2020-02-16; of the other six, four predate Sentinel-2, one has a coverage gap, and one has total cloud rejection. The remaining seven have no coordinate. **All 14 lack a valid anomaly statistic**, independently of these availability findings. th_010's reading has three qualifiers: `n=1`; `karenia_sp`, not the B2/B3 *Noctiluca* target; and recovery through the ETOPO1 fallback where JRC returns zero pixels, ETOPO1 averages +3.1 m with about 35% below sea level, and bands are 1040–1660 versus 200–560 in open Gulf water. None changes the invalid statistic into a detection result.

## What these numbers do and don't show

- Confirms all four index functions in `src/indices.py` run against real band values pulled live from Google Earth Engine (`COPERNICUS/S2_SR_HARMONIZED`) -- not synthetic test fixtures.
- Does NOT show which index best discriminates a documented bloom. No valid anomaly statistic exists for any of the 14 events, and none of the demo points/dates is a documented event.
- The proposed benefit of 3BDA near turbid river mouths remains unvalidated here. th_003/th_008/th_012 at Tha Chin all predate Sentinel-2, and no event has an evaluable anomaly statistic.
- B2/B3 (green *Noctiluca* discrimination) is secondary/lower-confidence by design (`.claude/agents/bloom-detection.md` §1) and, per `data/validation/CALIBRATION_NOTES.md` §2, is only expected to be meaningful for *Noctiluca* events specifically -- none of the demo points above are events at all, so this column is shown only to confirm the function runs, not that it discriminates anything.
