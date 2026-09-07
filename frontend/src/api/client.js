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

const baseURL = import.meta.env.VITE_API_BASE_URL || DEV_FALLBACK_BASE_URL

// Runs once, at module import -- not per request. Without this, an unset
// VITE_API_BASE_URL degrades silently to the localhost fallback and the
// only symptom is a bare ERR_CONNECTION_REFUSED per call, which says
// nothing about *why* the URL is localhost. Say both facts out loud.
if (!import.meta.env.VITE_API_BASE_URL) {
  console.warn(
    `[api] VITE_API_BASE_URL is not set — falling back to ${DEV_FALLBACK_BASE_URL}. ` +
      'A backend must be running there, or every API call fails with ' +
      'ERR_CONNECTION_REFUSED. Start it with ./scripts/dev.sh (or ' +
      'cd backend && uvicorn src.main:app --reload), or set ' +
      'VITE_API_BASE_URL in frontend/.env — see frontend/.env.example.',
  )
}

export const client = axios.create({ baseURL, timeout: 30000 })

export async function getRiskMap() {
  const { data } = await client.get('/risk-map')
  return data
}

export async function getRasterScan() {
  const { data } = await client.get('/raster-scan')
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

export async function getRegionalScan() {
  const { data } = await client.get('/regional-scan')
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
