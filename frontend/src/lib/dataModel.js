/**
 * dataModel: everything the Data & limits page (`/data`) shows, as data --
 * formatted values, source refs, i18n keys and export builders -- so the
 * page is a thin renderer and every rule runs under `node --test`
 * (dashboard spec §4.5, §5, §10; test-baseline spec §8).
 *
 * Data source (read-only; only what the API returns):
 *   - `GET /raster-scan` (RasterScanResponse): the served run, the stale run
 *     id, the latest-scene assessment, the newer-scene poll, the per-day
 *     scene breakdown;
 *   - `GET /raster-scan/highlights` (RasterHighlightsResponse): the pins;
 *   - `GET /risk-map` (RiskMapResponse): the monitoring sites for the
 *     exports;
 *   - `GET /methods` (MethodsResponse): API version, baseline version,
 *     gates, MODIS grid resolution;
 *   - build constants (src/lib/buildInfo.js): app version and commit.
 *
 * Rules kept here:
 *   - there is no run-history endpoint, so the run table can only ever hold
 *     the served run and, if the API names one, the stale run's id; every
 *     other cell of the stale run is "—" with the reason, never invented;
 *   - unknown is "—" with a reason; a real 0 stays 0; no value is computed
 *     (counts of rows and percentages of API-provided counts only);
 *   - the pins table has exactly the columns of the pins CSV (`pinsTable`
 *     in src/lib/csv.js uses the same getters), so screen and file agree;
 *   - MODIS resolution is read from `/methods` (never written here);
 *   - no risk wording: a pin is a ranking inside one scan, or a TEST-baseline
 *     anomaly, whatever the response says in `mode`.
 *
 * Limitations: pure functions of their inputs; no fetching except the
 * injected fetcher of `runModisExport`.
 */
import { apiAssetUrl } from '../api/client.js'
import { appVersion as BUILD_VERSION, gitSha as BUILD_SHA } from './buildInfo.js'
import { PINS_CSV_COLUMNS, pinsCsv, pinsTable, timeseriesCsv } from './csv.js'
import { NULL_TEXT, formatValue } from './format.js'
import { latestSceneBlock, pollBlock } from './overviewModel.js'
import { refForRasterField, requestPath, sourceRef } from './provenance.js'
import { TIMESERIES_TIMEOUT_MS, sitesExports } from './sitesModel.js'

export { PINS_CSV_COLUMNS }

/** The page's sections, in order (anchors and table of contents). */
export const DATA_SECTIONS = Object.freeze([
  { id: 'run', titleKey: 'data.section.run' },
  { id: 'scene', titleKey: 'data.section.scene' },
  { id: 'pins', titleKey: 'data.section.pins' },
  { id: 'exports', titleKey: 'data.section.exports' },
  { id: 'api', titleKey: 'data.section.api' },
  { id: 'limits', titleKey: 'data.section.limits' },
  { id: 'repro', titleKey: 'data.section.repro' },
])

/** Pins requested for the table and CSV (the endpoint allows 3-10). */
export const DATA_PINS_N = 10

const isObject = (v) => v !== null && typeof v === 'object' && !Array.isArray(v)
const finite = (v) => typeof v === 'number' && Number.isFinite(v)
const hasValue = (v) => v !== null && v !== undefined
const text = (v) => (typeof v === 'string' && v.trim() !== '' ? v : null)
const msg = (key, params = {}) => ({ key, params })

/** One displayed value: the API value, its spec and formatValue's result. */
function val(raw, spec) {
  const r = formatValue(raw, spec)
  return { raw: hasValue(raw) ? raw : null, spec, text: r.text, isNull: r.isNull, reason: r.reason }
}

/** `{loading, error}` of one request. */
function requestOf(requests, name) {
  const r = isObject(requests) && isObject(requests[name]) ? requests[name] : {}
  return { loading: r.loading === true, error: hasValue(r.error) ? r.error : null }
}

function missingState(payload, req) {
  if (isObject(payload)) return null
  return req.loading || !req.error ? 'loading' : 'error'
}

// ---------------------------------------------------------------- run table

