# Validation dataset — folder guide

This holds the ground truth the detection system is validated against.
It is **not training data** — there is no model to train (see `docs/DETECTION_PLAN.md` §0).
The system is physics-based (spectral indices + MODIS climatology); these events exist
solely to check whether the resulting thresholds fire on real, documented blooms.

**Scope is locked at 14 events.** No further data collection is planned — see
`docs/DETECTION_PLAN.md` §4 for how this fixed set is used (leave-one-out calibration,
reported per-event, never as a percentage).

```
data/validation/
├── README.md
├── events.csv                      # THE file every agent reads — one row per
│                                    # event, 14 total, merged from thailand/
├── water_mask_truth.json           # NOT bloom data — water/land ground truth for
│                                    # the 501-point scan grid, used only to test
│                                    # the Sentinel-2 buffer water mask. See below.
└── thailand/
    ├── REPORT_THAILAND.md          # the full source-search report — read this
    │                                # first for context on what was found, what
    │                                # wasn't, and why. Not read by any agent;
    │                                # it's for humans reviewing provenance.
    ├── burapha_literature/         # Luang-on et al. (2023), Frontiers in Marine
    │                                # Science 10:1031901 — the primary source,
    │                                # 10 of the 14 events, including the
    │                                # 30 Jul 2018 super-bloom (>1,500,000 cells/L)
    ├── seafdec_literature/         # SEAFDEC SP15-1 (2017) + Sudara (1984),
    │                                # Chulalongkorn — 3 historical events, 1981–1983
    └── moac_bulletin/              # 2018 MOAC disaster bulletin — 1 event,
                                     # Samut Songkhram mollusc die-off
```

## Schema — `events.csv`

| Column | Notes |
|--------|-------|
| `event_id` | Unique, stable |
| `date` | YYYY-MM-DD, or `date_start`/`date_end` for a range |
| `lat`, `lng` | Decimal degrees. **Blank if the source doesn't give them — never estimated from a place name.** |
| `location_name` | As written in the source |
| `location_precision` | `coordinates` \| `named_site` \| `province_level` |
| `species` | e.g. `noctiluca_scintillans`, `unknown` |
| `cell_count` | Cells/L where reported, blank otherwise |
| `event_type` | `bloom` \| `clear_water` |
| `source_type` | `paper` \| `government` \| `news` |
| `source_citation` | Full, traceable — every row must have one |
| `confidence` | `documented` \| `inferred` |

## Current status

14 events (1981–2020) across the three sources above — 13 of 14 in the upper Gulf of Thailand (Chonburi/Samut Sakhon/Phetchaburi/Prachuap Khiri Khan), 9 of 14 with a numeric cell density. Most have `location_precision = named_site`, not `coordinates` — a known limitation, documented in `LIMITATIONS.md`, not something the pipeline works around. Full detail and per-source notes are in `thailand/REPORT_THAILAND.md`.

---

## `water_mask_truth.json` — a mask fixture, not a bloom dataset

**This file has nothing to do with the 14 HAB events above.** It contains no bloom
observations, is never read by `thresholds.py`, and takes no part in threshold
calibration or leave-one-out validation. The "14 events, scope locked" rule stated
at the top of this README applies to `events.csv` only, and is not weakened by this
file's existence.

What it is: water/land ground truth for the 501 points of `generate_scan_grid(5)`,
sampled with the same 30 m buffer at 10 m scale that `_resolve_sentinel2_scene`
uses. It exists so the Sentinel-2 buffer water mask can be tested against a real
negative set — specifically, so a change to that mask can be shown not to let land
pixels through, rather than only shown to recover more points.

| Field | Notes |
|-------|-------|
| `point_id`, `lat`, `lng` | Grid point identity, matching `backend/src/regional_scan/grid.py` |
| `ndwi` | (B3 − B8)/(B3 + B8) from each pixel's clearest 2025-11→2026-04 observation, chosen by Cloud Score+ `qualityMosaic` on `cs_cdf` |
| `is_water` | `ndwi > 0`. **This is the truth column.** 400 water, 99 land |
| `buffer_px`, `jrc_occ_valid`, `jrc_occ_water` | JRC GSW occurrence pixel counts in the buffer. `jrc_occ_valid < buffer_px` means JRC has no data there |
| `etopo_m`, `mod44w`, `worldcover` | Candidate mask inputs under evaluation — **reference columns, not truth** |

Why NDWI and not Sentinel-2's own SCL class 6 (WATER): SCL was tried first and
rejected on measurement. At points `4_9` and `5_9` — ETOPO1 −10 m, roughly 10 km
offshore — the clearest available observation is SCL `thin cirrus`, so class 6 is
never assigned and an SCL-majority rule labels deep water as land. Measured
NIR/green at those points is 0.03 and 0.00. NDWI is a physical contrast and does
not depend on a per-scene classifier.

Two of the 501 points (`4_15`, `4_17`) are excluded as unmeasurable: both returned
B3 = 0 and B8 = 0 in the composite, making NDWI 0/0. They are not counted as land.

One known ambiguity, documented rather than resolved: `23_10` at the Chao Phraya
mouth is NDWI −0.220 while JRC reports 30/30 water. It is a real tidal mudflat —
exactly the turbid river-mouth case `data-pipeline/src/sentinel2.py`'s docstring
warns about. Both the current mask and the proposed one admit it.

Measured 2026-09-05 against live Earth Engine. Regenerating it requires GEE auth.
