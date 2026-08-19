# Thailand-Specific HAB Data Sources — Final Report

**Prepared:** 2026-08-18
**Scope:** Sources NOT already covered by HAEDAT/FWC/HABSOS/PMN (which contain zero usable Thailand coastal records — see the earlier `REPORT.md`).

## Bottom line up front

No source checked has a downloadable, structured Thailand HAB dataset. The best material found is **14 individually dated, located bloom events extracted by hand from academic papers and government bulletins** (10 from one 2023 Frontiers paper on the upper Gulf of Thailand specifically, 3 from a 1984 SEAFDEC-archived paper, 1 from a 2018 MOAC disaster bulletin) — saved as small CSVs in `ml/data/raw/thailand/*/thailand_hab_events_extracted.csv`. This is not remotely enough to fine-tune a model, but it is real, citable, and geographically on-target (mostly Chonburi/Samut Sakhon/Phetchaburi — the upper Gulf). Beyond that, the most promising unexplored leads are DMCR's Marine Warning System and AutoStation (both JavaScript-heavy, blocked automated access, need a real browser or manual visit) and direct contact with DMCR's Chonburi regional office.

## Per-source results

### Priority 1 — DMCR (Department of Marine and Coastal Resources)
**No data downloaded.** This is the agency with the actual red-tide monitoring mandate and has the most promising leads of anything checked:
- Category 3 (references, no confirmed download): Upper Gulf Research Center bulletins (dmcrth.dmcr.go.th/umcr) — tracks "sea color change" for 32 stations across exactly the target region, twice yearly, but no download link confirmed via automated fetch.
- Category 2 (needs manual access): Open Data Portal (opendata.dmcr.go.th) lists a "Marine Water Quality Report" CSV/XLSX dataset, but the download page didn't load via fetch — needs a real browser. Chonburi regional office (สทช.2) has a direct phone/mail contact.
- Category 4 (not found/inaccessible): Marine Warning System (warning.dmcr.go.th) and AutoStation (autostation.dmcr.go.th) — both plausibly the most relevant real-time sources by name, but both are JS-heavy and blocked every automated access attempt.
- Full detail: `ml/data/raw/thailand/dmcr/SOURCE.md`