/**
 * The run table's columns, in display order. `field` is the
 * RasterScanResponse field shown (named in the cell's source popover).
 */
export const RUN_COLUMNS = Object.freeze([
  { id: 'run_id', field: 'run_id', spec: { kind: 'count' }, plain: true },
  { id: 'status', field: 'status', spec: { kind: 'text' }, plain: true },
  { id: 'date_used', field: 'date_used', spec: { kind: 'date' } },
  { id: 'scale_m', field: 'scale_m', spec: { kind: 'count', unit: 'm' } },
  { id: 'cell_count', field: 'cell_count', spec: { kind: 'count' } },
  { id: 'scene_count', field: 'scene_count', spec: { kind: 'count' } },
  { id: 'oldest_scene_date', field: 'oldest_scene_date', spec: { kind: 'date' } },
  { id: 'newest_scene_date', field: 'newest_scene_date', spec: { kind: 'date' } },
  { id: 'completed_at', field: 'completed_at', spec: { kind: 'datetime-utc' } },
].map((c) => Object.freeze({ ...c, labelKey: `data.run.col.${c.id}` })))

function runCell(column, raw) {
  // Ids and status codes are shown as the API sent them, never number-formatted.
  if (column.plain) {
    const t = typeof raw === 'string' && raw !== '' ? raw : (finite(raw) ? String(raw) : null)
    return { raw: t, spec: column.spec, text: t ?? NULL_TEXT, isNull: t === null, reason: t === null ? 'not_available' : null }
  }
  return val(raw, { ...column.spec, reason: 'not_available' })
}

/**
 * The run provenance table (spec §4.5 item 1).
 * @returns {{state: 'loading'|'error'|'empty'|'stale'|'ready', columns, rows,
 *   notes, serverReason, error, staleRunId}}
 *   rows: `{key, role: 'served'|'stale', cells: {[columnId]: cell}}`; a cell
 *   is `{raw, spec, text, isNull, reason, source}`.
 */
export function buildRunTable({ raster, request } = {}) {
  const req = requestOf({ raster: request }, 'raster')
  const base = {
    columns: RUN_COLUMNS, rows: [], notes: [msg('data.run.no_history')], serverReason: null, error: null, staleRunId: null,
  }
  const missing = missingState(raster, req)
  if (missing) {
    return { ...base, state: missing, error: missing === 'error' ? { endpoint: '/raster-scan', error: req.error } : null }
  }
  const served = hasValue(raster.run_id)
  const staleId = hasValue(raster.stale_run_id) ? raster.stale_run_id : null
  const rows = []
  if (served) {
    const cells = {}
    for (const c of RUN_COLUMNS) {
      cells[c.id] = { ...runCell(c, raster[c.field]), source: refForRasterField(raster, c.field) }
    }
    rows.push({ key: `served-${raster.run_id}`, role: 'served', cells })
  }
  if (staleId !== null) {
    const cells = {}
    for (const c of RUN_COLUMNS) {
      const isId = c.id === 'run_id'
      const cell = isId
        ? runCell(c, staleId)
        : { raw: null, spec: c.spec, text: NULL_TEXT, isNull: true, reason: 'not_available' }
      cells[c.id] = { ...cell, source: isId ? refForRasterField(raster, 'stale_run_id') : null }
    }
    rows.push({ key: `stale-${staleId}`, role: 'stale', cells })
  }
  const notes = [...base.notes]
  if (staleId !== null) notes.push({ ...msg('data.run.stale_note', { run: String(staleId) }), tone: 'attention' })
  if (!served) notes.push(msg('data.run.none'))
  const state = !served ? 'empty' : (staleId !== null ? 'stale' : 'ready')
  return { ...base, state, rows, notes, serverReason: text(raster.reason), staleRunId: staleId }
}

// ------------------------------------------------------------ scene summary

/**
 * Latest-scene assessment, newer-scene poll and the per-day breakdown of the
 * served raster. The first two are the same blocks the Overview and the map
 * rail show (src/lib/overviewModel.js), so the sentences cannot disagree.
 * `nowMs` is injected for tests.
 */
