# SEAFDEC repository — Thailand historical red tide/PSP literature (extracted events)

**This is NOT a downloadable dataset** — it is a small hand-extracted table of historical events found embedded in narrative PDF reports in SEAFDEC's institutional repository, per the task's instruction to extract structured data from narrative sources rather than skip them.

**Sources:**
1. Sudara, S. (1984). "Red Tide and Paralytic Shellfish Poisoning Phenomena in Thailand." Chulalongkorn University. Accessed via SEAFDEC institutional repository: `repository.seafdec.org/bitstream/.../SudaraS1984.pdf`.
2. Yeap, S.E. & Sulit, V.T. (2017). "Monitoring and Identification of Harmful Algal Blooms in Southeast Asia to Support SDG 14.1." SEAFDEC, Vol 15(1), pp. 39–46. `repository.seafdec.org/handle/20.500.12066/1006` — **open access**.

**Date accessed:** 2026-08-18
**Record count: 3 rows.** These are the only individually dated/located events with enough detail to extract from what was fetched; both source PDFs also contain broader narrative summary text (e.g., "1957s–2007s: dominant species Noctiluca scintillans in Thai waters generally") that is too vague to convert into a dated row and was NOT force-fit into this table.
**License:** SEAFDEC repository content — reuse terms not independently confirmed; treat as citable historical reference, not freely redistributable data.
**Citations:** see above.

## Data quality note — a real discrepancy, not resolved
The Sudara (1984) source describes a May 12–16, 1983 Pranburi River / Prachuap Khiri Khan PSP outbreak as "34 hospitalized, 1 death." The SEAFDEC SP15-1 (2017) narrative separately describes "May 1983 in Pranburi River, Prachuap Khiri Khan Province — 63 victims from eating mussels." These may be the same event described with different casualty figures by two different sources, or two distinct events in the same location/month. **This was not resolved — both figures are reported as-is in the `notes` column rather than picking one.**

## Columns
`event_id, date, year, month, day, location, region, species_or_cause, notes, source_citation`

No cell-count/density values were available for any of these three events — 1980s Thai red tide reports predate routine cell-count monitoring in the available literature. These rows are useful only as historical confirmation that red tide events have occurred in these Thai locations, not as quantitative training labels.
