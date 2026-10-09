# Academic Dashboard (Frontend) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single-map page with a bilingual (TH default / EN) multi-page academic dashboard — Overview, Raster map (with highlight/anomaly pins and a provenance-rich cell inspector), Monitoring sites, Methods, Data & limits — where every number can be traced to its endpoint, field, scene date, run and formula.

**Architecture:** Pure, node-testable logic in `src/lib/` and `src/i18n/` (no React); a small set of shared UI components in `src/components/ui/`; pages in `src/pages/`; routes in `main.jsx`. All data comes from the existing API (nothing computed client-side except labels/layout). Existing, already-tested raster components are reused and extended, not rewritten.

**Tech Stack:** React 19, react-router-dom 7, Leaflet/react-leaflet 5, recharts 3, axios, Vite 8, `node --test` for tests (`npm test` = `node --test tests/*.test.js`), oxlint.

**Specs:**
- `docs/superpowers/specs/2026-10-09-academic-dashboard-design.md` (primary: pages, truth boundary, visual design, i18n, verifiability components)
- `docs/superpowers/specs/2026-10-09-test-baseline-and-latest-scene-design.md` §5-§8 (TEST banner/labels, anomaly pins, latest-scene messages, truth-boundary additions)
- Backend plan (already implemented): `docs/superpowers/plans/2026-10-09-backend-baseline-and-latest-scene.md`.

## Global Constraints

- **Truth boundary (binding on every string and every layout):** detection is satellite-pixel level; small/dispersed blooms may be missed; detection and prediction are separate claims; `null` renders as `—` with a stated reason, never `0`, never green, never "normal" unless the API's own status says so; **no risk wording or risk colours anywhere** (the four `--risk-*` tokens stay unused; `risk_level` is always null in the API); the accent colour is for interaction only; pins mean "highest NDCI in this scan" (mode `ndci`) or "anomaly vs own seasonal history, TEST baseline" (mode `anomaly`) — never "bloom" or "risk". When `baseline.mode == "test"` a persistent banner appears on every page and every anomaly chip carries "(TEST)".
- **Two server disclaimers exist** (`disclaimer` field; a TEST variant when a valid test baseline is in force). Show the server's `disclaimer` verbatim wherever a response's data is shown; never re-translate it; label it as server text.
- **No client-side science.** The UI never computes z-scores, NDCI, thresholds or classifications; it formats and arranges what the API returns. Allowed derivations: unit/format conversions, sorting, counts of rows, percentages of API-provided counts.
- **API shapes are the contract** — read `backend/src/schemas.py` for exact field names before using any field (`RasterScanResponse` incl. `latest_scene`, `last_used_scene_date`, `poll`; `RasterPixelResponse` incl. `anomaly`; `RasterHighlightsResponse`; `RiskMapProperties`/`RiskMapResponse.baseline`; `SummaryResponse`; `TimeseriesResponse`; `MethodsResponse` incl. `quality_screens`, `season_windows`, `latest_scene_policy`). MODIS is reported at 4638 m by `/methods` — use the API value (the older "~1 km" claim is wrong for the Level-3 grid).
- **i18n:** every user-visible string comes from `src/i18n/{th,en}.js` through `t(key, params)`; both files must have identical key sets (test). Scientific symbols, band names, formulas, units, DOIs and API-supplied free text are never translated. Dates ISO `YYYY-MM-DD`, times UTC with `Z`.
- **Accessibility:** WCAG 2.1 AA contrast, visible focus, full keyboard path, landmarks and heading order, `aria-live` for the inspector, colour never the sole carrier, `lang` attribute follows the toggle, `prefers-reduced-motion` honoured.
- **Responsive:** ≥1024 two-column; 640–1023 single column with the rail as a drawer; <640 nav collapses, tables become card lists, inspector becomes a bottom sheet.
- **Tests:** logic modules and components must be testable under `node --test` without a DOM (pure functions; components via `react-dom/server` `renderToStaticMarkup` or by calling pure render helpers). Map components that need `leaflet` use the existing `leaflet` alias fixture (see `tests/rasterLayerSwitcher.test.js`; real `leaflet` throws "window is not defined" in Node). `npm run lint` and `npm run build` must stay clean.
- **Existing work:** the tree has many uncommitted/committed user edits in `frontend/`; read each file before editing, keep edits local, reuse `RasterOverlay`, `RasterLayerSwitcher`, `RasterLegend`, `RasterPixelPanel`, `RasterScanBanner`, `SatelliteImage`, `TimeSeriesChart`, `useApi`; never revert user changes. Subagent commits are denied by the harness: implementers leave changes uncommitted; the controller commits (trailers `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_01PTmXbZHuaq2gQcPCx9uDuf`).
- **Browser verification** is done by the controller with Chrome against the live local stack (backend :8000 started with `BASELINE_MODE=test`, Vite :5173 proxies `/api`). Implementers cannot open a browser: they say so and rely on tests/build.
- Suites: `cd frontend && npm test && npm run lint && npm run build`. Frontend baseline before this plan: 54 tests.

