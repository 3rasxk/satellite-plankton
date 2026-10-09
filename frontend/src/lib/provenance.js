/**
 * Where a displayed number came from (dashboard spec §5 `SourceChip`).
 *
 * Data source: the API response the number was read from -- this module
 * only restates its provenance: endpoint and query, field path, the value
 * exactly as returned (unrounded, so a judge can match it to the raw JSON),
 * unit, observation date, raster run, scene id and a link to the formula on
 * /methods. The "Open raw JSON" URL is built with `apiAssetUrl`, so it goes
 * through the same base (Vite proxy or absolute URL) as the app's own calls.
 *
 * Rules: nothing is invented. A row whose fact the response does not carry
 * is "—" (e.g. scene ID: a cell knows its acquisition date, not its scene).
 * Null/undefined query params are dropped from the URL rather than sent as
 * "null".
 *
 * Limitations: field-to-unit/formula metadata below is naming only (which
 * /methods anchor an index key belongs to, which unit a field is in); it
 * restates backend/src/schemas.py field docs and the `/methods`
 * `indices[].key`/`raster_band` pairs, and computes nothing.
 */
import { apiAssetUrl } from '../api/client.js'
import { NULL_TEXT, formatDateSpan } from './format.js'

/** Popover rows, in display order; each label is i18n `source.<id>`. */
export const SOURCE_ROW_IDS = Object.freeze([
  'endpoint', 'field', 'value', 'unit', 'observed_date', 'run_id', 'scene_id', 'formula',
])

/** Units written as words (translated via `unit.<name>`); any other unit
 * string is a symbol (°, m, ms, mg m⁻³, DN) and is shown as is. */
export const WORD_UNITS = Object.freeze(['dimensionless', 'count', 'fraction'])

// /methods index keys (MethodsIndex.key) by the name each response uses.
// The stored raster names its bands differently (MethodsIndex.raster_band).
const RASTER_INDEX_KEYS = Object.freeze({ ndci: 'ndci', bda2: '2bda', bda3: '3bda', b2_b3: 'b2_b3_ratio' })
const SITE_INDEX_KEYS = Object.freeze({ ndci: 'ndci', '2bda': '2bda', '3bda': '3bda', b2_b3_ratio: 'b2_b3_ratio' })

const DEGREES = '°'

const isObject = (v) => v !== null && typeof v === 'object'

/** `/path?a=1&b=2` with null/undefined/non-finite params dropped; insertion
 * order kept. Null for a missing endpoint. */
export function requestPath(endpoint, params) {
  if (typeof endpoint !== 'string' || endpoint === '') return null
  const query = new URLSearchParams()
  if (isObject(params)) {
    for (const [name, value] of Object.entries(params)) {
      if (value === null || value === undefined) continue
      if (typeof value === 'number' && !Number.isFinite(value)) continue
      query.append(name, String(value))
    }
  }
  const qs = query.toString()
  return qs ? `${endpoint}?${qs}` : endpoint
}

/** The value at a dotted path ("index_values.ndci"), own properties only. */
export function valueAtPath(obj, path) {
  if (typeof path !== 'string' || path === '') return undefined
  let node = obj
  for (const part of path.split('.')) {
    if (!isObject(node) || !Object.hasOwn(node, part)) return undefined
    node = node[part]
  }
  return node
}

const isKnown = (v) => v !== null && v !== undefined && !(typeof v === 'number' && !Number.isFinite(v)) && v !== ''

/** The API's value as text, unrounded. */
function rawText(value) {
  if (!isKnown(value)) return NULL_TEXT
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  try {
    return JSON.stringify(value)
  } catch {
    return NULL_TEXT
  }
}

function row(id, textValue, extra = {}) {
  return { id, labelKey: `source.${id}`, text: textValue, textKey: null, href: null, ...extra }
}

function unitRow(unit) {
  if (typeof unit !== 'string' || unit === '') return row('unit', NULL_TEXT)
  return row('unit', unit, { textKey: WORD_UNITS.includes(unit) ? `unit.${unit}` : null })
}

/**
 * The provenance of one displayed value.
 * @returns {{endpoint: string|null, field: string|null, url: string|null,
 *   rows: Array<{id, labelKey, text, textKey, href, value?}>}}
 *   `rows[].text` is display text ("—" when unknown); render `textKey`
 *   through t() when it is set; `href` is set on the formula row only.
 */