export function buildSceneSummary({ raster, request, methods, nowMs } = {}) {
  const req = requestOf({ raster: request }, 'raster')
  const latest = latestSceneBlock(raster, req, methods)
  const poll = pollBlock(raster, req, nowMs)
  const days = isObject(raster) && Array.isArray(raster.scene_dates) ? raster.scene_dates.filter(isObject) : []
  const sceneDates = days.map((d, i) => ({
    key: `${d.date}-${i}`,
    date: val(d.date, { kind: 'date' }),
    cells: val(d.cells, { kind: 'count' }),
    share: val(d.share, { kind: 'percent', decimals: 1 }),
  }))
  const lastUsed = isObject(raster)
    ? {
      value: val(raster.last_used_scene_date, { kind: 'date', reason: 'not_available' }),
      source: refForRasterField(raster, 'last_used_scene_date'),
    }
    : null
  return {
    state: latest.state,
    latest,
    poll,
    lastUsed,
    sceneDates,
    sceneDatesSource: isObject(raster) ? refForRasterField(raster, 'scene_dates') : null,
  }
}

// --------------------------------------------------------------- pins table

// Display specs by column header; any column not listed is shown as text.
const PIN_SPECS = Object.freeze({
  rank: { kind: 'count' },
  metric_value: { kind: 'index', decimals: 4 },
  percentile: { kind: 'index', decimals: 3 },
  cell_lat: { kind: 'coord', decimals: 5 },
  cell_lng: { kind: 'coord', decimals: 5 },
  pixel_centre_lat: { kind: 'coord', decimals: 5 },
  pixel_centre_lng: { kind: 'coord', decimals: 5 },
  'index_values.ndci': { kind: 'index', decimals: 4 },
  'index_values.bda2': { kind: 'index', decimals: 4 },
  'index_values.bda3': { kind: 'index', decimals: 4 },
  'index_values.b2_b3': { kind: 'index', decimals: 4 },
  acquired_date: { kind: 'date' },
  date_ms: { kind: 'ms', decimals: 0 },
  robust_z: { kind: 'z', decimals: 2 },
  median_ndci: { kind: 'index', decimals: 4 },
  mad: { kind: 'index', decimals: 4 },
  n_dates: { kind: 'count' },
  'visible_bands_dn.red': { kind: 'count' },
  'visible_bands_dn.green': { kind: 'count' },
  'visible_bands_dn.blue': { kind: 'count' },
  cohort_size: { kind: 'count' },
  min_separation_m: { kind: 'count', unit: 'm' },
})

/** Columns that carry the server's text, shown verbatim and marked English. */
export const PIN_SERVER_TEXT_COLUMNS = Object.freeze(['ranking', 'disclaimer'])

function pinCell(header, raw) {
  const spec = Object.hasOwn(PIN_SPECS, header) ? PIN_SPECS[header] : { kind: 'text' }
  if (spec.kind === 'text') {
    const t = typeof raw === 'string' && raw !== '' ? raw : (typeof raw === 'boolean' || finite(raw) ? String(raw) : null)
    return { raw: t, spec, text: t ?? NULL_TEXT, isNull: t === null, reason: t === null ? 'not_available' : null }
  }
  return val(raw, spec)
}

/** True when the response's pins are TEST-baseline anomaly pins. */
function isAnomalyMode(h) {
  return isObject(h) && h.mode === 'anomaly'
}

export const PINS_CSV_FILENAME_PREFIX = 'highlight-pins-run-'

/**
 * The pins table of `/raster-scan/highlights` and its CSV.
 * @returns {{state, columns: string[], rows: Array<{key, rank, cells: Array>}>,
 *   csv: {filename, content}|null, anomalyMode, notes, error, source, disclaimer}}
 *   `columns` equals PINS_CSV_COLUMNS, always.
 */