## Review Focus

- A number displayed without a working source reference, or `null` shown as `0`/blank. (Tasks 1-2)
- Any risk wording/colour, or a pin legend that reads as a risk marking. (Task 4)
- TH/EN key drift and untranslated server text. (F1)
- Control clicks on the map triggering pixel requests (regression guard exists; keep). (Task 4)
- Stale data presented as current (poll failed, no newer scene, stale run). (Tasks 3-4)
- Truncated Thai text and overlapping panels at 390/1024/1440 widths. (Task 8, controller)

---

## Task 1: Logic foundations — i18n, formatting, status vocabulary, provenance, citation, permalink, CSV

**Files:**
- Create: `frontend/src/i18n/{index.js,th.js,en.js}`, `frontend/src/lib/{format.js,statusChip.js,statusBanner.js,provenance.js,citation.js,permalink.js,csv.js,buildInfo.js}`
- Modify: `frontend/src/api/client.js` (add `getMethods()`, `getHighlights(params)`; extend `getRasterPixel` unchanged), `frontend/vite.config.js` (define `__APP_VERSION__`, `__GIT_SHA__`, with `dev` fallbacks)
- Test: `frontend/tests/{i18n,format,statusChip,statusBanner,provenance,citation,permalink,csv}.test.js`

**Interfaces (exact names; later tasks import these):**
- `i18n/index.js`: `SUPPORTED = ['th','en']`; `detectLang({search, storage, navigatorLang}) -> 'th'|'en'` (priority `?lang=` > storage `plankton.lang` > default `'th'`; storage access guarded by try/catch); `createT(lang) -> (key, params?) => string` (`{name}` interpolation; missing key → returns the key itself AND records it in `missingKeys` for tests; never throws); `missingKeys: Set`.
- `lib/format.js`: `formatValue(value, spec) -> {text, isNull, reason}` where `spec = {decimals, unit?, kind: 'index'|'fraction'|'percent'|'count'|'date'|'datetime-utc'|'coord'|'ms'|'mg-m3'|'z'}`; `null/undefined/NaN/Infinity → {text:'—', isNull:true, reason:<passed or 'not_available'>}`; uses U+2212 for negatives, tabular digits left to CSS; `0` is rendered `0.000` (a real zero stays a zero); `percent` takes a 0–1 fraction; `datetime-utc` outputs `YYYY-MM-DD HH:MMZ`.
- `lib/statusChip.js`: closed vocabulary `STATUS = {MEASURED, NOT_MEASURED, OUTSIDE_STUDY_AREA, NO_USABLE_DATA, NOT_CHECKED_YET, NOT_EVALUATED, STALE}`; `chipForPixelState(state)` (`reading`→MEASURED, `not_measured`, `outside_study_area`), `chipForSite(properties)` (from `status` ∈ ok/no_imagery/no_water_pixels/no_climatology/error/no_data_yet, `stale`, and `risk_level == null`: an `ok` site with no anomaly is `MEASURED` plus a separate `NOT_EVALUATED` note; `no_data_yet`→NOT_CHECKED_YET; others→NO_USABLE_DATA; stale flag adds STALE), `chipForAnomalyLevel(level, isTest)` (`normal|watch|high|null`; labels always carry the TEST marker when `isTest`; no colour names in the return value — only `tone: 'neutral'|'attention'|'strong'|'muted'` and `hatch: bool`). Each chip: `{key, tone, hatch, icon}`; the human text comes from i18n keys `status.<key>`.
- `lib/statusBanner.js`: `deriveBanner({raster, summary, baseline}) -> {key, params, tone}` implementing the dashboard spec §4.1 table exactly (precedence order) plus the TEST-baseline line; keys are i18n keys. Cases: no raster; stale run; poll failing/old (`poll.last_error` or `last_poll_ok_at` older than 3 h → "newer scenes may exist that were not checked"); newest scene rejected for cloud (`latest_scene.decision != 'passed'` and newer than `last_used_scene_date`); indices available/risk not evaluated; test baseline active.
- `lib/provenance.js`: `sourceRef({endpoint, field, value, unit, observedDate, runId, sceneId, formulaKey, params}) -> {endpoint, field, url, rows[]}` building the popover rows and the raw-JSON URL via `apiAssetUrl`; `refForPixelField(pixel, field)`, `refForSiteField(feature, field)`, `refForRasterField(raster, field)` helpers.
- `lib/citation.js`: `buildCitation({lang, version, sha, runId, oldestScene, newestScene, accessedAt, permalink, baselineVersion?}) -> string` (plain text; TEST baseline version included when present; no claims beyond provenance).
- `lib/permalink.js`: `encodeView({lat,lng,runId,layer,zoom,pin,lang}) -> query string`, `decodeView(search) -> object` with validation (invalid numbers dropped, layer ∈ ndci|light_map|true_color, ranges checked) — round-trip tested; never includes personal data.
- `lib/csv.js`: `toCsv(columns, rows) -> string` (RFC 4180 escaping, `\r\n`, UTF-8 BOM optional flag, null → empty cell), plus `sitesCsv(riskMap)`, `timeseriesCsv(ts)`, `pinsCsv(highlights)`, `cellCsv(pixel)` with fixed documented column orders that include source/run/date columns.
- `lib/buildInfo.js`: `appVersion`, `gitSha` read from the Vite defines with node-safe fallbacks.

