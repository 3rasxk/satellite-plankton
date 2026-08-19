# Burapha University / Gulf of Thailand HAB literature — extracted event data

**This is NOT a downloadable dataset.** It is a small, hand-extracted table of dated bloom events found embedded in the text of one open-access academic paper, per the task's explicit instruction to extract structured data found inside narrative/paper sources rather than skip them.

**Primary source:** Luang-on, J., Ishizaka, J., Buranapratheprat, A., Phaksopa, J., Goes, J. I., Maúre, E. D. R., Siswanto, E., Zhu, Y., Xu, Q., Nakornsantiphap, P., Kobayashi, H., & Matsumura, S. (2023). "MODIS-derived green *Noctiluca* blooms in the upper Gulf of Thailand: Algorithm development and seasonal variation mapping." *Frontiers in Marine Science*, 10, 1031901. https://doi.org/10.3389/fmars.2023.1031901 — **open access**.
**Date accessed:** 2026-08-18 (via WebFetch of the article's rendered text; the actual PDF/supplementary files were not independently opened, so this is only as complete as what the fetched HTML text exposed)
**Record count: 10 rows** (9 from the paper's Table 2, "Reports of red tides in the uGoT", covering 2009–2020, plus the paper's own July 30, 2018 "super bloom of green Noctiluca" event described in the main text). **This is not the paper's full dataset** — the paper's underlying MODIS-derived bloom detections spanning 2003–2021 are described as available "in the article/Supplementary Material" with no repository link; the authors would need to be contacted directly for anything beyond these 10 discrete, dated, human-observed events.
**License:** This is copyrighted journal content (Frontiers open-access articles are typically CC-BY, meaning reuse with attribution is allowed, but this was not independently verified against Frontiers' specific license terms for this article). **Treat as citable reference data, not freely redistributable raw data** — attribute the source paper if these rows are used.
**Citation:** see above.

## Columns
`event_id, date, year, month, day, location, region, algal_group, species, cell_density_cells_per_L, source_citation`

- `date` uses `??` for day-of-month where the paper's Table 2 only gave a month/year (marked "n.d." — no date — in the original), and a date-range format (`start_to_end`) where the paper gave a range of days.
- `cell_density_cells_per_L` is a range where the paper reported a range (e.g., across multiple stations/days for the same reported event), or `>1500000` for the July 2018 event where the paper stated only a lower bound.
- All 10 events are geographically within the upper Gulf of Thailand (Samut Sakhon, Phetchaburi, Chonburi) — the exact target region for this project, unlike the zero usable HAEDAT/FWC/HABSOS/PMN Thailand records.

## Why this is valuable despite being tiny
This is the only source found across all five priorities (DMCR, DOF, Burapha, broader literature, IOC-WESTPAC/SEAFDEC/ASEAN) that provides genuinely structured, dated, located, species-and-density-labeled bloom events specifically for the upper Gulf of Thailand. It is far too small (10 rows) to fine-tune a model on by itself, but is useful as: (a) ground-truth validation points to sanity-check any satellite-derived bloom detections against known real events, (b) a starting point if you contact the corresponding author for the underlying MODIS-derived event archive referenced but not published as an open dataset.

## Related paper found but not independently verified
"Enhancing the reliability of GCOM-C/SGLI data for red tide detection in the upper Gulf of Thailand," *International Journal of Remote Sensing* (2024) — full text was blocked (403) during research; cite with caution, not confirmed to contain additional structured event data.