export function sourceRef(input) {
  const {
    endpoint, field, value, unit, observedDate, runId, sceneId, formulaKey, params,
  } = isObject(input) ? input : {}
  const path = requestPath(endpoint, params)
  const formula = typeof formulaKey === 'string' && formulaKey !== '' ? formulaKey : null
  return {
    endpoint: typeof endpoint === 'string' && endpoint !== '' ? endpoint : null,
    field: typeof field === 'string' && field !== '' ? field : null,
    url: path ? apiAssetUrl(path) : null,
    rows: [
      row('endpoint', path ? `GET ${path}` : NULL_TEXT),
      row('field', rawText(field)),
      row('value', rawText(value), { value: isKnown(value) ? value : null }),
      unitRow(unit),
      row('observed_date', rawText(observedDate)),
      row('run_id', rawText(runId)),
      row('scene_id', rawText(sceneId)),
      row('formula', formula ?? NULL_TEXT, { href: formula ? `/methods#${formula}` : null }),
    ],
  }
}

/** Unit and /methods anchor of a field, from its path. */
function fieldMeta(field, indexKeys) {
  if (typeof field !== 'string') return { unit: null, formula: null }
  if (field.startsWith('index_values.')) {
    const key = field.slice('index_values.'.length)
    return { unit: 'dimensionless', formula: Object.hasOwn(indexKeys, key) ? indexKeys[key] : null }
  }
  switch (field) {
    case 'anomaly.robust_z':
    case 'anomaly.median_ndci':
    case 'anomaly.mad':
    case 'signal_robust_z':
    case 'robust_z':
    case 'median_ndci':
    case 'mad':
      return { unit: 'dimensionless', formula: 'robust_z' }
    case 'anomaly.n_dates':
    case 'n_dates':
      return { unit: 'count', formula: 'robust_z' }
    case 'anomaly.level':
    case 'signal_anomaly_level':
    case 'anomaly_level':
      return { unit: null, formula: 'robust_z' }
    case 'lat':
    case 'lng':
    case 'query_lat':
    case 'query_lng':
    case 'cell_lat':
    case 'cell_lng':
    case 'pixel_centre_lat':
    case 'pixel_centre_lng':
      return { unit: DEGREES, formula: null }
    case 'scale_m':
      return { unit: 'm', formula: null }
    case 'date_ms':
      return { unit: 'ms', formula: null }
    case 'cloud_fraction':
    case 'coverage.measured_fraction':
    case 'latest_scene.cloud_fraction':
    case 'latest_scene.threshold_cloud_fraction':
      return { unit: 'fraction', formula: null }
    case 'cell_count':
    case 'scene_count':
    case 'coverage.measured_pixels':
    case 'coverage.polygon_pixels':
      return { unit: 'count', formula: null }
    default:
      return { unit: null, formula: null }
  }
}

/** A field of a `/raster-scan/pixel` response (one inspected cell). */
export function refForPixelField(pixel, field) {
  const p = isObject(pixel) ? pixel : {}
  const meta = fieldMeta(field, RASTER_INDEX_KEYS)
  return sourceRef({
    endpoint: '/raster-scan/pixel',
    field,
    value: valueAtPath(p, field),
    unit: meta.unit,
    observedDate: p.acquired_date,
    runId: p.run_id,
    sceneId: null,
    formulaKey: meta.formula,
    params: { lat: p.query_lat, lng: p.query_lng, run_id: p.run_id },
  })
}

/** A field of one `/risk-map` feature; `lat`/`lng` read its geometry. */
export function refForSiteField(feature, field) {
  const f = isObject(feature) ? feature : {}
  const props = isObject(f.properties) ? f.properties : {}
  const coords = isObject(f.geometry) && Array.isArray(f.geometry.coordinates) ? f.geometry.coordinates : []
  const prefix = `features[site_id=${rawText(props.site_id)}]`
  let value
  let fieldPath
  if (field === 'lat' || field === 'lng') {
    const i = field === 'lat' ? 1 : 0 // GeoJSON order is [lng, lat]
    value = coords[i]
    fieldPath = `${prefix}.geometry.coordinates[${i}]`
  } else {
    value = valueAtPath(props, field)
    fieldPath = `${prefix}.properties.${field}`
  }
  const meta = fieldMeta(field, SITE_INDEX_KEYS)
  return sourceRef({
    endpoint: '/risk-map',
    field: fieldPath,
    value,
    unit: meta.unit,
    observedDate: props.actual_date,
    runId: null,
    sceneId: null,
    formulaKey: meta.formula,
    params: null,
  })
}

/** A field of the `/raster-scan` response; the observation date is the
 * run's scene-date span (one raster mixes acquisitions). */
export function refForRasterField(raster, field) {
  const r = isObject(raster) ? raster : {}
  const meta = fieldMeta(field, RASTER_INDEX_KEYS)
  return sourceRef({
    endpoint: '/raster-scan',
    field,
    value: valueAtPath(r, field),
    unit: meta.unit,
    observedDate: formatDateSpan(r.oldest_scene_date, r.newest_scene_date),
    runId: r.run_id,
    sceneId: null,
    formulaKey: meta.formula,
    params: null,
  })
}