- [ ] **Step 1: Failing tests** (all files under `tests/`): i18n key parity TH/EN (read both modules, compare deep key sets, no empty strings, same `{param}` placeholders per key); `detectLang` priority and storage failure (a storage whose getItem throws); `createT` interpolation and missing-key recording; `formatValue` for every kind incl. null/NaN/±Infinity, real zero, negative with U+2212, percent, datetime; `chipFor*` exhaustive tables (every API status string mapped; unknown → NO_USABLE_DATA, never MEASURED); `deriveBanner` for every case in precedence order with fixture payloads; `sourceRef` rows; `buildCitation` TH and EN snapshots; `encodeView`/`decodeView` round trip and rejection of garbage; `toCsv` escaping (commas, quotes, newlines), null handling, fixed columns for each exporter.
- [ ] **Step 2: Run, expect FAIL** (`cd frontend && npm test`).
- [ ] **Step 3: Implement.** i18n dictionaries start with the keys the foundations need (status vocabulary, banner texts, citation labels, nav, common words, truth-boundary footer lines incl. the three binding points and the TEST banner text from spec §5, null-reason texts) and grow in later tasks; add `getMethods`, `getHighlights` to `client.js`; `vite.config.js` defines.
- [ ] **Step 4: Run tests, lint, build.** Expect all green.
- [ ] **Step 5: Report** (files, evidence; do not commit).

---

## Task 2: Shell, tokens, routing and shared UI components

**Files:**
- Create: `frontend/src/components/ui/{NavBar,LangToggle,TruthFooter,BaselineBanner,SourceChip,FigureFrame,StatusChip,CiteButton,Value,PageHeader,EmptyState,ErrorState}.jsx`, `frontend/src/i18n/LangContext.jsx`, `frontend/src/hooks/useBaseline.js`, `frontend/src/pages/NotFoundPage.jsx`
- Modify: `frontend/src/main.jsx` (routes), `frontend/src/App.jsx` (shell), `frontend/src/styles/tokens.css` and `global.css` (additive: type scale, serif prose class, spacing, card/figure/table/chip classes, print stylesheet skeleton), `frontend/index.html` (`lang`, title, meta description, favicon unchanged), `frontend/src/components/RasterLegend.jsx` only if a shared caption helper is needed
- Test: `frontend/tests/ui_components.test.js`

