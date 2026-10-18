/**
 * Station view-model for the glass UI (design reference "Plankton Watch
 * Glass"). Pure functions over `GET /risk-map` features -- no network, no
 * sample data.
 *
 * Risk class: only the backend's own `risk_level` is shown as a class
 * (warning / watch / elevated / normal). While the TEST baseline is in
 * force the API returns `risk_level: null`, so a station with a reading is
 * "Not evaluated" (neutral, never one of the four risk colours) and a
 * station without one is "No data" / "Not checked yet" (hollow pin). The
 * TEST robust z (`signal_robust_z`) is a statistic against the station's
 * own seasonal history, uncalibrated and never a class.
 */

/** Risk-class tokens (design): colour, text colour on that colour, rank. */
export const LV = Object.freeze({
  warning: { label: 'Warning', color: '#FF3B30', on: '#fff', rank: 0, meaning: 'Strong multi-signal anomaly (z ≥ 2.0).' },
  watch: { label: 'Watch', color: '#FF9F0A', on: '#1D1D1F', rank: 1, meaning: 'Multiple signals; risk rising.' },
  elevated: { label: 'Elevated', color: '#FFCC00', on: '#1D1D1F', rank: 2, meaning: 'Above baseline; one signal (z ≥ 1.5).' },
  normal: { label: 'Normal', color: '#8E8E93', on: '#fff', rank: 3, meaning: 'Within seasonal baseline (z < 1.5).' },
  // Not risk classes: what the station is when the backend gives none.
  unrated: { label: 'Not evaluated', color: '#636366', on: '#fff', rank: 4, meaning: 'Index reading present; no validated baseline or calibrated rule, so no risk class.' },
  none: { label: 'No data', color: '#FFFFFF', on: '#1D1D1F', rank: 6, meaning: 'No usable observation.', hollow: true },
  unchecked: { label: 'Not checked yet', color: '#FFFFFF', on: '#1D1D1F', rank: 5, meaning: 'The first scheduled check has not finished.', hollow: true },
})

/** Class meanings when the classes come from the TEST statistic, not a rule set. */
export const TEST_MEANING = Object.freeze({
  warning: 'Strong anomaly vs own seasonal history (z ≥ 3.0).',
  watch: 'Anomaly vs own seasonal history; keep watching (z ≥ 2.0).',
  elevated: 'Moderately above own seasonal history (z ≥ 1.5).',
  normal: 'Within own seasonal history (z < 2.0).',
})

/** True when no station carries a backend risk class but some carry a TEST level. */
export const testBased = (stations) => stations.some((s) => s.testClass) && !stations.some((s) => s.rated)

export const RISK_KEYS = Object.freeze(['warning', 'watch', 'elevated', 'normal'])

const isObject = (v) => v !== null && typeof v === 'object' && !Array.isArray(v)
const finite = (v) => typeof v === 'number' && Number.isFinite(v)

/** CSS for a class swatch: filled, or hollow white with a 2px #AEAEB2 ring. */
export function swatchStyle(key) {
  const lv = LV[key] ?? LV.none
  return lv.hollow
    ? { background: '#fff', boxShadow: 'inset 0 0 0 2px #AEAEB2' }
    : { background: lv.color }
}

/** "Bang Saen, Chonburi" -> { short: "Bang Saen", province: "Chonburi" } */
export function splitName(name) {
  const text = typeof name === 'string' ? name : ''
  const i = text.indexOf(',')
  if (i < 0) return { short: text, province: '' }
  return { short: text.slice(0, i).trim(), province: text.slice(i + 1).trim() }
}

/** `+1.82` / `−0.30`; `—` for a missing value. */
export function fmtZ(z) {
  if (!finite(z)) return '—'
  const s = Math.abs(z).toFixed(2)
  return `${z > 0 ? '+' : z < 0 ? '−' : ''}${s}`
}

export function fmtIndex(v, d = 3) {
  return finite(v) ? v.toFixed(d).replace('-', '−') : '—'
}

