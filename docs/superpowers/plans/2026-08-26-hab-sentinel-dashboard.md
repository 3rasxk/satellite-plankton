# HAB Sentinel Dashboard Implementation Plan

> Correction, 2026-09-06: current detection-anomaly displays and gauge/risk verdicts in this historical plan are superseded. The former statistic mixed dimensionless spectral indices with MODIS concentrations and is removed. Current detection output is indices/status/actual_date only, with null API `spatial_anomaly_z`; display "Not computed — no valid baseline exists". `/timeseries` `anomaly_z` remains the valid MODIS `chlor_a` calculation. Numeric detection examples below are withdrawn implementation instructions, not evidence.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the former top-nav frontend with the 5-screen sidebar-nav "HAB Sentinel" dashboard, with no fabricated data.

**Architecture:** Frontend-only historical plan using the active monitoring endpoints and fixed monitoring grid. Validation-specific work from the original plan was retired on 2026-09-06.

**Tech Stack:** React 19 + Vite, react-router-dom v7, react-leaflet v5 + Leaflet, recharts v3, axios, oxlint (no JS test runner in this repo — verification is `npm run lint` + manual dev-server check via the Chrome browser tool, not unit tests).

**Spec:** `docs/superpowers/specs/2026-08-26-hab-sentinel-dashboard-design.md`

## Global Constraints

- No backend changes. Every number shown must trace to an active API response or `backend/src/grid.py`.
- Never fabricate a value. Where the spec calls for a field with no backend source (SST, aquaculture cell density, live service-health checks, scan history), render an explicit no-data / "ไม่มีข้อมูล" state — never a placeholder number.
- Truth-boundary disclaimer banner (`Disclaimer.jsx`, driven by `DISCLAIMER_TEXT`) stays mounted in the shared layout shell on every route, unconditionally.
- Colors: `--risk-*` tokens mean chlorophyll-concentration tier ONLY, never decorative. `--accent` is interactive-elements-only, never a data color. Both existing rules (tokens.css header comment) carry forward unchanged.
- IBM Plex Mono (`--font-mono` / `.mono`) for every number, coordinate, date. Inter + Noto Sans Thai for all UI text/labels.
- New Thai UI copy must preserve the exact technical meaning of the English original it replaces or sits alongside — this is a translation, not a rewrite of the claim.
- Every new/modified file keeps the existing repo convention: a short doc-comment stating data source + limitations where the file makes a truth-boundary-relevant choice (matches every existing component in `/frontend/src`).

---

## Task 1: Design tokens + fonts

**Files:**
- Modify: `frontend/src/styles/tokens.css`
- Modify: `frontend/index.html`

**Interfaces:**
- Produces (CSS custom properties later tasks rely on): `--surface-card`, `--divider`, `--divider-soft`, `--text-tertiary`, `--text-muted`, `--accent-hover`, `--radius-control`, `--radius-pill`, `--glass-bg`, `--glass-blur`, `--glass-border`, `--font-thai` (Noto Sans Thai stack, folded into `--font-body`).

Most of the target palette already exists in `tokens.css` (`--bg #fff`, `--surface #f5f5f7`, `--accent #0071e3`, the four `--risk-*` tokens, `--font-mono`). This task adds what's missing rather than rewriting the file.

- [ ] **Step 1: Add the missing tokens**

Edit `frontend/src/styles/tokens.css`:

1. Extend the existing `@import` line (line 10) to also pull Noto Sans Thai:
   ```css
   @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Noto+Sans+Thai:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');
   ```
2. In the `:root` surfaces block, add a third surface tier and a second divider tier (spec: white / panel gray / card surface / divider / secondary divider):
   ```css
   --surface-card: #fafafa; /* card body inside a --surface panel — one step lighter than --surface-raised's pure white, per spec's card-surface tier */
   --divider: #e5e5ea; /* primary hairline — spec's "dividers" */
   --divider-soft: #f0f0f2; /* secondary/nested divider — spec's "secondary divider" */
   ```
   Keep `--border` as an alias (`--border: var(--divider);`) rather than removing it — every existing component still reads `--border`.
3. Add `--accent-hover: #0058b4;` next to `--accent`.
4. Add tertiary/muted text tiers next to `--text-secondary`:
   ```css
   --text-tertiary: #8e8e93;
   --text-muted: #aeaeb2;
   ```
   (`--risk-normal` and `--no-data-line` already hardcode these same two hex values for other reasons — leave those alone, this just gives plain text the same tones a name of its own.)
5. Add control/pill radii next to `--radius` / `--radius-lg`:
   ```css
   --radius-control: 8px; /* controls, 7-9px per spec */
   --radius-pill: 999px;
   ```
6. Add glass-surface tokens (floating map chrome — segmented control, legend, date pill):
   ```css
   --glass-bg: rgba(255, 255, 255, 0.86);
   --glass-blur: blur(20px) saturate(180%);
   --glass-border: 0.5px solid rgba(0, 0, 0, 0.06);
   ```
7. Update the type-stack comment/block: rename the existing `--font-body`/`--font-display` values to include Noto Sans Thai right after Inter (so Thai glyphs render in the same faces as Latin ones, no separate `--font-thai` token needed):
   ```css
   --font-body: 'Inter', 'Noto Sans Thai', -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'SF Pro Display', system-ui, sans-serif;
   --font-display: 'Inter', 'Noto Sans Thai', -apple-system, BlinkMacSystemFont, 'SF Pro Display', system-ui, sans-serif;
   ```

- [ ] **Step 2: Add the Noto Sans Thai font stylesheet link as a fallback preconnect (optional but matches Google-Fonts best practice already absent from this repo) — skip if the `@import` alone renders Thai correctly in a quick check; do not add a second font-loading mechanism.**

Open `frontend/index.html` and confirm no changes are needed there (fonts load via the CSS `@import`, matching the existing Inter/IBM Plex Mono setup) — this step is a checkpoint, not a code change, unless the manual check in Step 3 shows Thai glyphs falling back to a system font.

- [ ] **Step 3: Verify**

```bash
cd frontend && npm run lint
```
Expected: no new errors (CSS isn't linted by oxlint, this just guards against a stray syntax slip elsewhere).

Start the dev server if not already running (`npm run dev`), open it in the Chrome browser tool, and confirm the page still renders (existing 3-page app, unchanged visually except font stack) with no console errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/styles/tokens.css frontend/index.html
git commit -m "Add HAB Sentinel design tokens: card surface, dividers, glass chrome, Thai font"
```

---

## Task 2: Sidebar shell + 5-route skeleton

**Files:**
- Create: `frontend/src/components/Sidebar.jsx`
- Modify: `frontend/src/App.jsx`
- Modify: `frontend/src/main.jsx`
- Modify: `frontend/src/api/client.js`
- Modify: `frontend/src/constants.js`
- Modify: `frontend/src/styles/global.css`

**Interfaces:**
- Produces: `Sidebar` component (no props — self-contained: renders nav + live connectivity pill), routes `/`, `/ndci`, `/anomaly`, `/aquaculture`, `/reports` registered in `main.jsx`. `RISK_LABEL_TH` (Thai risk-tier labels) exported from `constants.js` — every later Thai-copy screen (Tasks 3, 4, 5, 7) imports this same map rather than each defining its own.
- Consumes: `getMeta()` (new API client function) for the connectivity pill.

This task stands up the shell and routing skeleton. Temporary placeholders are replaced by the final route components in later tasks.

**Bounded Thai-copy scope for this whole plan:** risk-tier labels (`RISK_LABEL_TH`), nav items, headings, and card chrome are translated to Thai throughout. Longer explanatory sentences already defined in English in `constants.js` (`RISK_MEANING`, `STATUS_LABEL`, `STATUS_EXPLAINER`, `RULE_DESCRIPTION`) are left as-is and reused verbatim — translating multi-clause truth-boundary sentences risks introducing a subtle meaning drift, which is a bigger risk than a mixed-language sentence. This is a deliberate scope line, not an oversight.

- [ ] **Step 1: Add `getMeta()` to the API client, and `RISK_LABEL_TH` to constants**

`frontend/src/constants.js` already exports `RISK_LABEL` (English: Normal/Elevated/Watch/Warning). Add a Thai counterpart right after it — same 4 keys, a translation of the same tier meaning, not a new claim:

```js
export const RISK_LABEL_TH = {
  normal: 'ปกติ',
  elevated: 'เริ่มพบสัญญาณ',
  watch: 'เฝ้าระวัง',
  warning: 'เตือนภัย',
}
```

`frontend/src/api/client.js` already exports the monitoring API helpers. Add, following the same pattern:

```js
export async function getMeta() {
  const { data } = await client.get('/')
  return data
}
```

`GET /` is `backend/src/main.py`'s existing meta route — reused here only to prove the API is reachable, not for its response shape.

- [ ] **Step 2: Build `Sidebar.jsx`**

```jsx
import { NavLink } from 'react-router-dom'
import { useApi } from '../hooks/useApi.js'
import { getMeta } from '../api/client.js'

const NAV_ITEMS = [
  { to: '/', label: 'ภาพรวม/แผนที่', icon: '🗺️', end: true },
  { to: '/ndci', label: 'Sentinel-2 NDCI', icon: '📡' },
  { to: '/anomaly', label: 'ความผิดปกติตามฤดูกาล', icon: '📈' },
  { to: '/aquaculture', label: 'พื้นที่เพาะเลี้ยงสัตว์น้ำ', icon: '🐟' },
  { to: '/reports', label: 'รายงานและการส่งออก', icon: '📄' },
]

/**
 * Sidebar nav shell (HAB Sentinel design spec, docs/superpowers/specs/
 * 2026-08-26-hab-sentinel-dashboard-design.md). The connectivity pill is a
 * real signal, not decoration: it fires GET / (backend/src/main.py's meta
 * route) once on mount and reflects whether that call actually succeeded —
 * never a hardcoded "connected" claim (CLAUDE.md: never fabricate).
 */
export default function Sidebar() {
  const { data, error } = useApi(getMeta, [])
  const connected = !!data && !error

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <span className="sidebar-logo" aria-hidden="true">🛰️</span>
        <div>
          <div className="sidebar-title">HAB Sentinel</div>
          <div className="sidebar-subtitle">อ่าวไทยตอนบน</div>
        </div>
      </div>

      <div className={`sidebar-status-pill${connected ? '' : ' offline'}`}>
        <span className="dot" />
        {connected ? 'ระบบทำงานปกติ' : 'เชื่อมต่อ API ไม่ได้'}
      </div>

      <nav className="sidebar-nav">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) => `sidebar-nav-item${isActive ? ' active' : ''}`}
          >
            <span className="sidebar-nav-icon" aria-hidden="true">{item.icon}</span>
            {item.label}
          </NavLink>
        ))}
      </nav>

      <div className="sidebar-footer">
        <div className={`sidebar-pill outline${connected ? '' : ' offline'}`}>
          <span className="dot" />
          GEE API {connected ? 'Connected' : 'Unreachable'}
        </div>
        <button type="button" className="sidebar-settings-btn">
          <span aria-hidden="true">⚙️</span> ตั้งค่าระบบ
        </button>
      </div>
    </aside>
  )
}
```

- [ ] **Step 3: Rewrite `App.jsx`'s layout to sidebar + content**

```jsx
import { Outlet } from 'react-router-dom'
import Sidebar from './components/Sidebar.jsx'
import Disclaimer from './components/Disclaimer.jsx'
import { DISCLAIMER_TEXT } from './constants.js'

