# HAB Sentinel Dashboard — Design Spec

Date: 2026-08-26
Status: Approved, proceeding to implementation plan
Scope: `/frontend` only. No backend changes — existing routers (`/risk-map`, `/timeseries`, `/detect`, `/satellite-image`, `/summary`, `/validation`) cover all real data needs.

## Why

Replace the current 3-page top-nav app (RiskMapPage, SummaryPage, ValidationPage) with a 5-screen sidebar-nav dashboard, "HAB Sentinel", styled as a macOS Sequoia-style native app. Consolidates existing components into richer per-screen layouts and adds two new screens (Aquaculture Zones, Reports & Exports) that were previously out of scope.

Truth-boundary rules from CLAUDE.md carry over unchanged: no fabricated data, no percentage claims on n=14, rule-based (non-ML) framing stated wherever risk/confidence is shown, per-pixel resolution caveat present.

## Design System

- Colors: white `#FFFFFF`, panel gray `#F5F5F7`, card surface `#FAFAFA`, dividers `#E5E5EA` / `#F0F0F2`, text `#1D1D1F` / `#6E6E73` / `#8E8E93` / `#AEAEB2`. Accent `#0071E3` (hover `#0058B4`). Status: normal/sage `#34C759`, watch/amber `#FF9F0A`, warning/coral `#FF3B30`, no-data gray `#E5E5EA` w/ `#AEAEB2` dashed border.
- Fonts: Inter + Noto Sans Thai (UI text), IBM Plex Mono (all numbers/coordinates/dates).
- Radii: 12–14px cards, 7–9px controls, 999px pills. Card shadow `0 1px 3px rgba(0,0,0,0.06)`.
- Floating glass elements: `rgba(255,255,255,0.86)` + `backdrop-filter: blur(20px) saturate(180%)` + `0.5px solid rgba(0,0,0,0.06)` border.

This supersedes the "clean light theme" from commit `611cf84`.

## Navigation Shell

Sidebar, 240px, `#F5F5F7` background, right border `#E5E5EA`.

- Header: 28px blue rounded-square logo mark (satellite/wave icon), "HAB Sentinel" title + "อ่าวไทยตอนบน" subtitle.
- Status pill: green dot + "ระบบทำงานปกติ" on `rgba(52,199,89,0.10)`.
- Nav, 5 items, icon+label, active = blue tint pill `rgba(0,113,227,0.10)` + blue text:
  1. ภาพรวม/แผนที่ (map icon) → `/`
  2. Sentinel-2 NDCI → `/ndci`
  3. ความผิดปกติตามฤดูกาล → `/anomaly`
  4. พื้นที่เพาะเลี้ยงสัตว์น้ำ → `/aquaculture`
  5. รายงานและการส่งออก → `/reports`
- Footer: "GEE API Connected" outlined pill + green dot; "ตั้งค่าระบบ" settings button (gear icon + label, no avatar/login).

All 5 nav items are live routes.

## Screen 1 — ภาพรวม/แผนที่ (Overview/Map)

Flex row: map fills remaining width, 360px analytics panel on right.

**Map** (reuses `RiskMap.jsx`): real Leaflet, Esri World Imagery (true color) or CartoDB light (risk view) tiles; 6 real grid-site circle markers (13px radius) colored by risk, dashed gray for no-data, hover tooltip with name + status.

**NDCI raster mode** (new): canvas-generated domain-warped noise field rendered as an image overlay on a diverging ramp (dark blue → pale cyan → orange → dark red), toggled via the segmented control — not a CSS filter. This is a decorative/illustrative overlay, not real per-pixel index data (no such raster endpoint exists); must be labeled as such in the legend/footnote so it isn't mistaken for a live product.

**Floating controls:**
- Segmented control (top-left): True Color (RGB) / NDCI Index (20m) / แผนที่ความเสี่ยง (rule-based) — functional, switches map mode.
- Date-range pill (top-right area): calendar icon + date range text + chevron — presentational, not wired.
- Zoom control (+/−), stacked, top-right — functional.
- Legend (bottom-left, draggable): "NDCI Index" label, gradient bar, min/mid/max labels (−0.10 / 0.10 / >0.35), plus "ไม่มีค่าอ่าน — ไม่ใช่ระดับเสี่ยง" no-data key.

**Right panel cards** (top to bottom), all driven by `/detect` + `/timeseries` + `/satellite-image` for the selected site:
1. Alert card: uppercase label + status pill, large heading (e.g. "เฝ้าระวัง"), location subtitle, divider, "ความเชื่อมั่นของการพยากรณ์: ปานกลาง" (qualitative only, never a fabricated %), "กฎที่ถูกกระตุ้น: N/3", amber-tinted callout explaining why, footnote disclosing rule-based (non-ML) methodology.
2. Spectral metrics card: 2×2 grid — Chlorophyll-a (mg/m³), NDCI (20m, labeled "approx"), SST (°C), Anomaly z-score — IBM Plex Mono tabular numbers; footer with scene date + cloud %.
   - **SST has no backend field** (`DetectResponse`/`RiskMapProperties` carry no `sst`; MODIS SST was a locked-decisions intent, never implemented) — render its cell as `—`, with the same "ไม่มีข้อมูล" honesty treatment used elsewhere, never a fabricated number.
   - **NDCI** and **Anomaly z-score**: from `dt.data.index_values[dt.data.index_used]` and `dt.data.anomaly_z` (the Sentinel-2, per-scene detection reading) — same numbers SitePanel's "Detection verdict" block already shows.
   - **Chlorophyll-a (mg/m³)**: `/detect` has no chlor_a field (its index_values are NDCI/2BDA/3BDA/B2-B3 ratio, not raw chlorophyll). Use the latest point from the site's already-fetched `/timeseries` series (MODIS chlor_a) instead, and caption the card with *both* dates — the Sentinel-2 scene date (NDCI/z) and the MODIS point date (chlor_a) — since they are two different sensors/resolutions and may not be the same day; never imply one date covers all four numbers.
