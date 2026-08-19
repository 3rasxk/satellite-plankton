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