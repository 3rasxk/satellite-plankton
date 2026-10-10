/**
 * CSV exports built client-side from JSON the page already fetched
 * (dashboard spec §4.5 "Exports"; no bulk cell download).
 *
 * Data source: the API responses, untouched. Values are written at full
 * precision exactly as returned (no rounding, ASCII "-" for negatives so the
 * file is machine-readable); unknown (null, undefined, NaN, ±Infinity) is an
 * EMPTY cell, never 0; a real 0 stays "0". Headers are the API field paths,
 * so every column can be traced back to backend/src/schemas.py. Each row
 * carries its own provenance: the request (`endpoint`, "GET /path?query"),
 * run/date columns, and the server `disclaimer` verbatim.
 *
 * Format: RFC 4180 -- comma separated, CRLF after every record (header
 * included), a field quoted when it contains a comma, quote, CR or LF, and
 * inner quotes doubled. `{bom: true}` prefixes a UTF-8 BOM (for spreadsheet
 * programs that otherwise misread UTF-8); the default is no BOM.
 *
 * Fixed column orders (documented here and pinned by tests/csv.test.js):
 *   sites      (GET /risk-map, one row per feature)        SITES_CSV_COLUMNS
 *   timeseries (GET /timeseries, one row per MODIS point)  TIMESERIES_CSV_COLUMNS
 *   pins       (GET /raster-scan/highlights, one per pin)  PINS_CSV_COLUMNS
 *              -- one column set for both modes; the anomaly columns are
 *              empty in 'ndci' mode and `visible_bands_dn.*` empty when the
 *              response has none
 *   cell       (GET /raster-scan/pixel, one row)           CELL_CSV_COLUMNS
 * No risk column exists: `risk_level` is always null while risk evaluation
 * is inactive, and `risk_tier` likewise.
 *
 * Limitations: list-valued fields (`unreadable_bands`) are joined with ";".
 */
import { requestPath, valueAtPath } from './provenance.js'

const BOM = '﻿'
const isObject = (v) => v !== null && typeof v === 'object'

function cellText(value) {
  if (value === null || value === undefined) return ''
  if (typeof value === 'number') return Number.isFinite(value) ? String(value) : ''
  if (typeof value === 'string') return value
  if (typeof value === 'boolean') return String(value)
  if (value instanceof Date) return Number.isFinite(value.getTime()) ? value.toISOString() : ''
  try {
    return JSON.stringify(value) ?? ''
  } catch {
    return ''
  }
}

function escapeCell(text) {
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}

function normaliseColumn(column) {
  if (typeof column === 'string') {
    return { header: column, get: (r) => (Object.hasOwn(r, column) ? r[column] : undefined) }
  }
  const header = String(column?.header ?? column?.key ?? '')
  if (typeof column?.get === 'function') return { header, get: column.get }
  const key = column?.key ?? header
  return { header, get: (r) => (Object.hasOwn(r, key) ? r[key] : undefined) }
}

/**
 * Rows to CSV text.
 * @param {Array<string|{header: string, key?: string, get?: (row) => *}>} columns
 *   a string is both the header and the row key
 * @param {Array<object>|null} rows
 * @param {{bom?: boolean}} [options]
 */
export function toCsv(columns, rows, options = {}) {
  const cols = (Array.isArray(columns) ? columns : []).map(normaliseColumn)
  const records = [cols.map((c) => escapeCell(c.header)).join(',')]
  for (const r of Array.isArray(rows) ? rows : []) {
    const rowObject = isObject(r) ? r : {}
    records.push(cols.map((c) => escapeCell(cellText(c.get(rowObject)))).join(','))
  }
  return `${options?.bom ? BOM : ''}${records.map((rec) => `${rec}\r\n`).join('')}`
}

// Build an exporter from [header, getter(context)] pairs; the header list is
// exported so the order is a documented, tested constant.
function exporter(spec) {
  return {
    columns: Object.freeze(spec.map(([header]) => header)),
    toColumns: () => spec.map(([header, get]) => ({ header, get })),
  }
}

const path = (p) => (ctx) => valueAtPath(ctx.item, p)

// ---------------------------------------------------------------- sites