3. NDCI trend chart card (reuses `TimeSeriesChart`/`RegionTrendChart`): inline SVG dual-line — solid blue "ปี 2026" vs dashed gray "ค่าฐาน 20 ปี", month axis labels, footnote citing `/timeseries` + MODIS climatology as real sources.
4. Satellite image card (reuses `SatelliteImage`): True Color / NDCI Heatmap toggle, 150px image frame (rounded, bordered), caption with scene date, footnote on the sampling-buffer caveat (image ~500m context, index sampled from a narrower ~30m area).

Small footer disclaimer on pixel-resolution detection limits (reuses `Disclaimer.jsx` content, restyled).

## Screen 2 — Sentinel-2 NDCI

Title + subtitle. Grid of 4 index-definition cards (NDCI, 2BDA, 3BDA, B2−B3), each: formula (mono) + one-line description — static reference content.

Below: table card "ค่าอ่านล่าสุดต่อจุดตรวจวัด" — columns จุดตรวจวัด / ดัชนีที่ใช้ / NDCI / สถานะ, one row per real grid site (from `/risk-map` or `/detect` per site), dash + status label for no-data sites.

## Screen 3 — ความผิดปกติตามฤดูกาล (Seasonal Anomaly)

Title + subtitle citing MODIS climatology, 90-day window. 4 stat cards (จุดตรวจวัด, มีค่าอ่าน, เฝ้าระวัง, z-score สูงสุด), large mono numbers, computed from real per-site data.

Below: one row per site (reuses `AnomalyStrip.jsx`) — name + current z-score, 45-cell horizontal strip colored by risk level over time, diagonal-hatch cells where no reading exists. Axis footer: "90 วันก่อน / ล่าสุด".

Per-site 45-cell strip: bucket each site's last 90 days of `/timeseries` points into 45 equal-width 2-day windows; a cell's z is the mean of that window's non-null `anomaly_z` values, or null (hatched) if the window has none.

**Resolution of a gap in the original brief:** the old `SummaryPage.jsx` (being replaced) surfaced region-wide data with no home in the new 5-screen nav — `/summary`'s `most_recent_detected_signal` + `prediction_confidence_label`, and a per-site 90-day chlorophyll trend overlay (`RegionTrendChart.jsx`, all 6 sites on one chart). Nothing here should regress, so this screen also carries, below the 4 stat cards and above the per-site strips: a compact "ล่าสุดทั้งภูมิภาค" callout (most recent detected signal + prediction confidence, from `/summary`), and below the per-site strips, the existing multi-site trend chart (`RegionTrendChart`, reused as-is). This keeps every real data source the app currently surfaces reachable somewhere in the new nav.

## Screen 4 — พื้นที่เพาะเลี้ยงสัตว์น้ำ (Aquaculture Zones)

Title + subtitle. Amber-bordered disclosure banner: zone coordinates are not in the system — shown as nearest-grid-point proxies, not direct readings.

Grid of zone cards: name, status badge, nearest grid site, distance, "ความหนาแน่นเซลล์: ไม่มีข้อมูล" (never fabricated — no cell-density data source exists).

Below: full list of the 6 real grid sites with coordinates and status badges (from `/risk-map`).

Zone names/locations are illustrative placeholders (no real aquaculture-zone registry exists yet) — must be clearly labeled as such, consistent with the disclosure banner.

## Screen 5 — รายงานและการส่งออก (Reports & Exports)

Title + subtitle. List card of export actions (Weekly PDF, raw CSV, 14-event reference CSV, scheduler log JSON), each with a detail line and action button — presentational only, not wired, per current scope.

Two-column row:
- Service Status card: GEE, FastAPI, Scheduler, MODIS climatology — dot + status text (presentational; no live health-check endpoint exists).
- Scan History log: timestamped entries — presentational.

Bottom card: 14-event historical reference dataset callout, reading `n_events` / `n_matchable` / `n_with_real_satellite_reading` live from `/validation` — **do not hardcode "0/14 matched"**: as of this spec, 7 of 14 events already carry a real coordinate (`n_matchable`, recalibration landed 2026-08-22) but 0 of those 7 produced a usable satellite reading (`n_with_real_satellite_reading`), each for its own documented reason (see `calibration_caveat`). The card must read these three counts from the response every time, not restate a point-in-time number, since `n_matchable` is expected to keep changing as more events get coordinates. 3 summary stats: `n_events`, `n_matchable`, 6 plankton species (species count is a static fact about the dataset, not from the API).

Additionally — CLAUDE.md's Definition of Done requires the full 14-row per-event table and leave-one-out calibration table to remain published somewhere in the UI (not just 3 summary stats). Screen 5's bottom card holds the summary callout; immediately below it, this screen also carries the full events table and leave-one-out list, reusing the existing `ValidationPage.jsx` table/list markup verbatim (all 10 columns, LOO iterations), restyled to match the card system. This is additive to the screen list above, not a new screen.

## Interaction Scope

Live/functional: all 5 nav routes, map segmented control, image True Color/NDCI toggle, zoom buttons.
Presentational only (current scope): date-range pill, export action buttons, service-status card, scan-history log.

## Non-goals

- No backend/API changes.
- No new real data sources (aquaculture zone coordinates, cell-density counts, service health checks, scan history) — all such gaps are disclosed in-UI per CLAUDE.md's overclaim guard, never faked.
- No LINE/push alerting (already rejected in CLAUDE.md).