export function buildPinsTable({ highlights, request } = {}) {
  const req = requestOf({ highlights: request }, 'highlights')
  const base = {
    columns: PINS_CSV_COLUMNS, rows: [], csv: null, anomalyMode: false, notes: [], error: null, source: null, disclaimer: null,
  }
  const missing = missingState(highlights, req)
  if (missing) {
    return { ...base, state: missing, error: missing === 'error' ? { endpoint: '/raster-scan/highlights', error: req.error } : null }
  }
  const table = pinsTable(highlights)
  const anomalyMode = isAnomalyMode(highlights)
  const rows = table.rows.map((values, i) => ({
    key: `pin-${i}`,
    cells: values.map((raw, j) => pinCell(table.columns[j], raw)),
  }))
  const notes = [msg(anomalyMode ? 'data.pins.note_anomaly' : 'data.pins.note_ndci')]
  const runId = hasValue(highlights.run_id) ? String(highlights.run_id) : 'unknown'
  const disclaimer = text(highlights.disclaimer)
    ? { text: highlights.disclaimer, endpoint: '/raster-scan/highlights' }
    : null
  const source = sourceRef({
    endpoint: '/raster-scan/highlights',
    field: 'pins',
    value: null,
    unit: null,
    runId: highlights.run_id,
    params: { run_id: highlights.run_id, n: highlights.n_requested, min_separation_m: highlights.min_separation_m, mode: highlights.mode },
  })
  const csv = {
    filename: `${PINS_CSV_FILENAME_PREFIX}${runId}.csv`,
    type: 'text/csv;charset=utf-8',
    content: () => pinsCsv(highlights, { bom: true }),
  }
  return {
    ...base,
    state: rows.length === 0 ? 'empty' : 'ready',
    rows,
    csv: rows.length === 0 ? null : csv,
    anomalyMode,
    notes,
    source,
    disclaimer,
    serverReason: text(highlights.reason),
  }
}

// ------------------------------------------------------------------ exports

export const MODIS_CSV_PREFIX = 'modis-chlor_a-'

/** The sites the MODIS series can be downloaded for: one per `/risk-map`
 * feature that has coordinates. */
export function modisTargets(riskMap) {
  const features = isObject(riskMap) && Array.isArray(riskMap.features) ? riskMap.features : []
  const out = []
  for (const f of features) {
    const props = isObject(f?.properties) ? f.properties : {}
    const coords = Array.isArray(f?.geometry?.coordinates) ? f.geometry.coordinates : []
    const lng = coords[0]
    const lat = coords[1]
    if (!finite(lat) || !finite(lng)) continue
    const id = text(props.site_id) ?? `${lat}_${lng}`
    out.push({
      siteId: id,
      name: text(props.name) ?? id,
      lat,
      lng,
      filename: `${MODIS_CSV_PREFIX}${id}.csv`,
      endpoint: requestPath('/timeseries', { lat, lng }),
    })
  }
  return out
}

/**
 * Fetch one site's MODIS series on demand and turn it into a download.
 * `fetcher(lat, lng, {timeout})` is `getTimeseries`; `download(filename,
 * content, type)` is `downloadText`. Never throws.
 * @returns {Promise<{ok: true, filename}|{ok: false, error}>}
 */
export async function runModisExport({ target, fetcher, download }) {
  if (!isObject(target) || typeof fetcher !== 'function' || typeof download !== 'function') {
    return { ok: false, error: 'invalid_request' }
  }
  try {
    const series = await fetcher(target.lat, target.lng, { timeout: TIMESERIES_TIMEOUT_MS })
    if (!isObject(series) || !Array.isArray(series.points)) return { ok: false, error: 'no_points' }
    const started = download(target.filename, timeseriesCsv(series, { bom: true }), 'text/csv;charset=utf-8')
    return started === false ? { ok: false, error: 'download_blocked' } : { ok: true, filename: target.filename }
  } catch (error) {
    return { ok: false, error }
  }
}

/**
 * The export buttons: sites CSV / GeoJSON (from `/risk-map` already on the
 * page), pins CSV (from the pins already on the page), MODIS series CSV per
 * site (fetched on click). The cell CSV lives in the map inspector (no bulk
 * cell download exists).
 */