/** One station from a /risk-map feature. */
export function stationOf(feature) {
  const p = isObject(feature?.properties) ? feature.properties : {}
  const c = Array.isArray(feature?.geometry?.coordinates) ? feature.geometry.coordinates : []
  const { short, province } = splitName(p.name)
  const rated = RISK_KEYS.includes(p.risk_level) ? p.risk_level : null
  const status = typeof p.status === 'string' ? p.status : 'error'
  const hasReading = status === 'ok'
  // No backend risk class (TEST baseline): the station's TEST anomaly level
  // (own seasonal history, uncalibrated) is shown in the class slots --
  // normal / watch / high -> Normal / Watch / Warning -- and marked TEST.
  const lvl = typeof p.signal_anomaly_level === 'string' && p.signal_anomaly_reason == null ? p.signal_anomaly_level : null
  const testCls = !rated && hasReading ? ({ normal: 'normal', watch: 'watch', high: 'warning' })[lvl] ?? null : null
  const cls = rated ?? testCls ?? (hasReading ? 'unrated' : status === 'no_data_yet' ? 'unchecked' : 'none')
  const idx = isObject(p.index_values) ? p.index_values : {}
  return {
    id: String(p.site_id ?? p.name ?? ''),
    name: typeof p.name === 'string' ? p.name : '',
    short: short || String(p.site_id ?? ''),
    province,
    lat: finite(c[1]) ? c[1] : null,
    lng: finite(c[0]) ? c[0] : null,
    status,
    hasReading,
    cls,
    rated,
    testClass: testCls !== null,
    z: finite(p.signal_robust_z) ? p.signal_robust_z : null,
    zLevel: typeof p.signal_anomaly_level === 'string' ? p.signal_anomaly_level : null,
    ndci: finite(idx.ndci) ? idx.ndci : null,
    bda2: finite(idx['2bda']) ? idx['2bda'] : null,
    bda3: finite(idx['3bda']) ? idx['3bda'] : null,
    date: typeof p.actual_date === 'string' ? p.actual_date : null,
    fetchedAt: typeof p.fetched_at === 'string' ? p.fetched_at : null,
    stale: p.stale === true,
    triggeredRules: Array.isArray(p.triggered_rules) ? p.triggered_rules.filter((r) => typeof r === 'string' || isObject(r)) : [],
    confidence: typeof p.confidence_label === 'string' ? p.confidence_label : null,
    trueColorUrl: typeof p.true_color_image_url === 'string' ? p.true_color_image_url : null,
    ndciUrl: typeof p.ndci_heatmap_image_url === 'string' ? p.ndci_heatmap_image_url : null,
    reason: typeof p.error === 'string' ? p.error : null,
    disclaimer: typeof p.disclaimer === 'string' ? p.disclaimer : null,
  }
}

/** Severity order: risk class first, then by TEST z (high first), then name. */
export function sortStations(list) {
  return [...list].sort((a, b) => {
    const r = LV[a.cls].rank - LV[b.cls].rank
    if (r !== 0) return r
    const az = a.z ?? -Infinity
    const bz = b.z ?? -Infinity
    if (az !== bz) return bz - az
    return a.short.localeCompare(b.short)
  })
}

/** Stations of a /risk-map response, or null before it loads. */
export function stationsOf(riskMap) {
  if (!isObject(riskMap) || !Array.isArray(riskMap.features)) return null
  return sortStations(riskMap.features.filter(isObject).map(stationOf))
}

/** The class counts of the chips / summary cards: the design's five when
 * the backend classifies stations, else only what is present. */
export function countsOf(stations) {
  const any = stations.some((s) => s.rated || s.testClass)
  const keys = any ? ['warning', 'watch', 'elevated', 'normal', 'unrated', 'none', 'unchecked'] : ['unrated', 'none', 'unchecked']
  const always = new Set(any ? ['warning', 'watch', 'elevated', 'normal', 'none'] : [])
  return keys
    .map((key) => ({ key, label: LV[key].label, n: stations.filter((s) => s.cls === key).length, meaning: (testBased(stations) && TEST_MEANING[key]) || LV[key].meaning }))
    .filter((c) => c.n > 0 || always.has(c.key))
}

/** Headline and one-line list for the left card. */
export function headlineOf(stations) {
  const attention = stations.filter((s) => s.cls === 'warning' || s.cls === 'watch')
  const anyRated = stations.some((s) => s.rated || s.testClass)
  if (anyRated) {
    return {
      headline: attention.length
        ? `${attention.length} ${attention.length === 1 ? 'station requires' : 'stations require'} attention`
        : 'No stations require attention',
      subline: attention.length
        ? attention.map((s) => `${s.short} — ${LV[s.cls].label}`).join(' · ')
        : 'All stations are within baseline or slightly elevated.',
    }
  }
  const measured = stations.filter((s) => s.hasReading).length
  return {
    headline: `${measured} of ${stations.length} stations have an index reading`,
    subline: 'Risk is not evaluated: no validated baseline gives a risk class.',
  }
}