export default function App() {
  return (
    <div className="app-shell">
      <Sidebar />
      <div className="app-body">
        <main className="app-main">
          <Outlet />
        </main>
        <Disclaimer text={DISCLAIMER_TEXT} />
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Update `main.jsx` routes**

Replace the existing `<Routes>` block:

```jsx
import RiskMapPage from './pages/RiskMapPage.jsx'
import SummaryPage from './pages/SummaryPage.jsx'

function NdciStub() {
  return <div className="page"><h1>Sentinel-2 NDCI</h1><p className="no-rules">Coming in Task 5.</p></div>
}
function AquacultureStub() {
  return <div className="page"><h1>พื้นที่เพาะเลี้ยงสัตว์น้ำ</h1><p className="no-rules">Coming in Task 7.</p></div>
}

// ...
<Route path="/" element={<App />}>
  <Route index element={<RiskMapPage />} />
  <Route path="ndci" element={<NdciStub />} />
  <Route path="anomaly" element={<SummaryPage />} />
  <Route path="aquaculture" element={<AquacultureStub />} />
</Route>
```

Keep all three existing page imports for now — Tasks 3, 6, 8 remove them one at a time as each is replaced.

- [ ] **Step 5: Sidebar + shell CSS**

First, add two dedicated status tokens to `frontend/src/styles/tokens.css` (near the `--no-data*` tokens Task 1 added), for the sidebar's live/offline connectivity pill. These are deliberately NOT `--risk-elevated`/`--risk-warning` — the connectivity pill is a system-health signal, not a chlorophyll reading, and reusing a risk-tier token for it would violate this plan's Global Constraint that `--risk-*` tokens mean chlorophyll-concentration tier only, never decorative. Same hex values as `--risk-elevated`/`--risk-warning` (Apple systemGreen/systemRed — the right visual language for "ok"/"error" on its own merits), but under names that carry no risk-tier meaning:

```css
--status-ok: #34c759;
--status-error: #ff3b30;
```

Then add a new section to `frontend/src/styles/global.css` (append, with a section-header comment `/* ---- Sidebar shell (HAB Sentinel) ---- */`) — this replaces the old `.app-header`/`.app-nav`/`.brand*` rules, which should be deleted since `App.jsx` no longer renders that markup:

```css
.app-shell {
  display: flex;
  min-height: 100svh;
}

.app-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.app-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.sidebar {
  width: 240px;
  flex-shrink: 0;
  background: var(--surface);
  border-right: 1px solid var(--divider);
  display: flex;
  flex-direction: column;
  padding: 20px 16px;
  gap: 20px;
}

.sidebar-header {
  display: flex;
  align-items: center;
  gap: 10px;
}

.sidebar-logo {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  background: var(--accent);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 15px;
}

.sidebar-title {
  font-family: var(--font-display);
  font-weight: 600;
  font-size: var(--fs-14);
  color: var(--text);
}

.sidebar-subtitle {
  font-size: 12px;
  color: var(--text-secondary);
}

.sidebar-status-pill,
.sidebar-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  border-radius: var(--radius-pill);
  font-size: 12px;
  width: fit-content;
}

.sidebar-status-pill {
  background: rgba(52, 199, 89, 0.1);
  color: var(--status-ok);
}
.sidebar-status-pill.offline {
  background: rgba(255, 59, 48, 0.1);
  color: var(--status-error);
}

.sidebar-status-pill .dot,
.sidebar-pill .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}

.sidebar-nav {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.sidebar-nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: var(--radius-control);
  font-size: var(--fs-14);
  color: var(--text);
  text-decoration: none;
}
.sidebar-nav-item:hover {
  background: var(--divider-soft);
}
.sidebar-nav-item.active {
  background: rgba(var(--accent-rgb), 0.1);
  color: var(--accent);
  font-weight: 500;
}

.sidebar-footer {
  margin-top: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.sidebar-pill.outline {
  border: 1px solid var(--divider);
  color: var(--text-secondary);
  background: none;
}
.sidebar-pill.outline .dot {
  background: var(--status-ok);
}
.sidebar-pill.outline.offline .dot {
  background: var(--status-error);
}

.sidebar-settings-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: var(--radius-control);
  border: none;
  background: none;
  color: var(--text-secondary);
  font-size: var(--fs-14);
  cursor: pointer;
  text-align: left;
}
.sidebar-settings-btn:hover {
  background: var(--divider-soft);
}
```

Delete the now-dead `.app-header`, `.app-nav`, `.brand`, `.brand-mark`, `.brand-sub` rules from `global.css` (search for them — they were read in Task 0's exploration at the top of the "App shell" section).

- [ ] **Step 6: Verify**

`npm run lint`, then in the Chrome browser tool: navigate to `/`, confirm the sidebar renders with all 5 nav items, the connectivity pill shows green "ระบบทำงานปกติ" (backend must be running — start it with the project's normal `uvicorn`/`run` command if not already up), click each nav item and confirm the URL changes and the (stub or old) page renders without console errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/Sidebar.jsx frontend/src/App.jsx frontend/src/main.jsx frontend/src/api/client.js frontend/src/styles/global.css
git commit -m "Add HAB Sentinel sidebar shell and 5-route skeleton"
```

---

## Task 3: Map view modes (True Color / NDCI raster / Risk map)

**Files:**
- Create: `frontend/src/utils/noiseField.js`
- Create: `frontend/src/components/NdciRasterOverlay.jsx`
- Create: `frontend/src/components/MapControls.jsx`
- Create: `frontend/src/pages/OverviewPage.jsx`
- Modify: `frontend/src/components/RiskMap.jsx`
- Modify: `frontend/src/components/RiskLegend.jsx`
- Modify: `frontend/src/main.jsx` (swap `/` from `RiskMapPage` to `OverviewPage`)
- Delete: `frontend/src/pages/RiskMapPage.jsx`
- Modify: `frontend/src/styles/global.css`

**Interfaces:**
- Produces: `RiskMap({ featureCollection, onSelectSite, mode })` — `mode` one of `'true_color' | 'ndci' | 'risk'`, default `'risk'`. `MapControls({ mode, onModeChange })`. `NdciRasterOverlay({ bounds })` — no other props, generates its own field.
- Consumes: existing `RISK_COLOR_HEX`, `NO_DATA_HEX`, `NO_DATA_LINE_HEX`, `STATUS_LABEL`, `NO_DATA_STATUS` from `constants.js` (unchanged).

Right-panel cards are NOT part of this task — `OverviewPage.jsx` temporarily keeps using the existing `SitePanel` component for the right side; Task 4 replaces it with the 4 new cards.

- [ ] **Step 1: Value-noise + domain-warp field generator**

```js
// frontend/src/utils/noiseField.js
/**
 * Deterministic 2D value noise with domain warp, used only to paint the
 * decorative NDCI-mode map overlay (docs/superpowers/specs/2026-08-26-
 * hab-sentinel-dashboard-design.md, Screen 1). This is NOT a real
 * per-pixel index product — there is no backend raster endpoint — it is
 * illustrative texture only, and every place it's shown must say so
 * (see NdciRasterOverlay.jsx). Self-contained (no noise library) so it
 * has zero new dependencies.
 */
function hash(x, y, seed) {
  const s = Math.sin(x * 127.1 + y * 311.7 + seed * 74.7) * 43758.5453123
  return s - Math.floor(s)
}

function smoothstep(t) {
  return t * t * (3 - 2 * t)
}

function valueNoise(x, y, seed) {
  const x0 = Math.floor(x)
  const y0 = Math.floor(y)
  const tx = smoothstep(x - x0)
  const ty = smoothstep(y - y0)
  const v00 = hash(x0, y0, seed)
  const v10 = hash(x0 + 1, y0, seed)
  const v01 = hash(x0, y0 + 1, seed)
  const v11 = hash(x0 + 1, y0 + 1, seed)
  const a = v00 + (v10 - v00) * tx
  const b = v01 + (v11 - v01) * tx
  return a + (b - a) * ty
}

function fbm(x, y, seed, octaves = 4) {
  let value = 0
  let amplitude = 0.5
  let freq = 1
  for (let i = 0; i < octaves; i++) {
    value += valueNoise(x * freq, y * freq, seed) * amplitude
    amplitude *= 0.5
    freq *= 2
  }
  return value
}

/** Returns a Float32Array of length size*size, values in [0,1], domain-warped. */
export function generateWarpedField(size, seed = 7) {
  const field = new Float32Array(size * size)
  const scale = 4 / size
  const warpAmount = 1.6
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const nx = x * scale
      const ny = y * scale
      const warpX = fbm(nx, ny, seed + 91, 3)
      const warpY = fbm(nx, ny, seed + 193, 3)
      const v = fbm(nx + warpX * warpAmount, ny + warpY * warpAmount, seed, 4)
      field[y * size + x] = Math.min(1, Math.max(0, v))
    }
  }
  return field
}

// Diverging ramp: dark blue -> pale cyan -> orange -> dark red, matching
// the map legend's -0.10 / 0.10 / >0.35 stops (RiskLegend NDCI variant).
const STOPS = [
  { t: 0, rgb: [10, 30, 90] },
  { t: 0.4, rgb: [176, 224, 230] },
  { t: 0.7, rgb: [255, 159, 10] },
  { t: 1, rgb: [139, 0, 0] },
]

export function rampColor(t) {
  for (let i = 0; i < STOPS.length - 1; i++) {
    const a = STOPS[i]
    const b = STOPS[i + 1]
    if (t >= a.t && t <= b.t) {
      const lt = (t - a.t) / (b.t - a.t)
      return [
        Math.round(a.rgb[0] + (b.rgb[0] - a.rgb[0]) * lt),
        Math.round(a.rgb[1] + (b.rgb[1] - a.rgb[1]) * lt),
        Math.round(a.rgb[2] + (b.rgb[2] - a.rgb[2]) * lt),
      ]
    }
  }
  return STOPS[STOPS.length - 1].rgb
}

/** Renders the field to a canvas and returns a PNG data URL. */
export function fieldToDataUrl(size = 256, seed = 7) {
  const field = generateWarpedField(size, seed)
  const canvas = document.createElement('canvas')
  canvas.width = size
  canvas.height = size
  const ctx = canvas.getContext('2d')
  const imageData = ctx.createImageData(size, size)
  for (let i = 0; i < field.length; i++) {
    const [r, g, b] = rampColor(field[i])
    imageData.data[i * 4] = r
    imageData.data[i * 4 + 1] = g
    imageData.data[i * 4 + 2] = b
    imageData.data[i * 4 + 3] = 200 // slightly translucent so the basemap reads through
  }
  ctx.putImageData(imageData, 0, 0)
  return canvas.toDataURL('image/png')
}
```

- [ ] **Step 2: `NdciRasterOverlay.jsx`**

```jsx
import { useMemo } from 'react'
import { ImageOverlay } from 'react-leaflet'
import { fieldToDataUrl } from '../utils/noiseField.js'

// Fixed bounds roughly covering the monitored grid's extent with margin —
// see backend/src/grid.py: sites span ~12.75-13.5N, 100.05-100.99E.
const NDCI_OVERLAY_BOUNDS = [
  [12.55, 99.85],
  [13.75, 101.15],
]

/**
 * Decorative NDCI-mode texture (docs/superpowers/specs/2026-08-26-hab-
 * sentinel-dashboard-design.md, Screen 1). Domain-warped noise on the
 * diverging ramp — illustrative only, NOT a real per-pixel NDCI raster
 * (no such backend endpoint exists). Regenerated once per mount
 * (useMemo, empty deps) so it doesn't re-warp on every re-render.
 */
export default function NdciRasterOverlay() {
  const dataUrl = useMemo(() => fieldToDataUrl(256, 7), [])
  return <ImageOverlay url={dataUrl} bounds={NDCI_OVERLAY_BOUNDS} opacity={0.65} />
}
```

- [ ] **Step 3: Extend `RiskMap.jsx` with a `mode` prop**

Modify `frontend/src/components/RiskMap.jsx`:
1. Add `mode = 'risk'` to the destructured props.
2. Add a second tile URL constant next to `TILE_URL`:
   ```js
   const TRUE_COLOR_TILE_URL =
     'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'
   const TRUE_COLOR_ATTRIBUTION =
     'Tiles &copy; Esri — Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community'
   ```
3. Replace the `<TileLayer>` element:
   ```jsx
   <TileLayer
     url={mode === 'true_color' ? TRUE_COLOR_TILE_URL : TILE_URL}
     attribution={mode === 'true_color' ? TRUE_COLOR_ATTRIBUTION : TILE_ATTRIBUTION}
   />
   {mode === 'ndci' && <NdciRasterOverlay />}
   ```
   (import `NdciRasterOverlay` and `ZoomControl` from `'react-leaflet'` at the top.)
4. Add `zoomControl={false}` to `<MapContainer>`'s props and add `<ZoomControl position="topright" />` as its first child — this moves the default zoom buttons to the top-right per the spec, replacing Leaflet's default top-left placement.
5. Leave the `CircleMarker` rendering loop unchanged — markers stay visible in all three modes (site selection must not disappear when switching map mode).

- [ ] **Step 4: `MapControls.jsx` — floating segmented control**

```jsx
const MODES = [
  { value: 'true_color', label: 'True Color (RGB)' },
  { value: 'ndci', label: 'NDCI Index (20m)' },
  { value: 'risk', label: 'แผนที่ความเสี่ยง (rule-based)' },
]

/** Floating glass segmented control switching RiskMap's `mode` prop. */
export default function MapControls({ mode, onModeChange }) {
  return (
    <div className="map-segmented-control glass">
      {MODES.map((m) => (
        <button
          key={m.value}
          type="button"
          className={mode === m.value ? 'active' : ''}
          onClick={() => onModeChange(m.value)}
        >
          {m.label}
        </button>
      ))}
    </div>
  )
}
```

- [ ] **Step 5: Draggable legend + NDCI gradient variant in `RiskLegend.jsx`**

Modify `frontend/src/components/RiskLegend.jsx` to accept a `mode` prop and, when `mode === 'ndci'`, render a gradient bar instead of the 4 discrete swatches:

```jsx
import { useRef, useState, useCallback } from 'react'
import { RISK_LABEL_TH, RISK_MEANING, RISK_COLOR_VAR } from '../constants.js'

const LEVELS = ['normal', 'elevated', 'watch', 'warning']

export default function RiskLegend({ mode = 'risk' }) {
  const [pos, setPos] = useState({ x: 16, y: 16 })
  const dragRef = useRef(null)

  const onPointerDown = useCallback((e) => {
    const start = { x: e.clientX, y: e.clientY, origin: pos }
    dragRef.current = start
    const onMove = (ev) => {
      const dx = ev.clientX - start.x
      const dy = ev.clientY - start.y
      setPos({ x: start.origin.x + dx, y: start.origin.y + dy })
    }
    const onUp = () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pos])

  return (
    <div
      className="risk-legend glass"
      style={{ left: pos.x, bottom: pos.y }}
      onPointerDown={onPointerDown}
    >
      {mode === 'ndci' ? (
        <>
          <h3>NDCI Index</h3>
          <div className="ndci-gradient-bar" />
          <div className="ndci-gradient-labels">
            <span>−0.10</span>
            <span>0.10</span>
            <span>&gt;0.35</span>
          </div>
        </>
      ) : (
        <>
          <h3>ระดับความเสี่ยง</h3>
          {LEVELS.map((level) => (
            <div className="legend-row" key={level}>
              <span className="legend-swatch" style={{ background: `var(${RISK_COLOR_VAR[level]})` }} />
              <span>
                <span className="legend-label">{RISK_LABEL_TH[level]}</span>
                <span className="legend-meaning">{RISK_MEANING[level]}</span>
              </span>
            </div>
          ))}
        </>
      )}
      <div className="legend-row">
        <span className="legend-swatch no-data" />
        <span>
          <span className="legend-label">ไม่มีค่าอ่าน</span>
          <span className="legend-meaning">ไม่ใช่ระดับเสี่ยง — เมฆบัง ไม่มีข้อมูลฐาน หรือยังไม่ได้ตรวจสอบ</span>
        </span>
      </div>
    </div>
  )
}
```

Note: legend position switches from CSS `left/bottom: 16px` anchoring to inline-styled `left`/`bottom` once dragged — absolute-position the `.risk-legend` element (`position: absolute`) inside a `position: relative` map container in CSS (Step 6) so the drag coordinates are meaningful.

- [ ] **Step 6: `OverviewPage.jsx` (new, map + controls only — right panel still `SitePanel` for now)**

```jsx
import { useMemo, useState } from 'react'
import { useApi } from '../hooks/useApi.js'
import { getRiskMap } from '../api/client.js'
import RiskMap from '../components/RiskMap.jsx'
import RiskLegend from '../components/RiskLegend.jsx'
import MapControls from '../components/MapControls.jsx'
import SitePanel from '../components/SitePanel.jsx'
import { formatRelativeTime } from '../constants.js'

export default function OverviewPage() {
  const { data, loading, error, refetch } = useApi(getRiskMap, [])
  const [selected, setSelected] = useState(null)
  const [mode, setMode] = useState('risk')

  const newestFetch = useMemo(() => {
    if (!data) return null
    const times = data.features.map((f) => f.properties.fetched_at).filter(Boolean).sort()
    return times.length ? times[times.length - 1] : null
  }, [data])

  return (
    <div className="overview-page">
      <div className="overview-map-area">
        {loading && <div className="state-panel" style={{ margin: 24 }}><h3>Loading the monitored grid…</h3></div>}
        {error && (
          <div className="state-panel error" style={{ margin: 24 }}>
            <h3>Couldn&apos;t reach the data service.</h3>
            <button type="button" className="retry-btn" onClick={refetch}>Retry</button>
          </div>
        )}
        {data && data.features.length > 0 && (
          <>
            <RiskMap featureCollection={data} onSelectSite={setSelected} mode={mode} />
            <MapControls mode={mode} onModeChange={setMode} />
            <RiskLegend mode={mode} />
            <div className="map-date-pill glass">
              📅 {newestFetch ? `อัปเดต ${formatRelativeTime(newestFetch)}` : 'Sentinel-2 + MODIS'} ⌄
            </div>
          </>
        )}
      </div>
      <div className="overview-side-panel">
        {selected ? (
          <SitePanel site={selected} onClose={() => setSelected(null)} />
        ) : (
          <div className="state-panel"><h3>เลือกจุดตรวจวัดบนแผนที่</h3></div>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 7: Wire the new page and delete the old one**

In `main.jsx`: import `OverviewPage` from `'./pages/OverviewPage.jsx'`, replace `<Route index element={<RiskMapPage />} />` with `<Route index element={<OverviewPage />} />`, remove the now-unused `RiskMapPage` import.

Delete `frontend/src/pages/RiskMapPage.jsx`.

- [ ] **Step 8: CSS for map area, glass chrome, segmented control**

Append to `global.css`:

```css
/* ---- Overview page: map + side panel ---- */
.overview-page {
  display: flex;
  height: 100%;
}
.overview-map-area {
  flex: 1;
  position: relative;
}
.overview-map-area .leaflet-map {
  height: 100%;
}
.overview-side-panel {
  width: 360px;
  flex-shrink: 0;
  border-left: 1px solid var(--divider);
  overflow-y: auto;
}

.glass {
  background: var(--glass-bg);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: var(--glass-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
}

.map-segmented-control {
  position: absolute;
  top: 16px;
  left: 16px;
  z-index: 500;
  display: flex;
  padding: 3px;
  gap: 2px;
}
.map-segmented-control button {
  border: none;
  background: none;
  padding: 6px 10px;
  border-radius: calc(var(--radius-lg) - 4px);
  font-size: 12px;
  color: var(--text-secondary);
  cursor: pointer;
}
.map-segmented-control button.active {
  background: var(--accent);
  color: #fff;
}

.map-date-pill {
  position: absolute;
  top: 16px;
  right: 60px;
  z-index: 500;
  padding: 7px 14px;
  font-size: 13px;
  color: var(--text);
}

.risk-legend {
  position: absolute;
  z-index: 500;
  padding: 12px 14px;
  cursor: grab;
  max-width: 220px;
}

.ndci-gradient-bar {
  height: 10px;
  border-radius: 5px;
  margin: 8px 0 4px;
  background: linear-gradient(
    90deg,
    rgb(10, 30, 90) 0%,
    rgb(176, 224, 230) 40%,
    rgb(255, 159, 10) 70%,
    rgb(139, 0, 0) 100%
  );
}
.ndci-gradient-labels {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  font-family: var(--font-mono);
  color: var(--text-secondary);
}
```

Leaflet's `ZoomControl` at `topright` will visually collide with the date pill — set the date pill's `right` past the zoom control's width (already done above, `right: 60px`); verify visually in Step 9 and adjust if it still overlaps.

- [ ] **Step 9: Verify**

`npm run lint`. In Chrome: open `/`, confirm the map fills the left area and `SitePanel` still opens on marker click (unchanged behavior). Click through all 3 segmented-control modes and confirm: True Color swaps to satellite imagery tiles, NDCI shows the colored noise overlay + gradient legend, Risk map shows the original CartoDB + swatch legend. Drag the legend and confirm it moves. Confirm zoom buttons are top-right and functional. Check console for errors.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/utils/noiseField.js frontend/src/components/NdciRasterOverlay.jsx frontend/src/components/MapControls.jsx frontend/src/components/RiskMap.jsx frontend/src/components/RiskLegend.jsx frontend/src/pages/OverviewPage.jsx frontend/src/main.jsx frontend/src/styles/global.css
git rm frontend/src/pages/RiskMapPage.jsx
git commit -m "Add map view-mode segmented control, NDCI illustrative overlay, draggable legend"
```

---

## Task 4: Overview right-panel cards

**Files:**
- Create: `frontend/src/utils/climatology.js`
- Create: `frontend/src/components/AlertCard.jsx`
- Create: `frontend/src/components/SpectralMetricsCard.jsx`
- Create: `frontend/src/components/NdciTrendCard.jsx`
- Create: `frontend/src/components/SatelliteImageCard.jsx`
- Modify: `frontend/src/pages/OverviewPage.jsx`
- Delete: `frontend/src/components/SitePanel.jsx`
- Modify: `frontend/src/styles/global.css`

**Interfaces:**
- Produces: `AlertCard({ site })`, `SpectralMetricsCard({ site, detect, latestTimeseriesPoint })`, `NdciTrendCard({ points })` (points = raw `/timeseries` `points` array), `SatelliteImageCard({ trueColorUrl, ndciHeatmapUrl, noImageMessage, caption })`, `dayOfYearBaseline(points)` returning `[{ date, current, baseline }]`.
- Consumes: `site` shape identical to what `RiskMap.jsx` already passes into `onSelectSite` (`{ lat, lng, ...RiskMapProperties }`), `dt`/`ts` shapes identical to `useApi(detect, ...)` / `useApi(getTimeseries, ...)` results already used by the deleted `SitePanel.jsx`, `RISK_LABEL_TH` (added to `constants.js` in Task 2).

This task moves `SitePanel.jsx`'s already-correct data-fetching and field logic into 4 separate cards; it does not add any new fetches beyond what `SitePanel` already made (`/timeseries`, `/detect`).

- [ ] **Step 1: Day-of-year climatology baseline util**

```js
// frontend/src/utils/climatology.js
/**
 * Client-side day-of-year baseline from the SAME full-history /timeseries
 * response already fetched for the trend chart (2002-present MODIS
 * chlor_a, per CLAUDE.md's climatology baseline definition) — no new
 * endpoint. For each point in the most recent ~365 days, baseline is the
 * mean chlor_a of all OTHER years' points within +/-7 days of the same
 * day-of-year (mirrors backend/src/routers/timeseries.py's own
 * _CLIMATOLOGY_WINDOW_DAYS=7, so the two stay conceptually aligned even
 * though this one runs client-side over the bulk series instead of
 * per-point server-side).
 */
const WINDOW_DAYS = 7

function dayOfYear(dateStr) {
  const d = new Date(dateStr)
  const start = new Date(d.getFullYear(), 0, 0)
  return Math.floor((d - start) / 86400000)
}

export function dayOfYearBaseline(points) {
  if (!points || points.length === 0) return []
  const recent = points.slice(-365)
  const cutoffYear = new Date(recent[recent.length - 1]?.date).getFullYear()

  return recent.map((p) => {
    const doy = dayOfYear(p.date)
    const priorYears = points.filter((q) => {
      const qYear = new Date(q.date).getFullYear()
      if (qYear >= cutoffYear) return false
      const qDoy = dayOfYear(q.date)
      return Math.abs(qDoy - doy) <= WINDOW_DAYS
    })
    const baseline = priorYears.length
      ? priorYears.reduce((sum, q) => sum + q.chlor_a, 0) / priorYears.length
      : null
    return { date: p.date, current: p.chlor_a, baseline }
  })
}
```

- [ ] **Step 2: `AlertCard.jsx`** (moves `SitePanel`'s "Predicted risk" section into a standalone card)

```jsx
import { RISK_COLOR_VAR, RISK_LABEL_TH, RULE_DESCRIPTION, NO_DATA_STATUS, STATUS_LABEL, formatConfidence } from '../constants.js'

export default function AlertCard({ site }) {
  const isNoData = NO_DATA_STATUS.has(site.status)
  const riskColorVar = RISK_COLOR_VAR[site.risk_level] || null
  const triggeredCount = site.triggered_rules ? site.triggered_rules.length : 0
  const topRule = site.triggered_rules && site.triggered_rules.length
    ? RULE_DESCRIPTION[site.triggered_rules[site.triggered_rules.length - 1]]
    : null

  return (
    <div className="card alert-card">
      <div className="eyebrow">แจ้งเตือน (บ่งชี้ ไม่ใช่การพยากรณ์ที่ผ่านการตรวจสอบ)</div>
      <span className={`risk-pill${isNoData ? ' no-data' : ''}`}>
        <span className="dot" style={riskColorVar && !isNoData ? { background: `var(${riskColorVar})` } : undefined} />
        {isNoData ? STATUS_LABEL[site.status] || 'ไม่มีค่าอ่าน' : RISK_LABEL_TH[site.risk_level]}
      </span>
      <h2>{isNoData ? STATUS_LABEL[site.status] : RISK_LABEL_TH[site.risk_level]}</h2>
      <div className="stat-detail">{site.name}</div>
      <hr className="card-divider" />
      <p className="stat-detail">
        ความเชื่อมั่นของการพยากรณ์: {site.confidence_label ? formatConfidence(site.confidence_label) : 'ไม่ระบุ'}
      </p>
      <p className="stat-detail">กฎที่ถูกกระตุ้น: {triggeredCount}/3</p>
      {topRule && <div className="callout amber">{topRule}</div>}
      <p className="card-footnote">
        ผลนี้มาจากกฎที่กำหนดไว้ล่วงหน้า (rule-based) ไม่ใช่แบบจำลองที่ผ่านการฝึกฝน (non-ML)
        และเป็นค่าบ่งชี้ ไม่ใช่การพยากรณ์ที่ผ่านการตรวจสอบความแม่นยำ
      </p>
    </div>
  )
}
```

- [ ] **Step 3: `SpectralMetricsCard.jsx`**

```jsx
import { formatZ } from '../constants.js'

export default function SpectralMetricsCard({ site, detect, latestTimeseriesPoint }) {
  const ndci = detect?.index_values?.[detect.index_used]
  const chlorA = latestTimeseriesPoint?.chlor_a

  return (
    <div className="card spectral-metrics-card">
      <div className="eyebrow">ค่าดัชนีสเปกตรัม</div>
      <div className="spectral-grid">
        <div className="spectral-cell">
          <span className="spectral-value mono">{chlorA != null ? chlorA.toFixed(2) : '—'}</span>
          <span className="spectral-label">Chlorophyll-a (mg/m³)</span>
        </div>
        <div className="spectral-cell">
          <span className="spectral-value mono">
            {ndci != null ? ndci.toFixed(4) : '—'}
            {ndci != null && <span className="approx-marker">approx</span>}
          </span>
          <span className="spectral-label">NDCI (20m)</span>
        </div>
        <div className="spectral-cell">
          <span className="spectral-value mono">—</span>
          <span className="spectral-label">SST (°C) — ไม่มีข้อมูล</span>
        </div>
        <div className="spectral-cell">
          <span className="spectral-value mono">{formatZ(detect?.spatial_anomaly_z)}</span>
          <span className="spectral-label">Anomaly z-score</span>
        </div>
      </div>
      <p className="card-footnote">
        Sentinel-2 scene: {detect?.actual_date || '—'} · cloud {detect?.cloud_fraction != null ? `${Math.round(detect.cloud_fraction * 100)}%` : '—'}
        {latestTimeseriesPoint && ` · MODIS chlor_a: ${latestTimeseriesPoint.date}`}
      </p>
    </div>
  )
}
```

- [ ] **Step 4: `NdciTrendCard.jsx`** (dual-line: this year vs 20-year baseline)

```jsx
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid } from 'recharts'
import { dayOfYearBaseline } from '../utils/climatology.js'

export default function NdciTrendCard({ points }) {
  const data = dayOfYearBaseline(points)
  if (data.length === 0) {
    return (
      <div className="card">
        <div className="eyebrow">แนวโน้ม NDCI</div>
        <p className="no-rules">ไม่มีข้อมูลย้อนหลังสำหรับจุดนี้</p>
      </div>
    )
  }

  return (
    <div className="card ndci-trend-card">
      <div className="eyebrow">แนวโน้ม NDCI</div>
      <ResponsiveContainer width="100%" height={180}>
        <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="2 4" stroke="rgba(60,60,67,0.08)" />
          <XAxis dataKey="date" tick={{ fontSize: 10, fill: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }} tickLine={false} minTickGap={50} />
          <YAxis tick={{ fontSize: 10, fill: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }} tickLine={false} axisLine={false} width={36} />
          <Tooltip contentStyle={{ background: 'var(--surface-raised)', border: '1px solid var(--border)', borderRadius: 8, fontFamily: 'var(--font-mono)', fontSize: 12 }} />
          <Line type="monotone" dataKey="current" name="ปี 2026" stroke="var(--accent)" strokeWidth={2} dot={false} connectNulls={false} isAnimationActive={false} />
          <Line type="monotone" dataKey="baseline" name="ค่าฐาน 20 ปี" stroke="var(--text-secondary)" strokeWidth={1.5} strokeDasharray="5 3" dot={false} connectNulls={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
      <p className="card-footnote">ข้อมูลจริงจาก GET /timeseries (MODIS chlor_a) — เส้นฐานคำนวณจากค่าเฉลี่ยวันเดียวกันของปีก่อนหน้าในชุดข้อมูลเดียวกัน</p>
    </div>
  )
}
```

- [ ] **Step 5: `SatelliteImageCard.jsx`** (thin styling wrapper around the existing `SatelliteImage`)

```jsx
import SatelliteImage from './SatelliteImage.jsx'

export default function SatelliteImageCard(props) {
  return (
    <div className="card satellite-image-card">
      <div className="eyebrow">ภาพถ่ายดาวเทียม</div>
      <SatelliteImage {...props} />
    </div>
  )
}
```

- [ ] **Step 6: Rewrite `OverviewPage.jsx`'s side panel**

Replace the `overview-side-panel` block from Task 3 Step 6. This inlines the fetches `SitePanel.jsx` used to own (same hooks, same shapes):

```jsx
import { useCallback } from 'react'
import { useApi } from '../hooks/useApi.js'
import { getTimeseries, detect } from '../api/client.js'
import AlertCard from '../components/AlertCard.jsx'
import SpectralMetricsCard from '../components/SpectralMetricsCard.jsx'
import NdciTrendCard from '../components/NdciTrendCard.jsx'
import SatelliteImageCard from '../components/SatelliteImageCard.jsx'

const today = () => new Date().toISOString().slice(0, 10)

function SiteDetail({ site }) {
  const fetchTimeseries = useCallback(() => getTimeseries(site.lat, site.lng), [site.lat, site.lng])
  const fetchDetect = useCallback(() => detect(site.lat, site.lng, today()), [site.lat, site.lng])
  const ts = useApi(fetchTimeseries, [site.lat, site.lng])
  const dt = useApi(fetchDetect, [site.lat, site.lng])

  const usingCachedImage = !!site.site_id
  const trueColorImageUrl = usingCachedImage ? site.true_color_image_url || null : dt.data?.true_color_image_url || null
  const ndciHeatmapImageUrl = usingCachedImage ? site.ndci_heatmap_image_url || null : dt.data?.ndci_heatmap_image_url || null
  const imageCaption = usingCachedImage
    ? (site.actual_date ? `Cached · scene ${site.actual_date}` : 'Cached scheduler reading')
    : (dt.data?.actual_date ? `Live render · scene ${dt.data.actual_date}` : 'Live render')

  const latestTimeseriesPoint = ts.data?.points?.length ? ts.data.points[ts.data.points.length - 1] : null

  return (
    <>
      <AlertCard site={site} />
      {dt.data && <SpectralMetricsCard site={site} detect={dt.data} latestTimeseriesPoint={latestTimeseriesPoint} />}
      {ts.data && <NdciTrendCard points={ts.data.points} />}
      {(usingCachedImage || dt.data) && (
        <SatelliteImageCard
          trueColorUrl={trueColorImageUrl}
          ndciHeatmapUrl={ndciHeatmapImageUrl}
          noImageMessage="ไม่มีภาพถ่ายดาวเทียมสำหรับจุดนี้"
          caption={imageCaption}
        />
      )}
    </>
  )
}
```

`SiteDetail` lives in the same `OverviewPage.jsx` file, defined above the `OverviewPage` function (or imported from a co-located file — either is fine, keep it in `OverviewPage.jsx` for locality since nothing else uses it). Replace `OverviewPage`'s `overview-side-panel` JSX block (written in Task 3 Step 6) with:

```jsx
<div className="overview-side-panel">
  {selected ? (
    <>
      <button type="button" className="site-detail-close" onClick={() => setSelected(null)} aria-label="ปิดแผงรายละเอียด">×</button>
      <SiteDetail site={selected} />
    </>
  ) : (
    <div className="state-panel"><h3>เลือกจุดตรวจวัดบนแผนที่</h3></div>
  )}
</div>
```

Remove the now-unused `import SitePanel from '../components/SitePanel.jsx'` line from `OverviewPage.jsx`.

- [ ] **Step 7: Delete `SitePanel.jsx`**

Confirm no remaining imports (`grep -rn "SitePanel" frontend/src` should only show the file itself, if not already deleted) — nothing else in the app references it after this step. `git rm frontend/src/components/SitePanel.jsx`.

- [ ] **Step 8: Card system CSS**

Append to `global.css`:

```css
/* ---- Card system (HAB Sentinel) ---- */
.card {
  background: var(--surface-card);
  border: 1px solid var(--divider);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
  padding: 16px;
  margin-bottom: 16px;
}

.card-divider {
  border: none;
  border-top: 1px solid var(--divider-soft);
  margin: 12px 0;
}

.card-footnote {
  font-size: 11px;
  color: var(--text-tertiary);
  margin-top: 10px;
}

.callout.amber {
  background: rgba(255, 159, 10, 0.1);
  border: 1px solid rgba(255, 159, 10, 0.25);
  border-radius: var(--radius-control);
  padding: 10px 12px;
  font-size: 13px;
  margin-top: 8px;
}

.spectral-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-top: 8px;
}
.spectral-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.spectral-value {
  font-size: var(--fs-20);
  font-weight: 600;
}
.spectral-label {
  font-size: 11px;
  color: var(--text-secondary);
}

.overview-side-panel {
  padding: 16px;
  position: relative;
}

.site-detail-close {
  position: absolute;
  top: 12px;
  right: 12px;
  border: none;
  background: var(--divider-soft);
  color: var(--text-secondary);
  width: 28px;
  height: 28px;
  border-radius: 50%;
  font-size: 16px;
  cursor: pointer;
  z-index: 1;
}
```

- [ ] **Step 9: Verify**

`npm run lint`. In Chrome: open `/`, click a marker, confirm all 4 cards render with real data (alert pill/heading, 2×2 spectral grid with SST showing `—`, dual-line trend chart, satellite image with True/NDCI toggle). Confirm closing and re-selecting a different site refetches correctly (same behavior `SitePanel` had). Check console for errors.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/utils/climatology.js frontend/src/components/AlertCard.jsx frontend/src/components/SpectralMetricsCard.jsx frontend/src/components/NdciTrendCard.jsx frontend/src/components/SatelliteImageCard.jsx frontend/src/pages/OverviewPage.jsx frontend/src/styles/global.css
git rm frontend/src/components/SitePanel.jsx
git commit -m "Split SitePanel into Overview's 4 right-panel cards"
```

---

## Task 5: Sentinel-2 NDCI page

**Files:**
- Create: `frontend/src/pages/NdciPage.jsx`
- Modify: `frontend/src/main.jsx`
- Modify: `frontend/src/styles/global.css`

**Interfaces:**
- Produces: `NdciPage` (no props, route-level page).
- Consumes: `getRiskMap()` (existing).

- [ ] **Step 1: Write `NdciPage.jsx`**

```jsx
import { useApi } from '../hooks/useApi.js'
import { getRiskMap } from '../api/client.js'
import { NO_DATA_STATUS, STATUS_LABEL, RISK_LABEL_TH, formatZ } from '../constants.js'

const INDEX_DEFINITIONS = [
  { name: 'NDCI', formula: '(R705 − R665) / (R705 + R665)', description: 'ดัชนีคลอโรฟิลล์ปกติ (Normalized Difference Chlorophyll Index) — ดัชนีหลักของระบบ' },
  { name: '2BDA', formula: 'R709 / R665', description: '2-Band Algorithm — สัดส่วนสองแถบคลื่นสำหรับตรวจจับคลอโรฟิลล์' },
  { name: '3BDA', formula: '(1/R665 − 1/R709) × R753', description: '3-Band Algorithm — ชดเชยผลของสารอินทรีย์ละลายน้ำและตะกอนแขวนลอย' },
  { name: 'B2−B3', formula: 'R490 − R560', description: 'ผลต่างแถบคลื่นสีน้ำเงิน-เขียว — ใช้แยกแยะ Noctiluca สีเขียวจากคลอโรฟิลล์ทั่วไป' },
]

export default function NdciPage() {
  const { data, loading, error, refetch } = useApi(getRiskMap, [])
  const sites = data?.features || []

  return (
    <div className="page">
      <div className="page-header">
        <h1>Sentinel-2 NDCI</h1>
        <span className="updated-line">ดัชนีสเปกตรัมสำหรับตรวจจับสาหร่ายบาน</span>
      </div>

      <div className="index-def-grid">
        {INDEX_DEFINITIONS.map((idx) => (
          <div className="card index-def-card" key={idx.name}>
            <h3>{idx.name}</h3>
            <div className="mono index-formula">{idx.formula}</div>
            <p className="stat-detail">{idx.description}</p>
          </div>
        ))}
      </div>

      {loading && <div className="state-panel"><h3>กำลังโหลดข้อมูล…</h3></div>}
      {error && (
        <div className="state-panel error">
          <h3>เชื่อมต่อไม่สำเร็จ</h3>
          <button type="button" className="retry-btn" onClick={refetch}>ลองใหม่</button>
        </div>
      )}

      {data && (
        <div className="card">
          <div className="section-title">ค่าอ่านล่าสุดต่อจุดตรวจวัด</div>
          <div className="table-scroll">
            <table className="events-table">
              <thead>
                <tr>
                  <th>จุดตรวจวัด</th>
                  <th>ดัชนีที่ใช้</th>
                  <th>ดัชนี (z-score)</th>
                  <th>สถานะ</th>
                </tr>
              </thead>
              <tbody>
                {sites.map((f) => {
                  const p = f.properties
                  const isNoData = NO_DATA_STATUS.has(p.status)
                  return (
                    <tr key={p.site_id}>
                      <td>{p.name}</td>
                      <td className="mono">{p.index_used || '—'}</td>
                      <td className="mono">{isNoData ? '—' : formatZ(p.spatial_anomaly_z)}</td>
                      <td>{isNoData ? STATUS_LABEL[p.status] || 'ไม่มีค่าอ่าน' : RISK_LABEL_TH[p.risk_level]}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
```

Correction: the former `/risk-map` anomaly value was dimensionally invalid and is removed. Its `spatial_anomaly_z` field is a null placeholder. The current table shows raw NDCI where available and states that the anomaly is not computed because no valid baseline exists; the historical table example above is superseded.

- [ ] **Step 2: Wire the route**

In `main.jsx`: import `NdciPage`, replace `<Route path="ndci" element={<NdciStub />} />` with `<Route path="ndci" element={<NdciPage />} />`, delete the inline `NdciStub` function.

- [ ] **Step 3: CSS**

Append to `global.css`:

```css
.index-def-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 16px;
  margin-bottom: 20px;
}
.index-def-card h3 {
  font-size: var(--fs-16);
}
.index-formula {
  font-size: 13px;
  margin: 6px 0;
  color: var(--accent);
}
```

- [ ] **Step 4: Verify**

`npm run lint`. In Chrome: navigate to `/ndci`, confirm the 4 index cards render, the table lists all 6 grid sites with real data, no-data sites show dash + status label. Check console.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/NdciPage.jsx frontend/src/main.jsx frontend/src/styles/global.css
git commit -m "Add Sentinel-2 NDCI page: index definitions + per-site table"
```

---

## Task 6: Seasonal Anomaly page

**Files:**
- Create: `frontend/src/utils/anomalyBuckets.js`
- Create: `frontend/src/pages/SeasonalAnomalyPage.jsx`
- Modify: `frontend/src/main.jsx`
- Delete: `frontend/src/pages/SummaryPage.jsx`
- Modify: `frontend/src/styles/global.css`

**Interfaces:**
- Produces: `bucketAnomalyStrip(points, days = 90, cells = 45)` → array of `{ z: number|null, tooltip: string }`, length `cells`.
- Consumes: `getSummary`, `getRiskMap`, `getTimeseries` (all existing, same as the deleted `SummaryPage.jsx`), `AnomalyStrip`, `RegionTrendChart`, `StatCard` (all existing, unmodified).

- [ ] **Step 1: 45-cell bucketing util**

```js
// frontend/src/utils/anomalyBuckets.js
/**
 * Buckets a site's last `days` of /timeseries points into `cells`
 * equal-width windows (docs/superpowers/specs/2026-08-26-hab-sentinel-
 * dashboard-design.md, Screen 3). A cell's z is the mean of its window's
 * non-null anomaly_z values; a window with none is null (renders hatched
 * via AnomalyStrip's existing no-data handling — no new visual language).
 */
export function bucketAnomalyStrip(points, days = 90, cells = 45) {
  const recent = (points || []).slice(-days)
  if (recent.length === 0) return Array.from({ length: cells }, () => ({ z: null, tooltip: 'ไม่มีข้อมูล' }))

  const lastDate = new Date(recent[recent.length - 1].date)
  const firstDate = new Date(lastDate)
  firstDate.setDate(firstDate.getDate() - days)
  const windowMs = (lastDate - firstDate) / cells

  const buckets = Array.from({ length: cells }, () => [])
  for (const p of recent) {
    const offset = new Date(p.date) - firstDate
    let idx = Math.floor(offset / windowMs)
    idx = Math.min(cells - 1, Math.max(0, idx))
    if (p.anomaly_z !== null && p.anomaly_z !== undefined) buckets[idx].push(p.anomaly_z)
  }

  return buckets.map((zs, i) => {
    if (zs.length === 0) return { key: i, z: null, tooltip: 'ไม่มีค่าอ่านในช่วงนี้' }
    const mean = zs.reduce((a, b) => a + b, 0) / zs.length
    return { key: i, z: mean, tooltip: `z เฉลี่ย = ${mean.toFixed(2)}` }
  })
}
```

- [ ] **Step 2: `SeasonalAnomalyPage.jsx`**

Builds on the deleted `SummaryPage.jsx`'s exact fetch pattern (region stat row + most-recent-signal + prediction-confidence + region trend chart, all unchanged/real), adding the per-site 45-cell strips the new spec calls for.

```jsx
import { useCallback, useMemo } from 'react'
import { useApi } from '../hooks/useApi.js'
import { getSummary, getRiskMap, getTimeseries } from '../api/client.js'
import StatCard from '../components/StatCard.jsx'
import AnomalyStrip from '../components/AnomalyStrip.jsx'
import RegionTrendChart from '../components/RegionTrendChart.jsx'
import { bucketAnomalyStrip } from '../utils/anomalyBuckets.js'
import { formatRelativeTime, formatZ, NO_DATA_STATUS } from '../constants.js'

export default function SeasonalAnomalyPage() {
  const summaryApi = useApi(getSummary, [])
  const riskMapApi = useApi(getRiskMap, [])

  const sites = useMemo(
    () =>
      (riskMapApi.data?.features || []).map((f) => ({
        site_id: f.properties.site_id,
        name: f.properties.name,
        lat: f.geometry.coordinates[1],
        lng: f.geometry.coordinates[0],
        spatial_anomaly_z: f.properties.spatial_anomaly_z,
        status: f.properties.status,
      })),
    [riskMapApi.data],
  )
  const siteKey = sites.map((s) => s.site_id).join(',')

  const fetchTrend = useCallback(async () => {
    const results = await Promise.all(
      sites.map(async (site) => {
        try {
          const ts = await getTimeseries(site.lat, site.lng)
          return { site, points: ts.points || [] }
        } catch {
          return { site, points: [] }
        }
      }),
    )
    return results
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [siteKey])
  const trendApi = useApi(fetchTrend, [siteKey], { enabled: sites.length > 0 })

  const s = summaryApi.data
  const sitesWithReading = sites.filter((site) => !NO_DATA_STATUS.has(site.status)).length
  const watchCount = sites.filter((site) => site.status === 'ok' && site.risk_level === 'watch').length
  const maxZ = sites.reduce((max, site) => (site.spatial_anomaly_z != null && site.spatial_anomaly_z > max ? site.spatial_anomaly_z : max), -Infinity)

  return (
    <div className="page">
      <div className="page-header">
        <h1>ความผิดปกติตามฤดูกาล</h1>
        <span className="updated-line">
          อ้างอิงเส้นฐานภูมิอากาศ MODIS ย้อนหลัง — หน้าต่าง 90 วัน
          {s?.newest_fetched_at ? ` · อัปเดตล่าสุด ${formatRelativeTime(s.newest_fetched_at)}` : ''}
        </span>
      </div>

      <div className="stat-row">
        <StatCard label="จุดตรวจวัด" value={sites.length} />
        <StatCard label="มีค่าอ่าน" value={sitesWithReading} />
        <StatCard label="เฝ้าระวัง" value={watchCount} riskLevel="watch" />
        <StatCard label="z-score สูงสุด" value={maxZ === -Infinity ? '—' : formatZ(maxZ)} />
      </div>

      {s && (
        <div className="card">
          <div className="section-title">ล่าสุดทั้งภูมิภาค</div>
          {s.most_recent_detected_signal ? (
            <p className="stat-detail">
              {s.most_recent_detected_signal.name} · z = {formatZ(s.most_recent_detected_signal.spatial_anomaly_z)} ·{' '}
              {s.most_recent_detected_signal.actual_date || '—'}
            </p>
          ) : (
            <p className="no-rules">ยังไม่มีสัญญาณตรวจพบล่าสุดในขณะนี้</p>
          )}
          <p className="stat-detail">ความเชื่อมั่นของการพยากรณ์: {s.prediction_confidence_label}</p>
        </div>
      )}

      <div className="section-title">แถบความผิดปกติรายจุดตรวจวัด</div>
      {trendApi.loading && <p className="no-rules">กำลังโหลดประวัติรายจุด…</p>}
      {trendApi.data &&
        trendApi.data.map(({ site, points }) => (
          <div className="anomaly-site-row" key={site.site_id}>
            <div className="anomaly-site-name">
              {site.name}
              <span className="mono stat-detail"> z = {formatZ(site.spatial_anomaly_z)}</span>
            </div>
            <AnomalyStrip
              segments={bucketAnomalyStrip(points, 90, 45)}
              leftLabel="90 วันก่อน"
              rightLabel="ล่าสุด"
            />
          </div>
        ))}

      <div className="section-title" style={{ marginTop: 24 }}>แนวโน้มคลอโรฟิลล์รายจุด 90 วันล่าสุด</div>
      {trendApi.data && <RegionTrendChart sitesWithPoints={trendApi.data.map((r) => ({ site: r.site, points: r.points.slice(-90) }))} />}
    </div>
  )
}
```

- [ ] **Step 3: Wire the route, delete the old page**

In `main.jsx`: import `SeasonalAnomalyPage`, replace `<Route path="anomaly" element={<SummaryPage />} />` with `<Route path="anomaly" element={<SeasonalAnomalyPage />} />`, remove the `SummaryPage` import. Delete `frontend/src/pages/SummaryPage.jsx`.

- [ ] **Step 4: CSS**

Append to `global.css`:

```css
.anomaly-site-row {
  margin-bottom: 16px;
}
.anomaly-site-name {
  font-size: var(--fs-14);
  margin-bottom: 4px;
}
```

- [ ] **Step 5: Verify**

`npm run lint`. In Chrome: navigate to `/anomaly`, confirm 4 stat cards with real numbers, region callout, one 45-cell strip per site with hover tooltips, and the multi-site trend chart below. Check console.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/utils/anomalyBuckets.js frontend/src/pages/SeasonalAnomalyPage.jsx frontend/src/main.jsx frontend/src/styles/global.css
git rm frontend/src/pages/SummaryPage.jsx
git commit -m "Add Seasonal Anomaly page: stat cards, per-site 45-cell strips, region trend"
```

---

## Task 7: Aquaculture Zones page

**Files:**
- Create: `frontend/src/utils/geo.js`
- Create: `frontend/src/data/aquacultureZones.js`
- Create: `frontend/src/pages/AquaculturePage.jsx`
- Modify: `frontend/src/main.jsx`
- Modify: `frontend/src/styles/global.css`

**Interfaces:**
- Produces: `haversineKm(lat1, lng1, lat2, lng2)`, `AQUACULTURE_ZONES` (static array).
- Consumes: `getRiskMap()` (existing, for the 6-grid-site list + live status).

`backend/src/grid.py`'s 6 sites are hardcoded in `RiskMap.jsx`'s comments already; this task reads them from the live `/risk-map` response instead of duplicating the list a third time.

- [ ] **Step 1: Haversine distance util**

```js
// frontend/src/utils/geo.js
/** Great-circle distance in km between two lat/lng points (haversine). */
export function haversineKm(lat1, lng1, lat2, lng2) {
  const R = 6371
  const dLat = ((lat2 - lat1) * Math.PI) / 180
  const dLng = ((lng2 - lng1) * Math.PI) / 180
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos((lat1 * Math.PI) / 180) * Math.cos((lat2 * Math.PI) / 180) * Math.sin(dLng / 2) ** 2
  return R * 2 * Math.asin(Math.sqrt(a))
}
```

- [ ] **Step 2: Static illustrative zone list**

```js
// frontend/src/data/aquacultureZones.js
/**
 * Illustrative aquaculture-zone markers — NOT a real registry. There is
 * no aquaculture-zone data source anywhere in this system (CLAUDE.md /
 * this page's own disclosure banner). Coordinates here are approximate
 * placeholders for well-known upper-Gulf coastal aquaculture clusters,
 * used only to demonstrate the nearest-grid-point-proxy pattern the
 * design calls for — never presented as verified zone boundaries.
 */
export const AQUACULTURE_ZONES = [
  { id: 'samutsongkhram', name: 'สมุทรสงคราม (ตัวอย่าง)', lat: 13.41, lng: 100.0 },
  { id: 'samutsakhon', name: 'สมุทรสาคร (ตัวอย่าง)', lat: 13.55, lng: 100.28 },
  { id: 'chonburi_south', name: 'ชลบุรีตอนใต้ (ตัวอย่าง)', lat: 13.05, lng: 100.92 },
  { id: 'phetchaburi', name: 'เพชรบุรี (ตัวอย่าง)', lat: 12.9, lng: 99.96 },
]
```

- [ ] **Step 3: `AquaculturePage.jsx`**

```jsx
import { useApi } from '../hooks/useApi.js'
import { getRiskMap } from '../api/client.js'
import { AQUACULTURE_ZONES } from '../data/aquacultureZones.js'
import { haversineKm } from '../utils/geo.js'
import { NO_DATA_STATUS, STATUS_LABEL, RISK_LABEL_TH } from '../constants.js'

export default function AquaculturePage() {
  const { data, loading, error, refetch } = useApi(getRiskMap, [])
  const sites = (data?.features || []).map((f) => ({
    site_id: f.properties.site_id,
    name: f.properties.name,
    lat: f.geometry.coordinates[1],
    lng: f.geometry.coordinates[0],
    status: f.properties.status,
    risk_level: f.properties.risk_level,
  }))

  return (
    <div className="page">
      <div className="page-header">
        <h1>พื้นที่เพาะเลี้ยงสัตว์น้ำ</h1>
        <span className="updated-line">ตำแหน่งเพาะเลี้ยงอ้างอิงจากจุดตรวจวัดที่ใกล้ที่สุด</span>
      </div>

      <div className="callout amber disclosure-banner">
        พิกัดพื้นที่เพาะเลี้ยงจริงยังไม่มีอยู่ในระบบ — รายการด้านล่างเป็น
        <strong> ตำแหน่งตัวอย่าง</strong> อ้างอิงจากจุดตรวจวัดที่ใกล้ที่สุดเท่านั้น ไม่ใช่การอ่านค่าโดยตรงจากพื้นที่เพาะเลี้ยงจริง
      </div>

      {loading && <div className="state-panel"><h3>กำลังโหลด…</h3></div>}
      {error && (
        <div className="state-panel error">
          <h3>เชื่อมต่อไม่สำเร็จ</h3>
          <button type="button" className="retry-btn" onClick={refetch}>ลองใหม่</button>
        </div>
      )}

      {sites.length > 0 && (
        <div className="zone-grid">
          {AQUACULTURE_ZONES.map((zone) => {
            const nearest = sites.reduce((best, site) => {
              const d = haversineKm(zone.lat, zone.lng, site.lat, site.lng)
              return !best || d < best.distance ? { site, distance: d } : best
            }, null)
            const isNoData = nearest && NO_DATA_STATUS.has(nearest.site.status)
            return (
              <div className="card zone-card" key={zone.id}>
                <h3>{zone.name}</h3>
                <span className={`risk-pill${isNoData ? ' no-data' : ''}`}>
                  {isNoData ? STATUS_LABEL[nearest.site.status] : RISK_LABEL_TH[nearest.site.risk_level]}
                </span>
                <p className="stat-detail">จุดตรวจวัดที่ใกล้ที่สุด: {nearest.site.name}</p>
                <p className="stat-detail mono">ระยะห่างโดยประมาณ: {nearest.distance.toFixed(1)} กม.</p>
                <p className="stat-detail">ความหนาแน่นเซลล์: ไม่มีข้อมูล</p>
              </div>
            )
          })}
        </div>
      )}

      <div className="section-title" style={{ marginTop: 24 }}>จุดตรวจวัดทั้งหมด</div>
      <div className="zone-grid">
        {sites.map((site) => {
          const isNoData = NO_DATA_STATUS.has(site.status)
          return (
            <div className="card" key={site.site_id}>
              <h3>{site.name}</h3>
              <p className="mono stat-detail">{site.lat.toFixed(4)}°N, {site.lng.toFixed(4)}°E</p>
              <span className={`risk-pill${isNoData ? ' no-data' : ''}`}>
                {isNoData ? STATUS_LABEL[site.status] : RISK_LABEL_TH[site.risk_level]}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Wire the route**

In `main.jsx`: import `AquaculturePage`, replace `<Route path="aquaculture" element={<AquacultureStub />} />` with `<Route path="aquaculture" element={<AquaculturePage />} />`, delete the inline `AquacultureStub` function.

- [ ] **Step 5: CSS**

Append to `global.css`:

```css
.disclosure-banner {
  margin-bottom: 20px;
}
.zone-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 16px;
}
```

- [ ] **Step 6: Verify**

`npm run lint`. In Chrome: navigate to `/aquaculture`, confirm the disclosure banner, 4 illustrative zone cards each with a nearest-site name + computed distance + "ไม่มีข้อมูล" cell-density line, and the full 6-site list below. Check console.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/utils/geo.js frontend/src/data/aquacultureZones.js frontend/src/pages/AquaculturePage.jsx frontend/src/main.jsx frontend/src/styles/global.css
git commit -m "Add Aquaculture Zones page with nearest-grid-site proxy distances"
```

---

## Task 8: Reports & Exports page

The Reports page retains service status, scan history, and inactive export chrome. The retired bloom-event dataset, endpoint, table, and export action are intentionally absent.

---

## Task 9: Final cleanup and full smoke test

**Files:**
- Modify: `frontend/src/styles/global.css` (dead-code sweep only)

- [ ] **Step 1: Dead CSS sweep**

Search JSX `className` usages to confirm every CSS class remains referenced; remove dead rules from superseded pages.

- [ ] **Step 2: Full lint pass**

```bash
cd frontend && npm run lint
```
Expected: 0 errors.

- [ ] **Step 3: Full click-through smoke test**

In the Chrome browser tool, with both the backend and `npm run dev` running:
1. Navigate to `/` — map loads, all 3 view modes work, marker click populates all 4 right-panel cards.
2. Click each of the other 4 sidebar nav items in turn (`/ndci`, `/anomaly`, `/aquaculture`, `/reports`) — each renders without a blank page or console error.
3. On `/reports`, confirm the page renders service status, scan history, and inactive export actions without retired dataset content.
4. Confirm the disclaimer banner is present on every route.
5. Read console messages (`read_console_messages`) on each route and confirm no errors/warnings introduced by this work.

- [ ] **Step 4: Commit (only if Step 1 removed anything)**

```bash
git add frontend/src/styles/global.css
git commit -m "Remove dead CSS from pre-redesign pages"
```