export function buildExports({ riskMap, pins, riskMapRequest } = {}) {
  const sites = sitesExports(riskMap)
  const targets = modisTargets(riskMap)
  const riskReq = requestOf({ riskMap: riskMapRequest }, 'riskMap')
  return {
    state: isObject(riskMap) ? 'ready' : missingState(riskMap, riskReq),
    sitesCsv: sites ? sites.csv : null,
    sitesGeojson: sites ? sites.geojson : null,
    pinsCsv: pins && pins.csv ? pins.csv : null,
    modis: targets,
  }
}

// ------------------------------------------------------------ API reference

/** Page ids -> nav route, for the "used by" column. */
const PAGES = Object.freeze({
  overview: '/',
  map: '/map',
  sites: '/sites',
  site: '/sites',
  methods: '/methods',
  data: '/data',
})

/**
 * The endpoints the dashboard uses. `schema` is the class in
 * backend/src/schemas.py; `fields` the response fields the UI reads (each is
 * checked against that file by tests/data_model.test.js). `example` is a
 * query a reader can open; the coordinates are an arbitrary point inside the
 * study area, not a monitoring site.
 */
export const API_ENDPOINTS = Object.freeze([
  {
    id: 'raster_scan',
    path: '/raster-scan',
    schema: 'RasterScanResponse',
    usedBy: ['overview', 'map', 'data'],
    fields: [
      'run_id', 'status', 'date_used', 'scale_m', 'cell_count', 'scene_count', 'oldest_scene_date', 'newest_scene_date',
      'scene_dates', 'completed_at', 'coverage', 'bounds', 'legend', 'overlay_url', 'true_color_url', 'stale_run_id',
      'reason', 'latest_scene', 'last_used_scene_date', 'poll',
    ],
  },
  { id: 'overlay', path: '/raster-scan/overlay.png', schema: null, usedBy: ['overview', 'map'], fields: ['overlay_url'], image: true },
  { id: 'true_color', path: '/raster-scan/true-color.png', schema: null, usedBy: ['map'], fields: ['true_color_url'], image: true },
  {
    id: 'pixel',
    path: '/raster-scan/pixel',
    schema: 'RasterPixelResponse',
    usedBy: ['map'],
    params: { lat: 13.3, lng: 100.2 },
    fields: [
      'state', 'meaning', 'run_id', 'date_used', 'scale_m', 'query_lat', 'query_lng', 'cell_lat', 'cell_lng',
      'pixel_centre_lat', 'pixel_centre_lng', 'index_values', 'unreadable_bands', 'acquired_date', 'anomaly',
    ],
  },
  {
    id: 'highlights',
    path: '/raster-scan/highlights',
    schema: 'RasterHighlightsResponse',
    usedBy: ['overview', 'map', 'methods', 'data'],
    params: { n: DATA_PINS_N },
    fields: ['run_id', 'mode', 'metric', 'ranking', 'n_requested', 'min_separation_m', 'cohort_size', 'pins', 'baseline'],
  },
  {
    id: 'risk_map',
    path: '/risk-map',
    schema: 'RiskMapResponse',
    usedBy: ['overview', 'sites', 'site', 'data'],
    fields: [
      'features', 'baseline', 'site_id', 'name', 'status', 'index_used', 'index_values', 'cloud_fraction', 'actual_date',
      'signal_anomaly_level', 'signal_robust_z', 'signal_anomaly_reason', 'stale', 'fetched_at', 'error',
      'true_color_image_url', 'ndci_heatmap_image_url',
    ],
  },
  {
    id: 'site_image',
    path: '/risk-map/{site_id}/image',
    example: '/risk-map/bangsaen/image?image_type=true_color',
    schema: null,
    usedBy: ['site'],
    fields: ['true_color_image_url', 'ndci_heatmap_image_url'],
    image: true,
  },
  {
    id: 'timeseries',
    path: '/timeseries',
    schema: 'TimeseriesResponse',
    usedBy: ['site', 'data'],
    params: { lat: 13.3, lng: 100.2 },
    fields: ['lat', 'lng', 'source', 'points', 'date', 'chlor_a', 'anomaly_z', 'reason'],
  },
  {
    id: 'summary',
    path: '/summary',
    schema: 'SummaryResponse',
    usedBy: ['overview'],
    fields: ['total_sites', 'risk_level_counts', 'stale_site_count', 'oldest_fetched_at', 'newest_fetched_at', 'baseline'],
  },
  {
    id: 'methods',
    path: '/methods',
    schema: 'MethodsResponse',
    usedBy: ['methods', 'sites', 'data', 'overview'],
    fields: [
      'api_version', 'indices', 'sentinel2', 'modis', 'gates', 'latest_scene_policy', 'season_rule', 'season_windows',
      'baseline', 'quality_screens', 'references',
    ],
  },
].map((e) => Object.freeze({ params: null, image: false, example: null, ...e })))