**Behaviour:**
- Routes: `/` Overview, `/map`, `/sites`, `/sites/:siteId`, `/methods`, `/data`; `/raster` → redirect to `/map`; `*` → NotFoundPage with the nav. Pages that do not exist yet render a clearly labelled placeholder via `EmptyState` (later tasks replace them) so the shell can be verified in a browser.
- `LangContext`/`useLang()` provide `{lang, setLang, t}`; toggling updates `<html lang>`, storage (guarded), and `?lang=`; no full reload.
- `useBaseline()` fetches `/methods` once (shared via a module-level promise cache) and exposes `{mode, valid, version, isTest, status}`; failure → `isTest:false` plus an inline note, never blocks pages.
- `BaselineBanner`: shown on every page when `isTest` (TEST text from i18n); when the baseline is test mode but invalid it says so with the reason.
- `TruthFooter`: the three binding points + the server `disclaimer` (prop, shown verbatim, labelled as server text), the app version/git SHA, link to `/methods` and `/data`.
- `SourceChip`: a small icon button (`aria-label`, keyboard focusable) that toggles a popover (Esc closes, focus returns) showing `rows[]` from `sourceRef` and an "Open raw JSON" link; no popover content is fabricated: rows with unknown values show `—`.
- `FigureFrame`: `Fig. n` numbering via props, caption, children, optional `dataTable` slot disclosure and CSV button.
- `StatusChip`: text + icon + tone/hatch class from the chip descriptor; never colour-only.
- `Value`: wraps `formatValue`, renders `—` with `title`/visually-hidden reason for nulls, optional `SourceChip`.
- `CiteButton`: builds the citation with `buildCitation`, copies via `navigator.clipboard` with a guarded fallback, shows a polite confirmation (`aria-live`), never throws.
- Visual system per spec §7: light theme, Inter + Noto Sans Thai UI, IBM Plex Mono tabular numerals, Source Serif 4 / Noto Serif Thai for long prose only (add to the Google Fonts `@import`), 12-column grid max 1280, 8 px unit, hairline cards, glass only over the map, reduced-motion respected, print stylesheet hides nav/controls and avoids breaking figures.

- [ ] **Step 1: Failing tests** (render with `renderToStaticMarkup`): `Value` null → `—` + reason text and no `0`; real zero → `0.000`; `StatusChip` for each descriptor renders text+icon, `data-tone`/`data-hatch` attributes and no risk class names; `SourceChip` markup contains endpoint/field rows; `TruthFooter` includes the server disclaimer verbatim and all three points in both languages; `BaselineBanner` renders only when `isTest`; `NavBar` lists the 5 routes in both languages with the active link marked `aria-current`; a source-level test greps `src/components/ui` and `src/pages` for forbidden risk strings (`risk-normal`, `risk-elevated`, `risk-watch`, `risk-warning`, `RISK_COLOR`) to keep the risk tokens unused.
- [ ] **Step 2–4:** fail, implement, green; `npm test && npm run lint && npm run build`.
- [ ] **Step 5: Report.**

---

## Task 3: Overview page (`/`)

**Files:** Create `frontend/src/pages/OverviewPage.jsx`, `frontend/src/components/OverviewMapPreview.jsx`; modify `main.jsx` route; i18n additions; Test `frontend/tests/overview.test.js`.

**Behaviour (spec §4.1):** status banner from `deriveBanner`; 4 key-fact cards (newest scene date; measured area as a share of the study polygon with the "not measured ≠ low" note; scenes mixed; sites with a usable reading with `no_usable_data` and `not_checked_yet` shown separately) each with `SourceChip`; latest-scene line from `raster.latest_scene` ("used" / "not used: cloud x % > y %", settled flag, "re-assessed as not passing after use" when `reassessed_after_use`); poll status line from `raster.poll` (age of `last_poll_ok_at`; the error kind when present; wording that a failing/old poll means newer scenes may exist unchecked); map preview (static `<img>` overlay from `apiAssetUrl(overlay_url)` over a Leaflet map or a bounds-fitted figure with legend swatches from `raster.legend`) + top-5 pins from `getHighlights({n:5})` (mode returned by the API; legend text from i18n; link to `/map`); sites strip (7 chips: name, `StatusChip`, newest `actual_date`, link). Each data block has loading/empty/error/stale states with distinct copy. Server `disclaimer` shown through `TruthFooter` from whichever response loaded.

