# Frontend Build Plan — Algal Bloom Early Warning Dashboard

Detailed plan for the Vite + React web app. Read alongside `.claude/agents/frontend-dashboard.md`.

---

## 1. Scope

Two pages, no authentication, no image upload (there is no underwater imagery in this project — detection is satellite-only).

| Page | Route | Job |
|------|-------|-----|
| Risk map | `/` | Show current bloom risk across the upper Gulf; click a cell → time-series panel |
| Summary | `/summary` | Region-wide status: at-risk site counts, trend, most recent detected signal |

**Out of scope:** user accounts, push notifications, image upload, mobile app, admin panel.

---

## 2. Setup

```bash
npm create vite@latest frontend -- --template react
cd frontend
npm install
```

Decide TypeScript vs JavaScript before running (`react-ts` vs `react`). Recommendation: plain `react` for competition timeline — fewer type-wrangling detours, and the API surface is small.

### Dependencies

```bash
npm install react-router-dom axios
npm install leaflet react-leaflet
npm install recharts
```

| Package | Why |
|---------|-----|
| `react-router-dom` | Two routes |
| `axios` | Backend calls |
| `leaflet` + `react-leaflet` | Map + GeoJSON risk overlay. Chosen over MapLibre: simpler API, no style-spec learning curve, and the overlay is a flat GeoJSON grid, not a 3D basemap |
| `recharts` | Time-series charts, React-native API |

Do **not** add a UI component library (MUI/Chakra/AntD). The app has ~8 distinct components; a library adds bundle weight and a generic look for no gain.

### Environment

`frontend/.env.example`:
```
VITE_API_BASE_URL=http://localhost:8000
```

Never hardcode the API URL. Read via `import.meta.env.VITE_API_BASE_URL`.

---

## 3. Structure

```
frontend/
├── .env.example
├── index.html
├── vite.config.js
└── src/
    ├── main.jsx              # router setup
    ├── App.jsx               # layout shell + persistent disclaimer
    ├── api/
    │   └── client.js         # axios instance + the 4 endpoint functions
    ├── pages/
    │   ├── RiskMapPage.jsx
    │   └── SummaryPage.jsx
    ├── components/
    │   ├── RiskMap.jsx       # Leaflet map + GeoJSON risk layer
    │   ├── RiskLegend.jsx    # colour ramp + threshold explanation
    │   ├── SitePanel.jsx     # slide-in panel on cell click
    │   ├── TimeSeriesChart.jsx
    │   ├── AnomalyStrip.jsx  # signature element (see §4)
    │   ├── StatCard.jsx
    │   └── Disclaimer.jsx    # truth-boundary banner
    ├── hooks/
    │   └── useApi.js         # loading/error/data fetch hook
    └── styles/
        ├── tokens.css        # design tokens (§4)
        └── global.css
```

### API client contract

`src/api/client.js` exposes exactly four functions matching the backend:

```js
getRiskMap()                    // GET /risk-map      → GeoJSON
getTimeseries(lat, lng)         // GET /timeseries    → array of readings
detect(lat, lng, date)          // GET /detect        → {detected, anomaly_z, index_values, index_used, disclaimer}
getSummary()                    // GET /summary       → region stats
```

Every response carries a `disclaimer` field — surface it, don't discard it.

---

## 4. Design direction

The subject is **ocean-colour remote sensing**. The design should look like it belongs to that world — satellite data products, chlorophyll ramps, instrument readouts — not like a generic SaaS dashboard.

### Colour — derived from the actual data, not decoration

The scientific ocean-colour ramp (deep blue → cyan → green → yellow → red) *is* the palette. It carries meaning: it's the same ramp used in published chlorophyll imagery, so a reader familiar with the domain reads the map instantly.

```css
--deep:      #0A1929;  /* deep water — page background */
--shelf:     #123A5A;  /* shallow shelf — panels, cards */
--clear:     #2E86AB;  /* low chlorophyll — safe */
--elevated:  #48C9A9;  /* elevated — watch */
--bloom:     #E8C547;  /* bloom likely — warning */
--severe:    #D64545;  /* severe bloom — alert */
--ink:       #E8F1F8;  /* primary text */
--ink-dim:   #7A9AB5;  /* secondary text, labels */
```

Risk levels map directly onto `--clear` / `--bloom` / `--severe` (three published levels), with `--elevated` available if a fourth tier is added later. **Never use these five ramp colours for anything non-data** — no accent buttons, no decorative fills. Colour means concentration here; spending it decoratively breaks the reading.

### Typography

| Role | Face | Use |
|------|------|-----|
| Display | **Space Grotesk** (600) | Page titles, stat numbers |
| Body | **Inter** (400/500) | Prose, labels, UI text |
| Data | **IBM Plex Mono** (400) | Coordinates, index values, dates, readouts |

