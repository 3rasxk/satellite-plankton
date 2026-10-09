# Academic Dashboard Redesign — Design Spec

Date: 2026-10-09 · Status: draft for review · Scope: `frontend/` plus two additive read-only backend endpoints (`GET /methods`, `GET /raster-scan/highlights`)

## 1. Intent

Redesign the web dashboard so it is **beautiful, easy to use, academically rigorous, complete, and verifiable**.

- **Primary users:** (1) researchers and competition judges who will probe method and provenance; (2) agency/ministry staff who need the current situation quickly in formal Thai.
- **Success looks like:** a judge can click any number and see where it came from (endpoint, field, scene date, run, formula) and can reproduce or cite it; an officer can open `/` and in under 10 seconds know what the satellite saw, when, how much of the area was actually measured, and what is *not* claimed.
- **Not a goal:** new science. The system stays physics-based, no ML, no LINE/push (CLAUDE.md §1). The UI never invents a number, a risk level, or an "all clear".

What the user said: beautiful, easy, highly academic, complete, correct, verifiable. Decisions taken here on the user's behalf (marked **Ruling**) are listed in §13.

## 2. Truth boundary (binding on every page)

1. Detection is at satellite pixel resolution (Sentinel-2 10/20 m native, read at the run's `scale_m`; MODIS ~1 km). Water-colour signatures only, never organisms.
2. Small or dispersed blooms may be missed.
3. Detection and prediction are separate claims. Today: index readings only; **no** Sentinel-2 anomaly score and **no** risk level (no valid baseline exists). MODIS `chlor_a` z-scores are a separate, same-quantity calculation and are labelled as such.
4. `null` means *unknown*, rendered `—` with the reason in words. Never `0`, never green, never "normal".
5. The four `--risk-*` colour tokens stay **unused** while risk evaluation is inactive. Data colour is the NDCI ramp only; the accent colour is interaction only (existing `tokens.css` rule, kept).
6. Every page ends with a persistent Truth-Boundary footer (text from `disclaimer` in the API response, shown verbatim, plus the three points above).

## 3. Information architecture

Shared shell: top bar (logo/title, 5 nav links, TH/EN toggle, "Cite" and "Data" shortcuts), page, footer. Deep-linkable; browser back/forward work.

| Route | Name (TH / EN) | Purpose | Data (all existing unless noted) |
|---|---|---|---|
| `/` | ภาพรวม / Overview | Current situation, honestly stated | `/summary`, `/raster-scan`, `/risk-map` |
| `/map` | แผนที่ราสเตอร์ / Raster map | Explore the area, inspect any cell, highlight pins | `/raster-scan`, `/raster-scan/overlay.png`, `/raster-scan/true-color.png`, `/raster-scan/pixel`, **new** `/raster-scan/highlights` |
| `/sites` | จุดเฝ้าระวัง / Monitoring sites | 7 fixed sites: table + per-site detail | `/risk-map`, `/risk-map/{id}/image`, `/timeseries` |
| `/methods` | วิธีการ / Methods | Indices, sensors, masks, references | **new** `GET /methods` |
| `/data` | ข้อมูลและข้อจำกัด / Data & limits | Provenance table, exports, limitations | `/raster-scan`, `/summary`, `/methods` |

`/raster` redirects to `/map`. `/sites/:siteId` is the detail view. Unknown routes show a 404 page with nav.

## 4. Pages

### 4.1 Overview `/`

1. **Status banner** (text derived only from API fields; table below). Never colour-coded as safe.
2. **Key facts** (4 cards, each with a source chip): *Newest scene date* (`/raster-scan.newest_scene_date`); *Measured area* (`coverage`, as % of the study polygon with a reading, with the "not measured ≠ low" note); *Scenes mixed* (`scene_count`, with link to the date-share chart); *Sites with a usable reading* (`risk_level_counts` → n of `total_sites`; `no_usable_data` and `not_checked_yet` shown separately and never merged).
3. **Map preview** (static NDCI overlay + legend + top-5 highlight pins per §4.6, link to `/map`).
4. **Sites strip**: seven chips (name, status, newest `actual_date`), linking to `/sites/:id`.
5. **Truth-boundary footer.**

Status-banner derivation (exhaustive; order = precedence):

| Condition | Headline |
|---|---|
| `/raster-scan.run_id` null | No raster is available yet — nothing has been measured (not "no bloom"). |
| any `stale_run_id` | Showing the last good raster (`date_used`); a newer scan did not complete. |
| `risk_level_counts.not_evaluated > 0` and risk gate inactive | Index readings are available for `n` of `N` sites. Bloom risk is **not evaluated**: no valid baseline exists. |
| gate active (future) | Risk tiers shown with their baseline version and provenance. |

All strings exist in both TH and EN; derivation is a pure function with tests (§11).

### 4.2 Raster map `/map`

Keeps the working Leaflet page and its logic; upgrades presentation:

- **Left rail (collapsible):** layer switcher (True Color / Light Map / NDCI, already built), legend (always includes the "transparent = not low/zero" caption, already built), scan coverage panel, **scene-date share bar chart** (`scene_dates[].share`), run provenance (run_id, `date_used`, `scale_m`, `completed_at`, selected scene IDs from `source_metadata`).
- **Cell inspector (right):** on click, `/raster-scan/pixel`. Shows `state` and `meaning`, the four indices with units/definitions linked to `/methods#ndci` etc., `acquired_date`, `acquired_at`, `cell_lat/lng` (observation) vs `pixel_centre_lat/lng` (drawn square), `scale_m` and the "one nearest-neighbour sampled native pixel, not an area average" statement, `run_id`.
- **Permalink:** `?lat=&lng=&run=&layer=&zoom=` is read on load and written on interaction, so a judge can open the exact cell.
- **Actions:** Copy citation, Copy permalink, Download this cell (CSV), Open raw JSON (new tab to the API URL).
- Pixel request is made only for map clicks, never for control clicks (regression guard already implemented; kept under test).
- **Highlight pins (user request, 2026-10-09).** Numbered pins mark where the served run's **NDCI is highest** — a descriptive ranking inside one scan, **not** a bloom-risk marking. Full rules in §4.6.

### 4.6 Highlight pins ("หมุดค่าสูงสุดในรอบสแกน")

**Why not "risk" pins.** There is no valid Sentinel-2 baseline and no validated NDCI threshold for this product and region, so any "at risk of bloom" pin would be an unsupported claim (CLAUDE.md §0/§1; `risk_evaluation.active` is false). A ranking by value needs no threshold and asserts nothing beyond the data: "these cells had the highest NDCI in this scan".

- **What a pin is.** The top *N* (default 5, user-adjustable 3–10) measured cells of the served run, ranked by NDCI, after spatial de-duplication (greedy non-maximum suppression: a cell is skipped if within `min_separation_m` — default 3000 m — of a higher-ranked pin), so five adjacent cells cannot fill the list. Only `state == "reading"` cells qualify; unmeasured/outside cells never get pins.
- **Appearance.** Numbered dark-neutral marker (shape distinct from the 7 monitoring-site markers). **Never** a risk colour, never red/amber, never the accent colour (reserved for interaction). A legend entry reads "Highest NDCI in this scan (rank within one image) — not a risk level".
- **Popup / inspector (per pin).** Rank *k* of *N*; NDCI and the other three indices; `acquired_date` and `acquired_at`; cell and pixel-centre coordinates; run_id; the cohort size (number of measured cells ranked); percentile of this cell within the run; `edge_of_no_data` flag (true when any of the 8 neighbouring cells in the raster is unmeasured — a **fact about the data**, shown as "next to unmeasured area: cloud edges and masks can distort index values"). Fixed caveat text: *high NDCI can also come from suspended sediment (e.g. river mouths), shallow bottom, sun glint or cloud edges; it does not by itself identify a bloom or a species.* Buttons: Zoom to cell, Copy permalink, Download CSV row, Open raw JSON.
- **Where they appear.** `/map` (all *N*, toggle "Show highlights", default on), `/` map preview (top 5, read-only), `/data` (table of the pins with all fields, CSV export). A pin list is also available in the `/map` left rail for keyboard users (each row focuses the pin).
- **Permalink.** `?pin=k&run=` restores the selection; pins are recomputed from the stored run so the same run always gives the same pins (deterministic tie-break: higher NDCI, then lower row, then lower column).
- **Honest empty states.** No run → no pins and the reason; run with fewer than *N* separable measured cells → fewer pins, stated; all-null NDCI → none.
- **Gate-ready, not gate-active.** If `risk_evaluation_active` becomes true in the future, the API may return a `risk_tier` per pin and the UI will show it with baseline provenance. While the gate is inactive the field is absent/null and the UI has no code path that renders a tier on a pin (tested).
- **If a true risk threshold is wanted.** It needs a validated baseline or published threshold for this sensor product and region, plus an independent (non-satellite-derived) validation set. That is a separate, explicit decision by the project owner; this spec does not pre-empt it.

### 4.3 Sites `/sites`, `/sites/:siteId`

- **Table** (sortable, keyboard accessible): name, lat/lng, status chip, `actual_date`, `cloud_fraction`, NDCI/2BDA/3BDA/B2÷B3 (from `index_values`), `index_used`, `fetched_at`, stale flag. Null cells `—` + tooltip reason (`confidence_label`/`error`). Column sources in a header popover.
- **Detail:** true-colour and NDCI images (cached PNGs) with date and cloud fraction; index values with definitions; **MODIS `chlor_a` series** (`/timeseries`: `chlor_a` mg m⁻³, `anomaly_z`) with the day-of-year climatology z-score, labelled "MODIS-Aqua, ≈1 km, 2002–present; same-quantity baseline", never combined with Sentinel-2 indices on one axis; data table beneath the chart (every plotted point, same numbers, downloadable CSV).
- No risk tier is shown while the gate is inactive; the status chip says "Index reading — risk not evaluated".

### 4.4 Methods `/methods`

Rendered from `GET /methods` (§6), so formulas, bands, thresholds and constants are **the values the code uses**.

1. Data sources: Sentinel-2 SR Harmonized (bands used, native 10/20 m, ~5-day revisit, `/10000` scale cancels in ratios), MODIS-Aqua `chlor_a`/SST (≈1 km), cloud and water masking, scene-age rule (`max_scene_age_days`).
2. Indices: NDCI (primary), 2BDA (algebraically tied to NDCI — flagged "not an independent signal"), 3BDA, B2/B3 (exploratory, not a species classifier). Each: formula, bands/wavelengths, role, display domain, and a **worked example computed by the server's own function** on fixed sample bands.
3. Why no ML; why no Sentinel-2 anomaly/risk yet (gate conditions, with the activation floors 30 independent dates / 14 days read from the code).
4. Raster method: study polygon, scale, mosaic of scenes (each cell keeps its own date), no-data semantics.
5. References: only those verified in `LIMITATIONS.md` (Mishra & Mishra 2012, DOI `10.1016/j.rse.2011.10.016`; Luang-on et al. 2023). A test asserts each DOI shown also appears in `LIMITATIONS.md`.

### 4.5 Data & limits `/data`

1. **Run table:** run_id, status, `date_used`, `scale_m`, cell/scene counts, oldest/newest scene date, `completed_at`.
2. **Exports (client-side from already-fetched JSON):** sites CSV, sites GeoJSON (`/risk-map` verbatim), MODIS series CSV (per site), cell CSV (from inspector). No bulk cell download.
3. **API reference:** the endpoints used, each with link, example and the schema field it supplies.
4. **Limitations:** the contents of `LIMITATIONS.md` summarised in Thai/English (static text in i18n files, reviewed against the file; a test asserts its section headings are all represented).
5. **Reproducibility:** app version, API version, commit short SHA (build-time), `/methods` gate state.

## 5. Verifiability features (shared components)

- **`SourceChip`** next to every number: opens a popover with *endpoint, field path, value, unit, observation date, run_id/scene ID (when known), formula link, "Open raw JSON"*. Keyboard operable.
- **`FigureFrame`**: numbered "Fig. n", caption, source chip, optional "View data table" disclosure, and CSV download.
- **`StatusChip`**: closed vocabulary — `Measured · Not measured · Outside study area · No usable data · Not checked yet · Not evaluated · Stale`. Mapping from API status to chip is one function with tests; no other labels.
- **`CiteButton`**: copies e.g. *"Plankton Watch (v`<version>`, `<sha>`), run `<id>`, scenes `<oldest>`–`<newest>`, accessed `<date>`. `<permalink>`"* in TH or EN; plain text, no formatting claims.
- **`Value`**: formats numbers (fixed decimals per field, tabular numerals, units, minus sign U+2212), renders `null` as `—` with reason.

## 6. Backend: `GET /methods` (additive, read-only)

New router `backend/src/routers/methods.py`; schema `MethodsResponse(DisclaimerMixin)`. No GEE call, no DB. Content:

```json
{
  "api_version": "0.1.0",
  "indices": [{"key":"ndci","name":"Normalized Difference Chlorophyll Index","formula":"(B5 - B4) / (B5 + B4)",
               "bands":["B5","B4"],"wavelengths_nm":{"B4":665,"B5":705,"B6":740},
               "role":"primary|derived|exploratory","note":"…",
               "display_domain":{"min":-0.05,"max":0.15},
               "worked_example":{"bands":{"B2":…,"B3":…,"B4":…,"B5":…,"B6":…},"value":0.0}}],
  "sentinel2": {"collection":"COPERNICUS/S2_SR_HARMONIZED","native_resolution_m":{"B2":10,"B3":10,"B4":10,"B5":20,"B6":20},
                "revisit_days":5,"scale_factor":10000,"max_scene_age_days":14},
  "modis": {"product":"MODIS-Aqua chlor_a","approx_resolution_m":1000,"record_start":"2002"},
  "gates": {"risk_evaluation_active":false,"signal_anomaly_active":false,
            "signal_anomaly_floors":{"min_independent_dates":30,"max_observation_age_days":14}},
  "references": [{"id":"mishra2012","citation":"…","doi":"10.1016/j.rse.2011.10.016"}, …],
  "disclaimer": "…"
}
```

Single-source rules: index `value` of the worked example is computed by calling `detection/src/indices.py` functions at request time; `gates` come from `scientific_status`; floors from the detection constants; `max_scene_age_days` from `default_max_scene_age_days()`; display domains from the data-pipeline `BAND_DOMAINS`. Static metadata (formula strings, roles, notes, wavelengths, references) sits in one new module next to the indices and is covered by tests (§11). Reached through the existing cross-project bridges (CLAUDE.md §8).

### 6.1 Backend: `GET /raster-scan/highlights` (additive, read-only)

Query: `run_id` (optional, default = the served run, same resolution as `/raster-scan/pixel`), `n` (3–10, default 5), `min_separation_m` (1000–10000, default 3000). Reads the run's stored cells blob like the pixel endpoint — **no GEE call**. Response `RasterHighlightsResponse(DisclaimerMixin)`:

```json
{"run_id": 4, "metric": "ndci", "ranking": "descending value within this run; not a risk level",
 "n_requested": 5, "min_separation_m": 3000, "cohort_size": 187560,
 "pins": [{"rank":1,"cell_lat":0.0,"cell_lng":0.0,"pixel_centre_lat":0.0,"pixel_centre_lng":0.0,
           "index_values":{"ndci":0.0,"bda2":0.0,"bda3":0.0,"b2_b3":0.0},
           "percentile":99.99,"acquired_date":"YYYY-MM-DD","acquired_at":"…Z",
           "edge_of_no_data":false,"risk_tier":null}],
 "reason": null}
```

Rules: only finite, date-valid cells; deterministic ordering and tie-break (§4.6); `percentile` computed over the same cohort; `risk_tier` is always `null` while the gate is inactive; 404 with the same wording as `/raster-scan/pixel` when no run/cells exist. The ranking helper lives in `backend/src/raster_scan/` beside `pixel.py` and is unit-tested on synthetic grids (de-duplication, tie-break, edge flag, fewer-than-N, empty).

## 7. Visual design

- **Character:** calm, high-density, printable — a scientific atlas, not a marketing page. Light theme only (**Ruling**); a print stylesheet for `/methods` and `/data` so they export cleanly to PDF.
- **Type:** Inter + Noto Sans Thai (UI, already loaded), IBM Plex Mono with `tabular-nums` for all numerals and codes; long-form prose on `/methods` and limitations in Source Serif 4 / Noto Serif Thai (**Ruling**, loaded the same way as existing fonts). Scale 12/14/16/20/28/40, line-height 1.5 (Thai 1.7).
- **Colour:** extend `tokens.css`, do not replace. Neutral surfaces, one interaction accent, data colour = existing NDCI ramp (domain from `legend`, never re-derived in the UI). No red/green semantics.
- **Layout:** 12-column grid, max width 1280 px, 8 px spacing unit; glass panels only over the map; cards with 1 px hairlines elsewhere.
- **Motion:** 150–200 ms opacity/transform only; `prefers-reduced-motion` disables it.
- **Responsive:** ≥1024 px two-column; 640–1023 single column, rail becomes a drawer; <640 nav collapses to a menu, tables become card lists, inspector becomes a bottom sheet.
- **Accessibility:** WCAG 2.1 AA contrast, visible focus ring, full keyboard path (map controls included), `aria-live` for the inspector, semantic landmarks and headings, colour never the only carrier (status chips carry text and an icon), `lang` attribute follows the toggle.

## 8. Internationalisation

- Thai default, English toggle, choice stored in `localStorage` (guarded with try/catch) and overridable by `?lang=th|en`; `<html lang>` updated.
- One dictionary per language under `frontend/src/i18n/`; keys must be identical in both (test). Scientific symbols, band names and formulas are never translated. API-supplied free text (disclaimer, `meaning`, `reason`) is shown verbatim and labelled as server text — never re-translated by the client.
- Dates in ISO `YYYY-MM-DD` (and UTC times with `Z`) in both languages, with a localised long form beside them only in prose.

## 9. Frontend architecture

- Routes in `main.jsx` (react-router, already installed); `App.jsx` becomes the shell. Pages in `src/pages/`, shared pieces in `src/components/ui/` (`SourceChip`, `FigureFrame`, `StatusChip`, `CiteButton`, `Value`, `TruthFooter`, `NavBar`, `LangToggle`).
- Pure logic in `src/lib/` (no React, node-testable): `statusBanner.js`, `statusChip.js`, `format.js`, `citation.js`, `permalink.js`, `csv.js`, `i18n.js`.
- Data layer keeps `src/api/client.js` + `useApi`; adds `getMethods()`. No client-side science: the UI derives labels and layout only.
- Reuse (already tested): `RasterOverlay`, `RasterLayerSwitcher`, `RasterLegend`, `RasterPixelPanel`, `RasterScanBanner`, `SatelliteImage`, `TimeSeriesChart`. Unrouted legacy pages (`AnomalyPage`, `AquaculturePage`, `ReportsPage`, `NdciPage`, `SummaryPage`, `Sidebar`) are audited in the plan: salvage truth-boundary-compliant parts, delete the rest in the final phase if nothing references them.
- Build adds `__APP_VERSION__` / `__GIT_SHA__` via Vite `define` (fallback `dev`).

## 10. States and errors

Every data block has four states with its own copy: *loading* (skeleton), *empty/unknown* (explains what "unknown" means), *error* (HTTP status, endpoint, retry), *stale* (shows the data and says it is stale and why). A 503 from GEE-config or auth is shown verbatim from the API `detail`. Partial failures (e.g. `/timeseries` fails for one site) degrade that block only.

## 11. Testing and verification

- **Unit (node:test, existing runner):** pin copy never contains risk wording and no code path renders a tier while the gate is inactive; i18n key parity TH/EN; `format` (null, rounding, minus sign, units); `statusBanner` over every row of the §4.1 table; `statusChip` over every API status; `citation`/`permalink` round-trip; `csv` escaping and column order; limitation headings coverage; DOIs match `LIMITATIONS.md`.
- **Component:** render-to-string of `Value`, `StatusChip`, `SourceChip` (popover content), `FigureFrame`, and the control-click-does-not-probe regression.
- **Backend (pytest):** `/raster-scan/highlights` ranking, de-duplication, tie-break, edge flag, null `risk_tier`; `/methods` schema; worked example equals hand arithmetic of the displayed formula; gates equal `scientific_status`; floors equal detection constants; DOIs ⊂ `LIMITATIONS.md`; no network/GEE.
- **Browser (Chrome, local stack):** every route at 1440×900, 1024×768, 390×844; screenshots reviewed for overlap, truncation, Thai line breaks; console clean; keyboard walkthrough; Lighthouse-style a11y spot check; permalink round-trip; TH↔EN toggle on each page; empty-DB and backend-down states.
- **Definition of done:** all suites green, lint and build clean, browser checklist passed with screenshots saved under `docs/screenshots/` (**Ruling**), README and `docs/FRONTEND_PLAN.md` updated.

## 12. Phases (for the implementation plan)

1. Backend `/methods` and `/raster-scan/highlights` + tests.
2. Shell, tokens, i18n, shared UI components + pure-logic modules with tests.
3. Overview.
4. Map upgrade (rail, scene-date chart, inspector provenance, permalink, actions, highlight pins §4.6).
5. Sites table + detail.
6. Methods.
7. Data & limits (+ print stylesheet).
8. QA pass in browser, legacy-page audit/cleanup, docs.

Each phase ships working software and is committed separately.

## 13. Rulings taken on the user's behalf

- Bilingual TH/EN, Thai default; English toggle (researchers + officials audience).
- Light theme only, plus print stylesheet; no dark mode.
- Serif for long-form prose only; sans for UI.
- Two additive backend endpoints: `/methods` (rather than duplicating formulas in the frontend, to keep them verifiable) and `/raster-scan/highlights`.
- Pins mark the **highest NDCI in the scan**, not bloom risk (user asked for "risk" pins; no validated baseline/threshold exists, so a risk label would overclaim). Neutral marker, never a risk colour; a risk tier can attach only when the gate is active.
- References limited to those already verified in `LIMITATIONS.md`; none added from memory.
- No historical raster browser, no bulk cell export, no write actions (out of scope).
- Screenshots committed as verification evidence.

## 14. Risks

- **Thai typography** (line breaking, tone-mark clipping) — mitigated by 1.7 line-height and browser checks at three widths.
- **Overclaiming through polish** — a handsome dashboard can imply authority; mitigated by §2 (null rules, closed status vocabulary, footer, no risk colours).
- **Scope** — five pages; phases are independent so the work can stop after any phase with a coherent site.
- **Uncommitted user edits** in frontend files — plan phases must read current files before changing them and commit only their own work.

## 15. Out of scope

LINE/push, ML, new satellite processing, authentication, deployment, dark mode, backend changes other than `/methods` and `/raster-scan/highlights`, any threshold-based "at risk" marking.