- [ ] **Step 1: Failing tests:** pure view-model builder `buildOverviewModel({raster, summary, riskMap, highlights, baseline, now})` (put it in `src/lib/overviewModel.js`) → cards/lines/chips; cases: no raster; stale run; poll error; newest scene rejected; used scene; test baseline on; no pins (reason shown); sites mix of ok/no_imagery/no_data_yet; all strings are i18n keys present in TH and EN; no `0` for nulls; `not_checked_yet` never merged into `no_usable_data`.
- [ ] **Step 2–4:** fail, implement, green; full frontend suite, lint, build.
- [ ] **Step 5: Report.**

---

## Task 4: Raster map upgrade (`/map`) — rail, provenance inspector, pins, permalink, actions

**Files:** Modify `frontend/src/pages/RasterPage.jsx` (becomes the `/map` page), `RasterPixelPanel.jsx`, `RasterScanBanner.jsx` (only to remove duplicated claims now carried by the rail; keep its tested content), `RasterLegend.jsx`; Create `frontend/src/components/{RasterRail,SceneDateChart,HighlightPins,PinList,PinLegend}.jsx`, `frontend/src/lib/mapModel.js`; i18n additions; Tests `frontend/tests/{map_model,pins,pixel_panel}.test.js` (+ keep existing raster tests green).

**Behaviour (spec §4.2, §4.6, test-baseline §6):**
- Left rail (collapsible; drawer <1024): layer switcher (exists), legend (exists, caption retained in every mode), coverage and run provenance (run_id, `date_used`, `scale_m`, `completed_at`, selected scene ids from `source_metadata`), `SceneDateChart` (bars for `scene_dates[].share`, text alternative table), latest-scene + poll lines as on Overview, and the **pin list** (keyboard path: each row focuses/selects its pin).
- Pins layer: `getHighlights({n, min_separation_m, mode})` where `mode` is the API's chosen mode (default call without `mode`); N selectable 3–10; toggle "Show highlights" (default on). Numbered neutral-dark markers (shape distinct from site markers); popup/inspector shows rank, NDCI, other indices, `acquired_date/at`, cell vs pixel-centre coordinates, run_id, percentile, `edge_of_no_data` text, `robust_z`/`median_ndci`/`mad`/`n_dates`/`anomaly_level` (anomaly mode, with "(TEST)") and `visible_bands_dn`, the fixed caveat (sediment, shallow bottom, glint, cloud edges), counts block (`measured/assessable/…reason buckets/watch/high/flagged_share`, `excluded_degenerate`, `excluded_low_signal`, `quality_note`) explained in plain words, and the server disclaimer. Legend entry text from i18n: "Highest NDCI in this scan (rank within one image) — not a risk level" / "Anomaly vs own seasonal history, TEST baseline — not a risk level". `409`/error from the endpoint is shown with its reason (e.g. `mode_off`), never as "no pins".
- Cell inspector (`RasterPixelPanel`): `state` + `meaning`; four indices with `Value`+`SourceChip` and definition links to `/methods#<index>`; `acquired_date`/`acquired_at`; `cell_*` vs `pixel_centre_*`; `scale_m` sampling statement; `run_id`; the `anomaly` block when present (z, median, MAD, n dates, level with TEST label, reason when null, season key, baseline version) and `visible_bands_dn`; buttons: Copy citation, Copy permalink, Download cell CSV (`cellCsv`), Open raw JSON.
- Permalink: `decodeView(location.search)` on load (lat/lng → selects the cell and flies to it; `pin` → selects that pin; `layer`, `zoom`, `run`), `encodeView` written with `history.replaceState` on interaction; a permalink to a run that is no longer served shows a clear "that run is no longer available" note and loads the latest.
- Control clicks never trigger a pixel request (keep the existing guard and its test).
- Everything uses `useBaseline()`/server fields; no client-side z computation.

- [ ] **Step 1: Failing tests:** `mapModel` (pin → popup view-model for ndci and anomaly modes incl. null fields; counts block → ordered rows with plain-language keys and a partition check display; legend text selection by mode; permalink apply/serialize); `PinList` markup (rows keyboard-focusable, rank order); a source test that no pin/legend i18n string contains "risk"/"เสี่ยง" except in the negation phrase; the pixel panel renders the anomaly block and TEST label only when `anomaly != null`, and renders `—` + reason for null z; existing `rasterLayerSwitcher`, `rasterPixel`, `rasterOverlay`, `rasterRunBinding`, `rasterScanBanner` tests stay green (update only where the page structure intentionally changed; list each).
- [ ] **Step 2–4:** fail, implement, green; `npm test && npm run lint && npm run build`.
- [ ] **Step 5: Report.**