const SITES = exporter([
  ['site_id', path('site_id')],
  ['name', path('name')],
  ['lat', (ctx) => ctx.coords[1]],
  ['lng', (ctx) => ctx.coords[0]],
  ['status', path('status')],
  ['stale', path('stale')],
  ['actual_date', path('actual_date')],
  ['cloud_fraction', path('cloud_fraction')],
  ['index_used', path('index_used')],
  ['index_values.ndci', path('index_values.ndci')],
  ['index_values.2bda', path('index_values.2bda')],
  ['index_values.3bda', path('index_values.3bda')],
  ['index_values.b2_b3_ratio', path('index_values.b2_b3_ratio')],
  ['signal_anomaly_level', path('signal_anomaly_level')],
  ['signal_robust_z', path('signal_robust_z')],
  ['signal_anomaly_reason', path('signal_anomaly_reason')],
  ['baseline.mode', (ctx) => valueAtPath(ctx.response, 'baseline.mode')],
  ['baseline.version', (ctx) => valueAtPath(ctx.response, 'baseline.version')],
  ['fetched_at', path('fetched_at')],
  ['error', path('error')],
  ['endpoint', () => `GET ${requestPath('/risk-map')}`],
  ['disclaimer', (ctx) => ctx.item.disclaimer ?? ctx.response.disclaimer],
])
export const SITES_CSV_COLUMNS = SITES.columns

/** `/risk-map` FeatureCollection -> one row per monitoring site. */
export function sitesCsv(riskMap, options) {
  const response = isObject(riskMap) ? riskMap : {}
  const features = Array.isArray(response.features) ? response.features : []
  const rows = features.map((f) => ({
    response,
    item: isObject(f?.properties) ? f.properties : {},
    coords: Array.isArray(f?.geometry?.coordinates) ? f.geometry.coordinates : [],
  }))
  return toCsv(SITES.toColumns(), rows, options)
}

// ----------------------------------------------------------- timeseries

const TIMESERIES = exporter([
  ['date', path('date')],
  ['chlor_a', path('chlor_a')],
  ['anomaly_z', path('anomaly_z')],
  ['reason', path('reason')],
  ['lat', (ctx) => ctx.response.lat],
  ['lng', (ctx) => ctx.response.lng],
  ['source', (ctx) => ctx.response.source],
  ['endpoint', (ctx) => `GET ${requestPath('/timeseries', { lat: ctx.response.lat, lng: ctx.response.lng })}`],
  ['disclaimer', (ctx) => ctx.response.disclaimer],
])
export const TIMESERIES_CSV_COLUMNS = TIMESERIES.columns

/** `/timeseries` (MODIS-Aqua chlor_a) -> one row per point, same numbers. */
export function timeseriesCsv(ts, options) {
  const response = isObject(ts) ? ts : {}
  const points = Array.isArray(response.points) ? response.points : []
  const rows = points.map((p) => ({ response, item: isObject(p) ? p : {} }))
  return toCsv(TIMESERIES.toColumns(), rows, options)
}

// ----------------------------------------------------------------- pins

const PINS = exporter([
  ['run_id', (ctx) => ctx.response.run_id],
  ['mode', (ctx) => ctx.response.mode],
  ['metric', (ctx) => ctx.response.metric],
  ['rank', path('rank')],
  ['metric_value', path('metric_value')],
  ['percentile', path('percentile')],
  ['cell_lat', path('cell_lat')],
  ['cell_lng', path('cell_lng')],
  ['pixel_centre_lat', path('pixel_centre_lat')],
  ['pixel_centre_lng', path('pixel_centre_lng')],
  ['index_values.ndci', path('index_values.ndci')],
  ['index_values.bda2', path('index_values.bda2')],
  ['index_values.bda3', path('index_values.bda3')],
  ['index_values.b2_b3', path('index_values.b2_b3')],
  ['acquired_date', path('acquired_date')],
  ['acquired_at', path('acquired_at')],
  ['date_ms', path('date_ms')],
  ['edge_of_no_data', path('edge_of_no_data')],
  ['robust_z', path('robust_z')],
  ['median_ndci', path('median_ndci')],
  ['mad', path('mad')],
  ['n_dates', path('n_dates')],
  ['anomaly_level', path('anomaly_level')],
  ['visible_bands_dn.red', path('visible_bands_dn.red')],
  ['visible_bands_dn.green', path('visible_bands_dn.green')],
  ['visible_bands_dn.blue', path('visible_bands_dn.blue')],
  ['baseline.version', (ctx) => valueAtPath(ctx.response, 'baseline.version')],
  ['ranking', (ctx) => ctx.response.ranking],
  ['cohort_size', (ctx) => ctx.response.cohort_size],
  ['min_separation_m', (ctx) => ctx.response.min_separation_m],
  ['endpoint', (ctx) => `GET ${requestPath('/raster-scan/highlights', {
    run_id: ctx.response.run_id,
    n: ctx.response.n_requested,
    min_separation_m: ctx.response.min_separation_m,
    mode: ctx.response.mode,
  })}`],
  ['disclaimer', (ctx) => ctx.response.disclaimer],
])
export const PINS_CSV_COLUMNS = PINS.columns

