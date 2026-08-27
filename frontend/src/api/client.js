/**
 * Axios client for the Gulf of Thailand Algal Bloom Monitor API.
 *
 * Data source: backend/src (FastAPI) — wraps detection/src physics-based
 * indices + MODIS climatology anomaly z-scores + rule-based escalation.
 * No trained model anywhere in this chain (CLAUDE.md §0/§1).
 *
 * Limitation: this file only shapes HTTP calls. It does not interpret or
 * validate response fields beyond basic destructuring — every field,
 * including `disclaimer`, is passed through untouched for the UI layer to
 * render honestly.
 */
import axios from 'axios'

const baseURL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

export const client = axios.create({ baseURL, timeout: 30000 })

export async function getRiskMap() {
  const { data } = await client.get('/risk-map')
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

export async function getValidation() {
  const { data } = await client.get('/validation')
  return data
}

export async function getWatchOverlay() {
  const { data } = await client.get('/watch-overlay')
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