---

## Task 5: Monitoring sites (`/sites`, `/sites/:siteId`)

**Files:** Create `frontend/src/pages/{SitesPage,SiteDetailPage}.jsx`, `frontend/src/components/{SitesTable,SiteImages,ModisSeries}.jsx`, `frontend/src/lib/sitesModel.js`; reuse `TimeSeriesChart`, `SatelliteImage`; i18n additions; Tests `frontend/tests/sites_model.test.js`.

**Behaviour (spec §4.3):** `/sites`: sortable, keyboard-accessible table from `/risk-map` (name, lat/lng, status chip, `actual_date`, `cloud_fraction`, the four indices, `index_used`, `fetched_at`, stale flag, anomaly chip `signal_anomaly_level` + `signal_robust_z` with "(TEST)" only when `baseline` is test/valid, `signal_anomaly_reason` for nulls); header popovers give each column's source; mobile card list; CSV and GeoJSON export. `/sites/:siteId`: true-colour and NDCI images via `true_color_image_url`/`ndci_heatmap_image_url` with date and cloud fraction (absent URL → stated reason from `image_status` when available else "no cached image"), index values with `Value`/`SourceChip`/links to `/methods#…`, the TEST anomaly block (z, level, reason, baseline version) and the site's baseline support from `baseline.min_season_dates_by_location[site_id]`, MODIS `chlor_a` series from `/timeseries` (mg m⁻³ with `anomaly_z` labelled "MODIS-Aqua day-of-year climatology, same-quantity baseline", resolution from `/methods.modis.grid_resolution_m`) with a data table beneath and CSV, never combined with Sentinel-2 indices on one axis; a `/timeseries` failure degrades that block only; unknown `siteId` → NotFound.

- [ ] **Step 1: Failing tests:** `sitesModel` sorting stable and null-last; row view-models for every status incl. `no_data_yet`; export builders (`sitesCsv` columns and `GeoJSON` passthrough equals API); anomaly chip only when baseline valid and level non-null; MODIS series table rows equal the API points.
- [ ] **Step 2–4, Step 5:** as above.

---

## Task 6: Methods page (`/methods`)

**Files:** Create `frontend/src/pages/MethodsPage.jsx`, `frontend/src/components/{IndexCard,GateTable,ReferenceList}.jsx`; i18n additions (long-form prose keys); Tests `frontend/tests/methods_model.test.js`.

**Behaviour (spec §4.4):** rendered from `getMethods()`: data sources (Sentinel-2 collection, bands/wavelengths present in the API only, native resolutions, revisit, `/10000` scale-cancels note, scene-age rule; MODIS at the API's resolution with the API's note); one anchored `IndexCard` per index (`#ndci`, `#2bda`, `#3bda`, `#b2_b3_ratio`): name, formula, bands, role chip, the note (2BDA "not an independent signal"), display domain, worked example with its bands and server-computed value; masks and quality screens (`quality_screens`: degenerate ±1 rule, low-signal 50 DN rule labelled "developer-chosen, not validated"); the TEST baseline section (season rule and `season_windows`, preprocessing signature, history range, per-site weakest-season support, the Level A self-check base rates from `baseline.base_rates` with the sentence that these describe the statistic on its own past, not accuracy; Level B summary) shown only when `baseline.mode == 'test'` with an explanation of why it is off otherwise; gates table (`risk_evaluation_active`, `signal_anomaly_active`, floors); latest-scene policy values; references list exactly as returned (DOIs as links); long-form prose in the serif class; print stylesheet makes the page PDF-friendly. Server `disclaimer` shown verbatim.

- [ ] **Step 1: Failing tests:** model builder from a `/methods` fixture → sections in order; baseline section omitted in mode off (with the off-explanation key); every displayed number maps to a field (no literals: a test greps the page source for numeric literals in JSX other than layout); anchors exist for each index key returned; references rendered verbatim.
- [ ] **Step 2–4, Step 5.**

---

## Task 7: Data & limits (`/data`) and exports