/** `/raster-scan/highlights` (either mode) -> one row per pin. */
export function pinsCsv(highlights, options) {
  const response = isObject(highlights) ? highlights : {}
  const pins = Array.isArray(response.pins) ? response.pins : []
  const rows = pins.map((p) => ({ response, item: isObject(p) ? p : {} }))
  return toCsv(PINS.toColumns(), rows, options)
}

/**
 * The same pins as a table: `columns` is PINS_CSV_COLUMNS and each row is
 * the raw cell values in that order, from the very getters `pinsCsv` uses
 * (so the on-screen table on /data cannot drift from the CSV). Unknown is
 * null; nothing is formatted or rounded here.
 */
export function pinsTable(highlights) {
  const response = isObject(highlights) ? highlights : {}
  const pins = Array.isArray(response.pins) ? response.pins : []
  const specs = PINS.toColumns()
  return {
    columns: PINS.columns,
    rows: pins.map((p) => {
      const ctx = { response, item: isObject(p) ? p : {} }
      return specs.map((c) => {
        const v = c.get(ctx)
        return v === undefined ? null : v
      })
    }),
  }
}

// ----------------------------------------------------------------- cell

const CELL = exporter([
  ['run_id', path('run_id')],
  ['date_used', path('date_used')],
  ['scale_m', path('scale_m')],
  ['state', path('state')],
  ['meaning', path('meaning')],
  ['query_lat', path('query_lat')],
  ['query_lng', path('query_lng')],
  ['cell_lat', path('cell_lat')],
  ['cell_lng', path('cell_lng')],
  ['pixel_centre_lat', path('pixel_centre_lat')],
  ['pixel_centre_lng', path('pixel_centre_lng')],
  ['pixel_row', path('pixel_row')],
  ['pixel_col', path('pixel_col')],
  ['index_values.ndci', path('index_values.ndci')],
  ['index_values.bda2', path('index_values.bda2')],
  ['index_values.bda3', path('index_values.bda3')],
  ['index_values.b2_b3', path('index_values.b2_b3')],
  ['unreadable_bands', (ctx) => (Array.isArray(ctx.item.unreadable_bands) ? ctx.item.unreadable_bands.join(';') : null)],
  ['acquired_date', path('acquired_date')],
  ['acquired_at', path('acquired_at')],
  ['date_ms', path('date_ms')],
  ['anomaly.robust_z', path('anomaly.robust_z')],
  ['anomaly.median_ndci', path('anomaly.median_ndci')],
  ['anomaly.mad', path('anomaly.mad')],
  ['anomaly.n_dates', path('anomaly.n_dates')],
  ['anomaly.level', path('anomaly.level')],
  ['anomaly.reason', path('anomaly.reason')],
  ['anomaly.season_key', path('anomaly.season_key')],
  ['anomaly.baseline_version', path('anomaly.baseline_version')],
  ['anomaly.visible_bands_dn.red', path('anomaly.visible_bands_dn.red')],
  ['anomaly.visible_bands_dn.green', path('anomaly.visible_bands_dn.green')],
  ['anomaly.visible_bands_dn.blue', path('anomaly.visible_bands_dn.blue')],
  ['endpoint', (ctx) => `GET ${requestPath('/raster-scan/pixel', {
    lat: ctx.item.query_lat, lng: ctx.item.query_lng, run_id: ctx.item.run_id,
  })}`],
  ['disclaimer', path('disclaimer')],
])
export const CELL_CSV_COLUMNS = CELL.columns

/** One `/raster-scan/pixel` response (the inspected cell) -> one row. */
export function cellCsv(pixel, options) {
  const rows = isObject(pixel) ? [{ item: pixel }] : []
  return toCsv(CELL.toColumns(), rows, options)
}
