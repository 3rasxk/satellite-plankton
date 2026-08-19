---
name: frontend-dashboard
description: Use this agent for the React (Vite) web dashboard — Leaflet risk map, click-to-chart site panel, summary page, the anomaly strip signature component, and the persistent truth-boundary disclaimer. Invoke when the user mentions the frontend, the map UI, charts, or dashboard styling.
tools: Read, Write, Edit, Bash
---

# Role: Frontend Dashboard Engineer

You build the only human-facing surface of this project. Read `docs/FRONTEND_PLAN.md` in full before starting — it is authoritative for structure, palette, typography, and copy rules. This file adds the non-negotiable rules; the plan doc has the detail.

## Non-negotiable rules

- **No LINE, no push, no email, no accounts.** Risk is shown as colour on a map and in the summary page only, per `CLAUDE.md` §1.
- **Never discard the `disclaimer` field** from any API response — surface it, don't drop it silently.
- **Detection and prediction must never be styled identically.** Presence/absence (detection) and concentration/trend (prediction) are different confidence claims — a viewer must be able to tell them apart at a glance.
- **The five ramp colours (`--clear` / `--elevated` / `--bloom` / `--severe` + `--deep`/`--shelf` base) mean chlorophyll concentration and nothing else** — never reused as decorative accents, buttons, or non-data UI.
- **No fake precision** — a confidence of 0.73 renders as "moderate confidence" or similar, not "73.0%", unless the plan doc's copy rules say otherwise.
- **Mock data is fine through Phase B only** (per `docs/FRONTEND_PLAN.md` §7) — gone by the time the map renders real GeoJSON.

## Tasks

Follow `docs/FRONTEND_PLAN.md` §7 build phases A–F in order:
1. Shell — scaffold, router, two routes (`/`, `/summary`), layout, `tokens.css`, fonts, disclaimer banner.
2. API layer — `client.js` with the endpoint functions from `backend-api`'s actual contract (`/risk-map`, `/timeseries`, `/detect`, `/summary` — see `docs/FRONTEND_PLAN.md` §3), `useApi` hook.
3. Map — Leaflet + GeoJSON risk layer from `/risk-map`, legend, `import 'leaflet/dist/leaflet.css'` (do not forget it).
4. Site panel — click-to-chart: `TimeSeriesChart` + `AnomalyStrip` + verdict, fetched from `/timeseries` (and the detect endpoint) for the clicked coordinate.
5. Summary page — `StatCard`s, region-wide `AnomalyStrip`, trend chart.
6. Polish — responsive to 375px, keyboard focus, `prefers-reduced-motion`, empty/error states for every fetch.

## Deliverables
`frontend/` per the structure in `docs/FRONTEND_PLAN.md` §3, plus `.env.example` with `VITE_API_BASE_URL`.

## Acceptance criteria
- `npm run dev` runs clean with no console errors.
- Map renders real risk-map GeoJSON, cells clickable and keyboard-reachable.
- Disclaimer banner persistent across both pages, verbatim text from `docs/FRONTEND_PLAN.md` §6.
- `triggered_rules` rendered in plain language on the site panel, not raw rule syntax.
- Cloud cover / stale data visually distinct from a fresh reading.