**Files:** Create `frontend/src/pages/DataPage.jsx`, `frontend/src/components/{RunTable,ApiReference,LimitationsList}.jsx`; i18n additions; Tests `frontend/tests/data_model.test.js`.

**Behaviour (spec §4.5):** run provenance table for the served run and, when available, the stale run (run_id, status, `date_used`, `scale_m`, cell/scene counts, oldest/newest scene date, `completed_at`) — only data the API returns (no run history endpoint exists; say so); latest-scene assessments summary from `raster.latest_scene`/`last_used_scene_date`/`poll`; the current highlight pins as a table with all fields + CSV; exports (sites CSV/GeoJSON, MODIS series CSV per site, pins CSV); API reference (each endpoint used, example link, the schema fields it supplies); limitations: the content of `LIMITATIONS.md` summarised in TH/EN (static i18n text; a test asserts every `##` heading of `LIMITATIONS.md` is represented by an i18n key listed in a mapping file) incl. the TEST-baseline limits (§8 of the test-baseline spec); reproducibility block (app version, API version from `/methods`, git SHA, baseline version); print stylesheet.

- [ ] **Step 1: Failing tests:** limitations coverage test (reads `../LIMITATIONS.md` headings); pins table columns equal `pinsCsv` columns; run table null handling; every export button's builder produces the documented column order.
- [ ] **Step 2–4, Step 5.**

---

## Task 8: Integration QA, legacy cleanup and docs (controller + one implementer)

**Files:** delete only unreferenced legacy files after a grep proves nothing imports them (`AnomalyPage`, `AquaculturePage`, `ReportsPage`, `NdciPage`, `SummaryPage`, `Sidebar`, `AnomalyStrip`, `RegionTrendChart`, `RiskLegend`, `StatCard`, `MapControls`… — verify each; keep anything a new page reuses); update `README.md`, `backend/README.md` (cooldown flow → latest-scene policy), `docs/FRONTEND_PLAN.md`, `docs/DETECTION_PLAN.md` (§ cooldown), `LIMITATIONS.md` (TEST-mode paragraph, MODIS grid 4.6 km, the two quality screens, the "no cell self-check" limit), `CLAUDE.md` §0/§1 (record the TEST baseline as an explicitly gated, off-by-default, uncalibrated mode; correct "~1 km" MODIS to the Level-3 grid; do not alter the locked decisions table beyond adding rows that state this).

- [ ] **Step 1 (controller, Chrome):** for each route at 1440×900, 1024×768 and 390×844: screenshot, console clean, keyboard walk (Tab order, Esc closes popovers), TH↔EN toggle, permalink round trip, copy-citation, CSV download (file content check), empty/error states (stop the backend briefly, or point to a bad base URL), print preview of `/methods` and `/data`. Save the screenshots under `docs/screenshots/`.
- [ ] **Step 2:** fix findings (implementer dispatches for each cluster of issues, each followed by a re-check).
- [ ] **Step 3:** docs and cleanup task for the implementer; `npm test && npm run lint && npm run build`; backend/data-pipeline/detection suites once more.
- [ ] **Step 4: Report.**

---

## Self-Review

1. **Spec coverage.** Dashboard spec §3 routes → F2; §4.1 → F3; §4.2/§4.6 → F4; §4.3 → F5; §4.4 → F6; §4.5 → F7; §5 components → F1/F2; §7 visual → F2 (+ per-page); §8 i18n → F1; §10 states → every page task; §11 testing → each task + F8. Test-baseline spec §5 labelling/banner → F2/F4/F5; §6 pins → F4; §7 latest-scene messaging → F3/F4/F7; §8 truth additions → F6/F7.
2. **Placeholders.** None intended; F5–F7 deliberately say "read `schemas.py` for exact names" because the API is the contract.
3. **Names.** `createT`, `detectLang`, `formatValue`, `chipFor*`, `deriveBanner`, `sourceRef`, `buildCitation`, `encodeView/decodeView`, `toCsv` + exporters, `useBaseline`, `useLang`, `buildOverviewModel`, `mapModel`, `sitesModel` are used consistently.
4. **Review Focus.** Null-as-zero and missing source refs → F1/F2 tests; risk wording/colour → source greps in F2/F4; i18n parity → F1; control clicks → F4 (existing guard); stale-as-current → F3/F4 banner cases; layout → F8 browser pass.