### Priority 2 — Department of Fisheries (DOF)
**No HAB data downloaded — confirmed DOF is not the responsible agency** (that's DMCR). DOF's one relevant contribution is aquaculture-damage bulletins as an indirect bloom proxy:
- Category 3: A June 2018 MOAC (ministry-level) disaster bulletin explicitly attributes a Samut Songkhram mollusc die-off to a plankton bloom — extracted as 1 row in `ml/data/raw/thailand/moac_bulletin/`.
- Category 1 (downloadable, relevance unverified): a general "Coastal Fisheries Research Data" CSV on Thailand's national open-data portal — not inspected for actual red-tide relevance.
- Category 2: DOF's own CKAN catalog exists but was blocked from automated access; a GIS contact email (gis@fisheries.go.th) was found.
- Full detail: `ml/data/raw/thailand/dof/SOURCE.md`

### Priority 3 — Burapha University / Tanuspong Pokavanich
**Correction to the brief:** Tanuspong Pokavanich is **not** affiliated with Burapha University — he's at Kasetsart University's Faculty of Fisheries, and his verified 2024 paper (*Water*, 16(14), 1962) is about physical oceanography/currents in the eastern Gulf of Thailand, **not algal blooms**, and contains no bloom event data.

The actual relevant Burapha-affiliated work is by **Anukul Buranapratheprat** (Dept. of Aquatic Science), co-author of the paper described below in Priority 4. No downloadable dataset was found from either researcher — the underlying MODIS-derived bloom archive behind the Buranapratheprat/Luang-on paper is described only as "included in the article/Supplementary Material," with raw data available on request to the corresponding author (contact not independently verified in this pass).
Full detail: `ml/data/raw/thailand/burapha_literature/SOURCE.md`

### Priority 4 — Academic literature with embedded event data
**Confirmed and extracted.** The paper referenced in the original brief (July 2018 bloom, MODIS, 2003–2021 coverage) is:

> Luang-on, J., Ishizaka, J., Buranapratheprat, A., Phaksopa, J., Goes, J. I., Maúre, E. D. R., Siswanto, E., Zhu, Y., Xu, Q., Nakornsantiphap, P., Kobayashi, H., & Matsumura, S. (2023). "MODIS-derived green *Noctiluca* blooms in the upper Gulf of Thailand: Algorithm development and seasonal variation mapping." *Frontiers in Marine Science*, 10, 1031901. https://doi.org/10.3389/fmars.2023.1031901 (open access)

It contains a genuine structured table (Table 2, 9 dated/located/species/density-labeled events, 2009–2020) plus a described July 30, 2018 "super bloom" event (>1,500,000 cells/L, chl-a >1,469 mg/m³) — all extracted into `ml/data/raw/thailand/burapha_literature/thailand_hab_events_extracted.csv` (10 rows total). This is the single best Thailand-specific find across all five priorities.

The SEAFDEC SP15-1 (2017) regional report and Sudara (1984) Chulalongkorn paper add 3 more historical (1981–1983) narrative events, extracted into `ml/data/raw/thailand/seafdec_literature/`.

Several other candidate papers were found only as search hits (titles/abstracts), not fetched/verified — listed as unconfirmed leads in the SOURCE.md files rather than treated as data.

### Priority 5 — IOC-WESTPAC, SEAFDEC, ASEAN-level sources
- **IOC-WESTPAC: not found.** Its HAB sub-network page is descriptive only (a chair contact), and its document library has no HAB/red-tide category. `data.hais.ioc-unesco.org` appears to just be HAEDAT's own front-end, not a separate dataset.
- **SEAFDEC: found references, no structured data beyond what's extracted above.** Its institutional repository holds the 1984 Sudara paper and the 2017 SP15-1 regional report (both narrative/historical, now partially extracted above). No ongoing/live HAB monitoring database.
- **ASEAN-level (COBSEA, PEMSEA, ASEAN Ocean Data Network): not found.** COBSEA's Thailand content is about nutrient pollution generally, not HABs. PEMSEA's 2024 EastHAB bulletin covers China/Korea/Japan/Philippines — Thailand is not mentioned. No ASEAN Ocean Data Network HAB module exists.

## Combined extracted event data (all sources)

| Total extracted events | 14 |
|---|---|
| Date range | 1981–2020 |
| All in upper Gulf of Thailand region (Chonburi/Samut Sakhon/Phetchaburi/Prachuap Khiri Khan) | 13 of 14 |
| Have a numeric cell density | 9 of 14 |
| Have only narrative/no density | 5 of 14 |

**This is not usable for fine-tuning a satellite detection model** — 14 hand-extracted rows, most without precise single-day dates or exact coordinates (they're described by place-name, not lat/lng), is far below any reasonable training threshold. Its value is as validation/sanity-check ground truth (does the model's satellite-derived detection line up with these 14 known real events?), and as a starting point for direct outreach (the DMCR Chonburi office, the Frontiers paper's corresponding author, DOF's GIS contact) if a human wants to pursue actual structured data acquisition.

## Recommended next steps, in order of likely payoff
1. Contact the Luang-on et al. (2023) corresponding author directly — they explicitly reference an underlying MODIS-derived event archive not published as open data.
2. Manually visit (not fetch) `warning.dmcr.go.th` and `autostation.dmcr.go.th` with a real browser — both are JS-heavy sites that blocked every automated access attempt and are, by name, the most directly relevant DMCR resources.
3. Call/email DMCR's Chonburi regional office (สทช.2): 038-467-372/3.
4. Query the DMCR open-data CKAN API directly (`https://dmcr.gdcatalog.go.th/api/3/action/datastore_search`) for the exact resource URL of its "Marine Water Quality Report" dataset.
5. Email DOF's GIS contact (gis@fisheries.go.th) specifically about red tide / shellfish-closure records.
