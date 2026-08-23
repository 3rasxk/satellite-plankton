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

**Redesigned 2026-08 to an Apple-style light theme.** This section is the current source of truth (`frontend/src/styles/tokens.css` / `global.css` implement it); the previous dark ocean-colour direction (deep blues, Space Grotesk, hairline-only flat panels) is retired. The functional/honesty elements below are unchanged from before — this redesign is a restyle, not a rebuild: the disclaimer banner, the satellite-image buffer caveat, the "Live monitoring site" badge, `triggered_rules` plain-language display, the `AnomalyStrip` signature component, and every non-`ok` honest state (dashed/hatched "no reading" treatment) all carry over in content and behaviour, only their colours/type/surfaces changed.

### Colour — a light, neutral surface with data doing the talking

Rather than a domain-flavoured instrument-panel palette, the chrome is now a quiet white/light-grey Apple-style surface, and colour is spent only where it's meaningful: the single accent for interactivity, and the risk ramp for actual chlorophyll readings.

```css
--bg:             #FFFFFF;  /* page background */
--surface:        #F5F5F7;  /* cards, panels, chrome bands */
--surface-raised:  #FFFFFF; /* a card nested inside a --surface panel */
--border:         #D2D2D7;  /* thin borders */
--text:           #1D1D1F;  /* primary text */
--text-secondary: #6E6E73;  /* secondary text, labels */

--accent: #0071E3;          /* Apple blue — interactive elements ONLY:
                                links, active nav, buttons, focus ring,
                                the single-series chart trace. Never used
                                for a risk reading. */

/* risk ramp — chlorophyll concentration tiers, same tier→hue assignment
   as the old dark theme (normal/elevated/watch/warning), new hues */
--risk-normal:   #8E8E93;   /* neutral grey — near seasonal baseline */
--risk-elevated: #34C759;   /* Apple systemGreen — one signal triggered */
--risk-watch:    #FF9F0A;   /* Apple systemOrange — multiple signals, rising */
--risk-warning:  #FF3B30;   /* Apple systemRed — strong multi-signal anomaly */

--no-data:      #E5E5EA;    /* neutral, OUTSIDE both the risk ramp and the
--no-data-line: #AEAEB2;       accent — a cloud-cover/no-baseline/stale/
                                error state must never borrow either */
```

`--risk-normal` is deliberately a neutral grey rather than the accent blue or a green: blue is reserved for interactive elements only (a "normal" map marker must never look like a clickable control), and green would prematurely read as "good" for a tier that just means "no anomaly detected yet," which is a narrower claim. Grey reads as genuinely neutral — the Apple-native way to say "nothing to report."

**The rule from the old palette carries over unchanged:** the four risk tokens mean chlorophyll concentration and nothing else — never a button, an accent, or decorative chrome. Its mirror: `--accent` is the *only* colour used for interactive elements, so a risk reading and a clickable control are never visually confusable.

### Typography

| Role | Face | Use |
|------|------|-----|
| Body & display | **Inter** (400/500/600), SF Pro in the fallback stack | Everything — titles, labels, prose, UI text |
| Data | **IBM Plex Mono** (400/500) | Coordinates, index values, z-scores, dates — raw numeric/identifier readouts ONLY |

Space Grotesk is gone; there is one primary typeface (Inter, falling back to `-apple-system`/SF Pro so native Apple devices render actual San Francisco). The old design used mono for nearly all uppercase UI labels (nav, section titles, badges, pill text, buttons) as part of its "instrument panel" feel — that's now reduced: mono is scoped strictly to the raw numeric/identifier readouts the old §4 "Data" row already named (coordinates, index values, z-scores, dates, scene ids), never general UI text or labels. For example, in the site panel's detect grid, the `<dt>` labels ("Anomaly z-score") are now body text; only the `<dd>` values are mono.

Type scale is larger and roomier than before: 13 / 15 / 17 / 22 / 32 / 44px (was 12/14/16/20/28/40), body line-height 1.6. Labels/eyebrows are 12–13px, uppercase, `letter-spacing: 0.05–0.06em`, in body weight 500 — no longer mono.

### Cards

Every panel-like surface (state panels, stat cards, the risk legend, the site panel's detect block and chart wrap, the validation table's LOO list items) is a white or light-grey card: `border-radius: 12–16px` (`--radius-lg: 14px`), a subtle shadow `0 1px 3px rgba(0,0,0,0.08)` (`--shadow-card`), and a `1px solid var(--border)` hairline. This replaces the old flat hairline-only look entirely — no more `border-radius: 2px` sharp corners or glow-style coloured borders on hover states (interactive borders now use `--accent` directly, not a translucent glow). Small interactive chrome (buttons, nav pills, toggles) uses the tighter `--radius: 8px`.

### Signature element — the anomaly strip

`AnomalyStrip.jsx` is still the one memorable, signature component and its concept is unchanged: a horizontal ribbon of colour segments over ~90 days (site panel) or across monitored sites (summary page), using the risk ramp, compressing "is this unusual for this time of year?" into one glance. Only its surface/colours moved to the new tokens — a hairline border in `--border`, the no-data hatch now rendered in the light neutral (`--no-data`/`#D2D2D7` stripe) instead of the old dark hatch.

### Motion

Unchanged from before:
- Site panel slides in from the right, 200ms `ease-out`
- Map cells fade on data refresh, 150ms
- Nothing else. No scroll animations, no page transitions.

Respect `prefers-reduced-motion: reduce` — disable both.

### Basemap

Leaflet's tile layer is CartoDB Positron (`https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png`), replacing the old CartoDB Dark Matter tiles — a light, muted basemap so the light-theme risk markers stay legible, mirroring how the old dark basemap kept the dark-theme ramp legible.

### Quality floor

Responsive down to 375px (map goes full-bleed, panel becomes a bottom sheet). Visible keyboard focus on every interactive element (`outline: 2px solid var(--accent)`). Map cells reachable by keyboard, not mouse-only. All unchanged from before.

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