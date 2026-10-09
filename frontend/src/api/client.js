/**
 * Axios client for the Gulf of Thailand Algal Bloom Monitor API.
 *
 * Data source: backend/src (FastAPI) — wraps detection/src physics-based
 * indices with actual scene dates. Spectral-index anomaly scoring and
 * rule-based escalation are inactive until a valid baseline exists.
 * No trained model anywhere in this chain (CLAUDE.md §0/§1).
 *
 * Limitation: this file only shapes HTTP calls. It does not interpret or
 * validate response fields beyond basic destructuring — every field,
 * including `disclaimer`, is passed through untouched for the UI layer to
 * render honestly.
 */
import axios from 'axios'

const DEV_FALLBACK_BASE_URL = 'http://localhost:8000'

// `import.meta.env` exists only under Vite. Plain Node (`node --test`, which
// loads src/lib/provenance.js and therefore this file) has none, so read it
// defensively instead of throwing at import.
const viteEnv = import.meta.env
const env = viteEnv ?? {}

const baseURL = env.VITE_API_BASE_URL || DEV_FALLBACK_BASE_URL

// Runs once, at module import -- not per request. Without this, an unset
// VITE_API_BASE_URL degrades silently to the localhost fallback and the
// only symptom is a bare ERR_CONNECTION_REFUSED per call, which says
// nothing about *why* the URL is localhost. Say both facts out loud.
// Only inside Vite: under plain Node there is no .env to have forgotten.
if (viteEnv && !env.VITE_API_BASE_URL) {
  console.warn(
    `[api] VITE_API_BASE_URL is not set — falling back to ${DEV_FALLBACK_BASE_URL}. ` +
      'A backend must be running there, or every API call fails with ' +
      'ERR_CONNECTION_REFUSED. Start it with ./scripts/dev.sh (or ' +
      'cd backend && uvicorn src.main:app --reload), or set ' +
      'VITE_API_BASE_URL in frontend/.env — see frontend/.env.example.',
  )
}

export const client = axios.create({ baseURL, timeout: 30000 })

/** Absolute-ish URL for a non-XHR asset served by the API (an <img> src).
 *
 * axios prefixes `baseURL` for us; a browser fetching an image does not.
 * With VITE_API_BASE_URL=/api the API is reached through Vite's proxy, so
 * a bare "/raster-scan/overlay.png" resolves against the dev server, which
 * answers with the SPA's index.html and leaves the <img> silently blank --
 * no console error, no failed request in the network tab's error filter,
 * just an empty map. Compose asset URLs through here so they travel the
 * same path the JSON does.
 */
export function apiAssetUrl(path) {
  if (!path) return null
  if (/^https?:\/\//i.test(path)) return path
  return `${baseURL.replace(/\/$/, '')}${path}`
}

export async function getRiskMap() {
  const { data } = await client.get('/risk-map')
  return data
}

export async function getRasterScan() {
  const { data } = await client.get('/raster-scan')
  return data
}

// One cell of the raster overlay, by coordinate. Reads the stored blob the
// picture was drawn from -- not a live Earth Engine call -- so the numbers
// shown on a click are the numbers behind the pixel on screen. A 404 here
// means there is no raster to query (or its cells expired), NOT that the
// water was measured and found empty.
export async function getRasterPixel(lat, lng, runId) {
  const { data } = await client.get('/raster-scan/pixel', { params: { lat, lng, run_id: runId } })
  return data
}

// Highlight / anomaly pins of a stored raster run. Reads the run's stored
// cells, like /raster-scan/pixel -- no Earth Engine call. `params` is passed
// through as given: run_id, n (3-10), min_separation_m (1000-10000), and
// mode ('anomaly' | 'ndci'; the server picks 'anomaly' only while a valid
// TEST cell baseline is in force). A pin is a ranking inside one scan or a
// TEST-baseline anomaly, never a risk marking; `risk_tier` is always null.
export async function getHighlights(params = {}) {
  const { data } = await client.get('/raster-scan/highlights', { params })
  return data
}

// The methods the server actually runs: index formulas with worked examples
// computed by the server's own functions, sensor constants, gates, season
// windows, the TEST baseline block and verified references. Static per
// deployment; no Earth Engine call, no database.
export async function getMethods() {
  const { data } = await client.get('/methods')
  return data
}

export async function getTimeseries(lat, lng) {
  const { data } = await client.get('/timeseries', { params: { lat, lng } })
  return data
}

export async function detect(lat, lng, date) {
  const { data } = await client.get('/detect', { params: { lat, lng, date } })
  return data
}

export async function getSummary() {
  const { data } = await client.get('/summary')
  return data
}

export async function getAlerts() {
  const { data } = await client.get('/api/alerts')
  return data
}

export async function getPinSatellitePreview(lat, lon, date) {
  const { data } = await client.get('/api/satellite/pin-preview', {
    params: { lat, lon, date },
  })
  return data
}

// backend/src/main.py's existing meta route at GET / — reused here only to
// prove the API is reachable (Sidebar's connectivity pill), not for its
// response shape.
export async function getMeta() {
  const { data } = await client.get('/')
  return data
}

export default client