/**
 * Rows of the API reference table. `example` carries the run id when the
 * served run is known, so the link opens what the page is showing.
 */
export function buildApiReference({ raster } = {}) {
  const runId = isObject(raster) && hasValue(raster.run_id) ? raster.run_id : null
  return API_ENDPOINTS.map((e) => {
    let params = e.params
    if (runId !== null && (e.id === 'pixel' || e.id === 'highlights')) params = { run_id: runId, ...(params ?? {}) }
    const example = e.example ?? requestPath(e.path, params)
    return {
      id: e.id,
      path: e.path,
      labelKey: `data.api.ep.${e.id}`,
      example,
      href: apiAssetUrl(example),
      schema: e.schema,
      fields: e.fields,
      image: e.image,
      usedBy: e.usedBy.map((p) => ({ id: p, to: PAGES[p], labelKey: `data.api.page.${p}` })),
    }
  })
}

// ---------------------------------------------------------- reproducibility

/**
 * The reproducibility block: build constants and `/methods` fields. `build`
 * is injectable for tests.
 */
export function buildReproducibility({ methods, request, build } = {}) {
  const b = isObject(build) ? build : { appVersion: BUILD_VERSION, gitSha: BUILD_SHA }
  const req = requestOf({ methods: request }, 'methods')
  const missing = missingState(methods, req)
  const m = isObject(methods) ? methods : {}
  const baseline = isObject(m.baseline) ? m.baseline : {}
  const gates = isObject(m.gates) ? m.gates : {}
  const modis = isObject(m.modis) ? m.modis : {}
  const ref = (field, value, unit = null) => sourceRef({ endpoint: '/methods', field, value, unit })
  const code = (id, labelKey, raw, field) => {
    const v = text(raw)
    return { id, labelKey, text: v ?? NULL_TEXT, isNull: v === null, source: field ? ref(field, raw) : null }
  }
  // Gate rows are labelled with the API field path itself (an identifier,
  // never translated).
  const gate = (id, raw, field) => ({
    id,
    labelKey: null,
    label: field,
    text: typeof raw === 'boolean' ? String(raw) : NULL_TEXT,
    isNull: typeof raw !== 'boolean',
    source: ref(field, raw),
  })
  const items = [
    { ...code('app_version', 'data.repro.app_version', b.appVersion, null), build: true },
    { ...code('git_sha', 'data.repro.git_sha', b.gitSha, null), build: true },
    code('api_version', 'data.repro.api_version', m.api_version, 'api_version'),
    code('baseline_version', 'data.repro.baseline_version', baseline.version, 'baseline.version'),
    code('baseline_mode', 'data.repro.baseline_mode', baseline.mode, 'baseline.mode'),
    code('signature', 'data.repro.signature', baseline.preprocessing_signature, 'baseline.preprocessing_signature'),
    gate('risk_gate', gates.risk_evaluation_active, 'gates.risk_evaluation_active'),
    gate('anomaly_gate', gates.signal_anomaly_active, 'gates.signal_anomaly_active'),
    {
      id: 'modis_grid',
      labelKey: 'data.repro.modis_grid',
      ...val(modis.grid_resolution_m, { kind: 'count', unit: 'm', reason: 'not_available' }),
      source: ref('modis.grid_resolution_m', modis.grid_resolution_m, 'm'),
    },
  ]
  return {
    // Build constants are always known; the /methods rows may be missing.
    state: missing ?? 'ready',
    items,
    error: missing === 'error' ? { endpoint: '/methods', error: req.error } : null,
    isDevBuild: b.gitSha === 'dev',
  }
}