The mono face for all numeric readouts is the deliberate choice: this is instrument data, and tabular figures line up in the time-series panel. Load via Google Fonts with `display=swap`, weights limited to those listed (don't pull whole families).

Type scale: 12 / 14 / 16 / 20 / 28 / 40px. Labels and eyebrows in 12px mono, uppercase, `letter-spacing: 0.08em`.

### Signature element — the anomaly strip

`AnomalyStrip.jsx` is the one memorable component. A horizontal ribbon showing the chlorophyll anomaly over the last ~90 days as a continuous colour band, using the same ramp as the map — echoing how satellite swath data is actually presented. It sits above the time-series chart in the site panel and again at the top of the summary page.

Why it earns its place: it compresses "is this unusual for this time of year?" into a single glance, which is the actual question the system answers. A line chart alone can't do that without the reader mentally holding the baseline.

Keep everything around it quiet: flat panels, hairline borders (`1px solid rgba(122,154,181,0.2)`), no shadows, no gradients, `border-radius: 2px`.

### Motion

Minimal and functional only:
- Site panel slides in from the right, 200ms `ease-out`
- Map cells fade on data refresh, 150ms
- Nothing else. No scroll animations, no page transitions.

Respect `prefers-reduced-motion: reduce` — disable both.

### Quality floor

Responsive down to 375px (map goes full-bleed, panel becomes a bottom sheet). Visible keyboard focus on every interactive element (`outline: 2px solid var(--elevated)`). Map cells reachable by keyboard, not mouse-only.

---

## 5. Page specs

### Risk map page (`/`)

```
┌────────────────────────────────────────────────┐
│  ALGAL BLOOM WATCH · UPPER GULF OF THAILAND    │
│  Updated 2026-08-17 · Sentinel-2 + MODIS       │
├────────────────────────────────────────────────┤
│                                    ┌──────────┐│
│                                    │ SITE     ││
│         [ Leaflet map with         │ 12.92°N  ││
│           GeoJSON risk grid ]      │ 100.78°E ││
│                                    │          ││
│                                    │ [strip]  ││
│                                    │ [chart]  ││
│  ┌─────────────┐                   │          ││
│  │ RISK LEGEND │                   └──────────┘│
│  └─────────────┘                               │
├────────────────────────────────────────────────┤
│ Detection is satellite-pixel resolution...     │
└────────────────────────────────────────────────┘
```

- Map centred on the upper Gulf, zoom fitted to the bounding box from the backend
- Risk grid as a GeoJSON layer, cells filled by `risk_level`, 60% opacity so the basemap reads through
- Basemap: a muted/dark tile set so the ramp stays legible. CartoDB Dark Matter or similar
- Legend fixed bottom-left, showing the three levels *with what they mean*, not just colour swatches
- Click a cell → `SitePanel` opens, fetches `/timeseries` for that coordinate
- Panel shows: coordinates (mono), current index value, `AnomalyStrip`, `TimeSeriesChart`, and the detection verdict from `/detect` (`detected` + `index_used`, no fabricated confidence — see `backend-api.md`)

### Summary page (`/summary`)

- Row of `StatCard`s: sites at each risk level, most recent detected bloom signal (date + location), data freshness
- Full-width `AnomalyStrip` for the region
- Region trend chart
- Every number in mono, every label in 12px uppercase

---

## 6. Copy rules

Interface words are design material. Write from the reader's side:

- "Bloom likely" not "Positive classification"
- "No recent signal" not "Null result"
- "Updated 4 hours ago" not "Last sync: 2026-08-17T04:00:00Z"
- Empty state: "No readings for this location yet — cloud cover blocks satellite passes during monsoon months." Explains *why*, and it's true.
- Error state: "Couldn't reach the data service. Retry." Not an apology, not vague.

The disclaimer banner, verbatim across the app:

> Detection is at satellite-pixel resolution. Small or scattered blooms may not be visible. Presence and absence are the reliable signal — concentration estimates are approximate.

---

## 7. Build phases

Each phase ends in something runnable.

**Phase A — shell**
Scaffold, router, two empty routes, layout, tokens.css, fonts, disclaimer banner. Runs, looks intentional, no data.

**Phase B — API layer**
`client.js` with all four functions, `useApi` hook handling loading/error/empty. Render raw JSON on the page to prove the contract works before styling anything.

**Phase C — map**
Leaflet mounted, basemap, GeoJSON risk layer from `/risk-map`, legend. Cells coloured, clickable, no panel yet.

**Phase D — site panel**
Panel opens on cell click, fetches time-series, renders `TimeSeriesChart` + `AnomalyStrip` + `/detect` verdict.

**Phase E — summary page**
Stat cards, region strip, trend chart.

**Phase F — polish pass**
Responsive down to 375px, keyboard focus, reduced-motion, empty and error states for every fetch, remove one thing that isn't earning its place.

---

## 8. Traps to avoid

- **Mock data left in.** Fine during Phase B, must be gone by Phase C. Never present mock as real.
- **Fake precision.** If the backend returns a confidence of 0.73, don't render "73.0%". One decimal implies precision the model doesn't have.
- **Conflating the two claims.** Presence/absence and concentration must never be styled identically — concentration readouts should carry a visible "approximate" marker.
- **Decorative use of ramp colours.** Covered in §4, worth repeating: those five colours mean chlorophyll concentration and nothing else.
- **Leaflet CSS forgotten.** `import 'leaflet/dist/leaflet.css'` — omitting it produces a broken-looking map with misaligned tiles, and it's the single most common Leaflet setup mistake.
- **Rebuilding on every render.** Memoise the GeoJSON layer; re-parsing a large grid on each state change will stutter.