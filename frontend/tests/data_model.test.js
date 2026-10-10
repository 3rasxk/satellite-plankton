/**
 * The Data & limits page (`/data`): its view model (src/lib/dataModel.js),
 * the limitations index (src/lib/limitationsMap.js) and the markup
 * (src/pages/DataPage.jsx, src/components/{RunTable,ApiReference,
 * LimitationsList}.jsx).
 *
 * Claims under test:
 *   - every `##` heading of ../LIMITATIONS.md is summarised by an entry of
 *     the limitations map, every key the map lists exists in TH and EN, and
 *     the TEST-baseline limits (test-baseline spec §8) are present;
 *   - the pins table has exactly the columns of the pins CSV, row for row;
 *   - the run table shows only what the API returns: the stale run is its
 *     id alone, unknown is "—" with a reason, a real 0 stays 0, and the page
 *     says no run-history endpoint exists;
 *   - each export builder yields its documented column order (sites CSV,
 *     GeoJSON verbatim, pins CSV, MODIS series CSV fetched on demand);
 *   - the API reference lists only real endpoints and real schema fields;
 *   - the reproducibility block reads versions from the build and /methods;
 *   - nothing on the page says "1 km" for MODIS, uses a risk colour, or
 *     hard-codes the MODIS grid size.
 *
 * Fixtures: tests/fixtures/{map_payloads.js,methods_payload.json} (live API,
 * 2026-10-10). Markup renders through a Vite SSR loader with no DOM, as in
 * tests/methods_model.test.js.
 */
import test, { before, after } from 'node:test'
import assert from 'node:assert/strict'
import { readFile, readdir } from 'node:fs/promises'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { createServer } from 'vite'
import react from '@vitejs/plugin-react'

import en from '../src/i18n/en.js'
import th from '../src/i18n/th.js'
import { missingKeys } from '../src/i18n/index.js'
import { formatValue } from '../src/lib/format.js'
import {
  PINS_CSV_COLUMNS, SITES_CSV_COLUMNS, TIMESERIES_CSV_COLUMNS, pinsCsv, sitesCsv,
} from '../src/lib/csv.js'
import {
  API_ENDPOINTS, DATA_PINS_N, RUN_COLUMNS, buildApiReference, buildExports, buildPinsTable, buildReproducibility,
  buildRunTable, buildSceneSummary, modisTargets, runModisExport,
} from '../src/lib/dataModel.js'
import {
  LIMITATIONS_FILE, LIMITATIONS_KEYS, LIMITATIONS_SECTIONS,
} from '../src/lib/limitationsMap.js'
import { HIGHLIGHTS_ANOMALY, HIGHLIGHTS_NDCI, RASTER } from './fixtures/map_payloads.js'

const FIXTURE = JSON.parse(await readFile(new URL('./fixtures/methods_payload.json', import.meta.url), 'utf8'))
const METHODS = FIXTURE.methods
const ROOT = new URL('../../', import.meta.url)

function deepFreeze(o) {
  if (o && typeof o === 'object') {
    Object.values(o).forEach(deepFreeze)
    Object.freeze(o)
  }
  return o
}

function flatten(obj, prefix = '', out = new Map()) {
  for (const [k, v] of Object.entries(obj)) {
    const key = prefix ? `${prefix}.${k}` : k
    if (v !== null && typeof v === 'object') flatten(v, key, out)
    else out.set(key, v)
  }
  return out
}

const EN = flatten(en)
const TH = flatten(th)
const ok = { loading: false, error: null }
const NBSP = '\u00a0'

const RISK_MAP = deepFreeze({
  disclaimer: RASTER.disclaimer,
  type: 'FeatureCollection',
  features: [
    {
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [100.88, 13.26] },
      properties: {
        disclaimer: RASTER.disclaimer, site_id: 'bangsaen', name: 'Bang Saen, Chonburi', status: 'ok', risk_level: null,
        signal_anomaly_level: 'normal', signal_robust_z: 1.02, signal_anomaly_reason: null, index_used: 'ndci',
        index_values: { ndci: 0, '2bda': 1.1, '3bda': 0.1, b2_b3_ratio: 0.9 }, cloud_fraction: 0, actual_date: '2026-09-29',
        fetched_at: '2026-10-10T14:25:49+00:00', stale: false, error: null,
      },
    },
    {
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [100.27, 13.42] },
      properties: {
        disclaimer: RASTER.disclaimer, site_id: 'thachin_mouth', name: 'Tha Chin River mouth, Samut Sakhon', status: 'no_imagery',
        risk_level: null, signal_anomaly_level: null, signal_robust_z: null, signal_anomaly_reason: 'no_imagery', index_used: null,
        index_values: null, cloud_fraction: null, actual_date: null, fetched_at: '2026-10-10T14:25:49+00:00', stale: false, error: null,
      },
    },
  ],
  baseline: { mode: 'test', valid: true, version: 'TEST-20261009-9fc9a022' },
})

const TIMESERIES = deepFreeze({
  disclaimer: RASTER.disclaimer,
  lat: 13.26,
  lng: 100.88,
  source: 'MODIS-Aqua chlor_a, 2002-present',
  points: [
    { date: '2002-09-05', chlor_a: 4.98, anomaly_z: -0.93, reason: null },
    { date: '2003-01-02', chlor_a: 0, anomaly_z: null, reason: 'climatology window had no other observations' },
  ],
})

// ------------------------------------------------------------ limitations

test('every ## heading of LIMITATIONS.md is summarised by an entry of the limitations map', async () => {
  const file = await readFile(new URL('LIMITATIONS.md', ROOT), 'utf8')
  const headings = [...file.matchAll(/^## (.+?)\s*$/gm)].map((m) => m[1])
  assert.ok(headings.length >= 7, 'the file has its sections')
  const mapped = LIMITATIONS_SECTIONS.filter((s) => s.source === LIMITATIONS_FILE).map((s) => s.heading)
  assert.deepEqual([...mapped].sort(), [...headings].sort(), 'map and file headings are the same set')
  for (const h of headings) {
    const s = LIMITATIONS_SECTIONS.find((x) => x.heading === h)
    assert.ok(s && s.pointKeys.length > 0, `heading "${h}" has a summary with points`)
  }
})

test('every key of the limitations map exists in Thai and English, non-empty', () => {
  assert.ok(LIMITATIONS_KEYS.length > 20)
  for (const key of LIMITATIONS_KEYS) {
    for (const [name, dict] of [['th', TH], ['en', EN]]) {
      assert.ok(dict.has(key), `${name} lacks ${key}`)
      assert.ok(String(dict.get(key)).trim().length > 0, `${name}:${key} is empty`)
    }
  }
  // no key of limits.<section>.* is left unlisted (a summary that never shows)
  const listed = new Set(LIMITATIONS_KEYS)
  for (const key of EN.keys()) {
    const m = /^limits\.(\w+)\.(title|p\d+)$/.exec(key)
    if (m) assert.ok(listed.has(key), `${key} is not listed in the map`)
  }
})

test('the TEST-baseline limits of test-baseline spec §8 are all stated', () => {
  const s = LIMITATIONS_SECTIONS.find((x) => x.id === 'test_baseline')
  assert.ok(s, 'a TEST-baseline section exists and summarises LIMITATIONS.md')
  const body = (dict) => s.pointKeys.map((k) => dict.get(k)).join('\n')
  const e = body(EN)
  assert.match(e, /own record for the same season/)
  assert.match(e, /provisional/)
  assert.match(e, /base rates/)
  assert.match(e, /sediment/)
  assert.match(e, /zero_mad/)
  assert.match(e, /insufficient_independent_dates/)
  assert.match(e, /low-signal/)
  assert.match(e, /developer-chosen/)
  assert.match(e, /Level B[^.]*no equivalent self-check/)
  assert.match(e, /word “risk” is not used/)
  const t = body(TH)
  for (const needle of ['zero_mad', 'insufficient_independent_dates', 'ตะกอน', 'ระดับ B', 'ผู้พัฒนากำหนดเอง']) {
    assert.ok(t.includes(needle), `Thai TEST-baseline limits mention ${needle}`)
  }
})

test('limitations prose states no number (values live on /methods and in the file)', () => {
  const digits = /\d/
  for (const s of LIMITATIONS_SECTIONS) {
    for (const key of s.pointKeys) {
      // B2/B3, B4/B5, B5/B4, 2BDA, ETOPO1 and years in a citation are names.
      const stripped = String(EN.get(key)).replace(/\b(Sentinel-2|Level-3|B\d|2BDA|ETOPO1|\d{4})\b/g, '')
      assert.doesNotMatch(stripped, digits, `en:${key}`)
    }
  }
})

// -------------------------------------------------------------------- pins

test('the pins table columns equal the pins CSV columns and its header row', () => {
  const m = buildPinsTable({ highlights: HIGHLIGHTS_ANOMALY, request: ok })
  assert.deepEqual([...m.columns], [...PINS_CSV_COLUMNS])
  const header = pinsCsv(HIGHLIGHTS_ANOMALY).split('\r\n')[0].split(',')
  assert.deepEqual(header, [...m.columns])
  assert.equal(m.rows.length, HIGHLIGHTS_ANOMALY.pins.length)
  for (const row of m.rows) assert.equal(row.cells.length, m.columns.length)
  // the same getters: the table cell equals the CSV cell for the same pin
  const record = pinsCsv(HIGHLIGHTS_ANOMALY).split('\r\n')[1]
  assert.ok(record.startsWith(`${HIGHLIGHTS_ANOMALY.run_id},${HIGHLIGHTS_ANOMALY.mode},${HIGHLIGHTS_ANOMALY.metric},1,`))
  const first = m.rows[0].cells
  assert.equal(first[m.columns.indexOf('rank')].raw, 1)
  assert.equal(first[m.columns.indexOf('metric_value')].raw, HIGHLIGHTS_ANOMALY.pins[0].metric_value)
  assert.equal(m.anomalyMode, true)
  assert.equal(m.disclaimer.text, HIGHLIGHTS_ANOMALY.disclaimer)
})

test('pins table: NDCI-mode response has the same columns, unknown cells are "—" with a reason, never 0', () => {
  const m = buildPinsTable({ highlights: HIGHLIGHTS_NDCI, request: ok })
  assert.deepEqual([...m.columns], [...PINS_CSV_COLUMNS])
  assert.equal(m.anomalyMode, false)
  const row = m.rows[0].cells
  const robustZ = row[m.columns.indexOf('robust_z')]
  assert.equal(robustZ.isNull, true)
  assert.equal(robustZ.text, '—')
  assert.notEqual(robustZ.text, '0')
  assert.equal(robustZ.reason, 'not_available')
  // a real zero stays a zero
  const zero = buildPinsTable({ highlights: { ...HIGHLIGHTS_NDCI, pins: [{ ...HIGHLIGHTS_NDCI.pins[0], percentile: 0 }] }, request: ok })
  assert.match(zero.rows[0].cells[zero.columns.indexOf('percentile')].text, /^0\.000$/)
})

test('pins table: loading, error and empty are distinct and none shows rows', () => {
  assert.equal(buildPinsTable({ highlights: null, request: { loading: true, error: null } }).state, 'loading')
  const err = buildPinsTable({ highlights: null, request: { loading: false, error: new Error('x') } })
  assert.equal(err.state, 'error')
  assert.equal(err.error.endpoint, '/raster-scan/highlights')
  const empty = buildPinsTable({ highlights: { ...HIGHLIGHTS_NDCI, pins: [], reason: 'no stored cells' }, request: ok })
  assert.equal(empty.state, 'empty')
  assert.equal(empty.csv, null)
  assert.equal(empty.serverReason, 'no stored cells')
})

test('pins CSV: the export builder yields the CSV with BOM, a run-named file and the documented columns', () => {
  const m = buildPinsTable({ highlights: HIGHLIGHTS_ANOMALY, request: ok })
  assert.equal(m.csv.filename, `highlight-pins-run-${HIGHLIGHTS_ANOMALY.run_id}.csv`)
  const content = m.csv.content()
  assert.ok(content.startsWith('﻿'))
  assert.deepEqual(content.slice(1).split('\r\n')[0].split(','), [...PINS_CSV_COLUMNS])
})

test('the page asks for the most pins the endpoint allows', () => {
  assert.equal(DATA_PINS_N, 10)
})

// --------------------------------------------------------------------- run

test('run table: the served run shows only API values, with null handling and sources', () => {
  const m = buildRunTable({ raster: RASTER, request: ok })
  assert.equal(m.state, 'ready')
  assert.deepEqual(m.columns.map((c) => c.id), ['run_id', 'status', 'date_used', 'scale_m', 'cell_count', 'scene_count',
    'oldest_scene_date', 'newest_scene_date', 'completed_at'])
  assert.equal(m.rows.length, 1)
  const c = m.rows[0].cells
  assert.equal(c.run_id.text, String(RASTER.run_id))
  assert.equal(c.status.text, RASTER.status)
  assert.equal(c.date_used.text, RASTER.date_used)
  assert.equal(c.scale_m.text, `${RASTER.scale_m}${NBSP}m`)
  assert.equal(c.oldest_scene_date.text, RASTER.oldest_scene_date)
  assert.match(c.completed_at.text, /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}Z$/)
  for (const col of RUN_COLUMNS) {
    assert.equal(c[col.id].source.field, col.field, `${col.id} source names its field`)
    assert.equal(c[col.id].source.endpoint, '/raster-scan')
  }
})

test('run table: no run-history endpoint is stated, in the model and in both languages', () => {
  const m = buildRunTable({ raster: RASTER, request: ok })
  assert.ok(m.notes.some((n) => n.key === 'data.run.no_history'))
  assert.match(EN.get('data.run.no_history'), /no run-history endpoint/)
  assert.match(TH.get('data.run.no_history'), /ประวัติรอบสแกน/)
})

test('run table: a stale run is its id only, every other cell "—", and a note says why', () => {
  const m = buildRunTable({ raster: { ...RASTER, stale_run_id: 9 }, request: ok })
  assert.equal(m.state, 'stale')
  assert.equal(m.rows.length, 2)
  const stale = m.rows[1]
  assert.equal(stale.role, 'stale')
  assert.equal(stale.cells.run_id.text, '9')
  for (const col of RUN_COLUMNS.filter((x) => x.id !== 'run_id')) {
    assert.equal(stale.cells[col.id].text, '—')
    assert.equal(stale.cells[col.id].isNull, true)
    assert.equal(stale.cells[col.id].reason, 'not_available')
  }
  const note = m.notes.find((n) => n.key === 'data.run.stale_note')
  assert.deepEqual(note.params, { run: '9' })
  assert.equal(note.tone, 'attention')
})

test('run table: null fields are "—" with a reason; a real 0 stays 0; no run is "empty", not zero rows of data', () => {
  const m = buildRunTable({ raster: { ...RASTER, cell_count: null, scene_count: 0, completed_at: null }, request: ok })
  const c = m.rows[0].cells
  assert.equal(c.cell_count.text, '—')
  assert.equal(c.cell_count.reason, 'not_available')
  assert.equal(c.scene_count.text, '0')
  assert.equal(c.completed_at.text, '—')
  const none = buildRunTable({ raster: { run_id: null, status: null, reason: 'no overlay rendered yet', stale_run_id: null }, request: ok })
  assert.equal(none.state, 'empty')
  assert.equal(none.rows.length, 0)
  assert.equal(none.serverReason, 'no overlay rendered yet')
  assert.ok(none.notes.some((n) => n.key === 'data.run.none'))
})

test('run table: loading and error', () => {
  assert.equal(buildRunTable({ raster: null, request: { loading: true, error: null } }).state, 'loading')
  const err = buildRunTable({ raster: null, request: { loading: false, error: new Error('down') } })
  assert.equal(err.state, 'error')
  assert.equal(err.error.endpoint, '/raster-scan')
})

test('scene summary reuses the shared latest-scene and poll blocks and lists the per-day cells', () => {
  const s = buildSceneSummary({ raster: RASTER, request: ok, methods: METHODS, nowMs: Date.parse(RASTER.poll.last_poll_ok_at) + 10 * 60000 })
  assert.equal(s.state, 'ready')
  assert.equal(s.latest.line.key, 'overview.scene.used')
  assert.equal(s.poll.health, 'ok')
  assert.equal(s.lastUsed.value.text, RASTER.last_used_scene_date)
  assert.equal(s.sceneDates.length, RASTER.scene_dates.length)
  assert.equal(s.sceneDates[0].cells.raw, RASTER.scene_dates[0].cells)
  assert.match(s.sceneDates[0].share.text, /%$/)
  const none = buildSceneSummary({ raster: { ...RASTER, scene_dates: null }, request: ok, methods: METHODS, nowMs: 0 })
  assert.equal(none.sceneDates.length, 0)
})

// ----------------------------------------------------------------- exports

test('sites CSV and GeoJSON exports: documented columns, GeoJSON is the response verbatim', () => {
  const x = buildExports({ riskMap: RISK_MAP, pins: null, riskMapRequest: ok })
  assert.equal(x.state, 'ready')
  const csv = x.sitesCsv.content()
  assert.ok(csv.startsWith('﻿'))
  assert.deepEqual(csv.slice(1).split('\r\n')[0].split(','), [...SITES_CSV_COLUMNS])
  assert.equal(csv, `﻿${sitesCsv(RISK_MAP)}`)
  assert.deepEqual(JSON.parse(x.sitesGeojson.content()), JSON.parse(JSON.stringify(RISK_MAP)))
  assert.equal(x.pinsCsv, null)
})

test('exports with no /risk-map: no site export is offered, the state says why', () => {
  const loading = buildExports({ riskMap: null, pins: null, riskMapRequest: { loading: true, error: null } })
  assert.equal(loading.state, 'loading')
  assert.equal(loading.sitesCsv, null)
  assert.equal(loading.modis.length, 0)
  const err = buildExports({ riskMap: null, pins: null, riskMapRequest: { loading: false, error: new Error('x') } })
  assert.equal(err.state, 'error')
})

test('MODIS targets: one per site with coordinates, [lng, lat] order read correctly', () => {
  const t = modisTargets(RISK_MAP)
  assert.deepEqual(t.map((x) => x.siteId), ['bangsaen', 'thachin_mouth'])
  assert.equal(t[0].lat, 13.26)
  assert.equal(t[0].lng, 100.88)
  assert.equal(t[0].filename, 'modis-chlor_a-bangsaen.csv')
  assert.equal(t[0].endpoint, '/timeseries?lat=13.26&lng=100.88')
  const bad = modisTargets({ features: [{ properties: { site_id: 'x' }, geometry: { coordinates: [null, 13] } }] })
  assert.equal(bad.length, 0)
})

test('MODIS export: fetched on demand with the long timeout, written in the documented column order', async () => {
  const calls = []
  const downloads = []
  const [target] = modisTargets(RISK_MAP)
  const result = await runModisExport({
    target,
    fetcher: async (lat, lng, opts) => { calls.push({ lat, lng, opts }); return TIMESERIES },
    download: (name, content, type) => { downloads.push({ name, content, type }); return true },
  })
  assert.deepEqual(result, { ok: true, filename: 'modis-chlor_a-bangsaen.csv' })
  assert.equal(calls.length, 1)
  assert.deepEqual([calls[0].lat, calls[0].lng], [13.26, 100.88])
  assert.ok(calls[0].opts.timeout >= 60000, 'a cold archive read outlasts the 30 s default')
  const lines = downloads[0].content.slice(1).split('\r\n')
  assert.deepEqual(lines[0].split(','), [...TIMESERIES_CSV_COLUMNS])
  // the real 0 stays 0 and the unknown z is an empty cell, never 0
  assert.match(lines[2], /^2003-01-02,0,,climatology window had no other observations,/)
  assert.equal(downloads[0].type, 'text/csv;charset=utf-8')
})

test('MODIS export never throws: a failed fetch, an odd payload and a blocked download are reported', async () => {
  const [target] = modisTargets(RISK_MAP)
  const download = () => true
  assert.equal((await runModisExport({ target, fetcher: async () => { throw new Error('504') }, download })).ok, false)
  assert.deepEqual(await runModisExport({ target, fetcher: async () => ({}), download }), { ok: false, error: 'no_points' })
  assert.deepEqual(await runModisExport({ target, fetcher: async () => TIMESERIES, download: () => false }), { ok: false, error: 'download_blocked' })
  assert.deepEqual(await runModisExport({}), { ok: false, error: 'invalid_request' })
})

// ----------------------------------------------------------- API reference

async function backendSource(dir) {
  const base = new URL(dir, ROOT)
  const names = (await readdir(base)).filter((n) => n.endsWith('.py'))
  const parts = await Promise.all(names.map((n) => readFile(new URL(n, base), 'utf8')))
  return parts.join('\n')
}

test('API reference: every endpoint is a real route and every listed field is a schema field', async () => {
  const routers = await backendSource('backend/src/routers/')
  const schemas = await readFile(new URL('backend/src/schemas.py', ROOT), 'utf8')
  const rows = buildApiReference({ raster: RASTER })
  assert.equal(rows.length, API_ENDPOINTS.length)
  for (const e of API_ENDPOINTS) {
    assert.ok(routers.includes(`"${e.path}"`), `route ${e.path} exists in backend/src/routers`)
    if (e.schema) assert.match(schemas, new RegExp(`class ${e.schema}\\b`), `${e.schema} exists`)
    for (const f of e.fields) {
      assert.match(schemas, new RegExp(`\\b${f}\\b\\s*:`), `${e.path}: field ${f} exists in schemas.py`)
    }
  }
})

test('API reference covers every endpoint the interface calls', async () => {
  const client = await readFile(new URL('../src/api/client.js', import.meta.url), 'utf8')
  const used = new Set([...client.matchAll(/client\.get\('([^']+)'/g)].map((m) => m[1]))
  const listed = new Set(API_ENDPOINTS.map((e) => e.path))
  // these client functions exist but no page of the dashboard calls them
  const unused = new Set(['/detect', '/api/alerts', '/api/satellite/pin-preview', '/'])
  for (const path of used) {
    if (unused.has(path)) continue
    assert.ok(listed.has(path), `${path} is called by the app but not in the API reference`)
  }
})

test('API reference rows: links go through the API base, the run id is carried, and no endpoint is a risk-level source', () => {
  const rows = buildApiReference({ raster: RASTER })
  const pixel = rows.find((r) => r.id === 'pixel')
  assert.match(pixel.example, new RegExp(`run_id=${RASTER.run_id}`))
  assert.match(pixel.example, /lat=/)
  assert.match(pixel.example, /lng=/)
  const hl = rows.find((r) => r.id === 'highlights')
  assert.match(hl.example, /n=10/)
  for (const r of rows) {
    assert.ok(r.href.endsWith(r.example), `${r.id} href ends with its example`)
    assert.ok(r.usedBy.length > 0)
    for (const p of r.usedBy) assert.ok(p.to.startsWith('/'))
    assert.ok(EN.has(r.labelKey) && TH.has(r.labelKey))
    for (const p of r.usedBy) assert.ok(EN.has(p.labelKey) && TH.has(p.labelKey))
  }
  const noRun = buildApiReference({ raster: null }).find((r) => r.id === 'pixel')
  assert.doesNotMatch(noRun.example, /run_id/)
})

// --------------------------------------------------------- reproducibility

test('reproducibility: build constants, API version, baseline version and gates, each with its source', () => {
  const m = buildReproducibility({ methods: METHODS, request: ok, build: { appVersion: '0.0.0', gitSha: 'abc1234' } })
  assert.equal(m.state, 'ready')
  const by = Object.fromEntries(m.items.map((i) => [i.id, i]))
  assert.equal(by.app_version.text, '0.0.0')
  assert.equal(by.git_sha.text, 'abc1234')
  assert.equal(by.api_version.text, METHODS.api_version)
  assert.equal(by.api_version.source.field, 'api_version')
  assert.equal(by.baseline_version.text, METHODS.baseline.version)
  assert.equal(by.signature.text, METHODS.baseline.preprocessing_signature)
  assert.equal(by.risk_gate.label, 'gates.risk_evaluation_active')
  assert.equal(by.risk_gate.text, String(METHODS.gates.risk_evaluation_active))
  assert.equal(by.anomaly_gate.text, String(METHODS.gates.signal_anomaly_active))
  assert.equal(by.modis_grid.text, formatValue(METHODS.modis.grid_resolution_m, { kind: 'count', unit: 'm' }).text)
  assert.equal(m.isDevBuild, false)
})

test('reproducibility: without /methods the server rows are "—", the build rows stay, and a dev build is flagged', () => {
  const m = buildReproducibility({ methods: null, request: { loading: false, error: new Error('x') }, build: { appVersion: 'dev', gitSha: 'dev' } })
  assert.equal(m.state, 'error')
  const by = Object.fromEntries(m.items.map((i) => [i.id, i]))
  assert.equal(by.api_version.isNull, true)
  assert.equal(by.api_version.text, '—')
  assert.equal(by.baseline_version.isNull, true)
  assert.equal(by.app_version.text, 'dev')
  assert.equal(m.isDevBuild, true)
  const noTest = buildReproducibility({ methods: { ...METHODS, baseline: { mode: 'off', valid: false } }, request: ok })
  const v = noTest.items.find((i) => i.id === 'baseline_version')
  assert.equal(v.isNull, true, 'no TEST baseline: no version is invented')
})

// ------------------------------------------------------------------ markup

let server
let DataView
let StaticLangProvider
before(async () => {
  server = await createServer({
    configFile: false,
    plugins: [react()],
    cacheDir: 'node_modules/.vite-data-tests',
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true, watch: null, hmr: false, ws: false },
  })
  DataView = (await server.ssrLoadModule('/src/pages/DataPage.jsx')).DataView
  ;({ StaticLangProvider } = await server.ssrLoadModule('/src/i18n/LangContext.jsx'))
})

after(async () => server?.close())

function models(over = {}) {
  const pins = buildPinsTable({ highlights: HIGHLIGHTS_ANOMALY, request: ok })
  return {
    run: buildRunTable({ raster: { ...RASTER, stale_run_id: 9 }, request: ok }),
    scene: buildSceneSummary({ raster: RASTER, request: ok, methods: METHODS, nowMs: Date.parse(RASTER.poll.last_poll_ok_at) + 10 * 60000 }),
    pins,
    exports: buildExports({ riskMap: RISK_MAP, pins, riskMapRequest: ok }),
    api: buildApiReference({ raster: RASTER }),
    repro: buildReproducibility({ methods: METHODS, request: ok, build: { appVersion: '0.0.0', gitSha: 'abc1234' } }),
    resolutionText: formatValue(METHODS.modis.grid_resolution_m, { kind: 'count', unit: 'm' }).text,
    ...over,
  }
}

function render(m, lang = 'en') {
  return renderToStaticMarkup(createElement(MemoryRouter, { initialEntries: ['/data'] },
    createElement(StaticLangProvider, { lang }, createElement(DataView, { models: m, onPrint: () => {}, onRetry: {} }))))
}

const visible = (html) => html.replace(/<[^>]+>/g, ' ').replace(/&#x27;/g, "'").replace(/&quot;/g, '"')
  .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&').replace(/\s+/g, ' ')

test('the page renders all seven sections, in both languages, with no missing i18n key', () => {
  missingKeys.clear()
  for (const lang of ['en', 'th']) {
    const html = render(models(), lang)
    for (const id of ['run', 'scene', 'pins', 'exports', 'api', 'limits', 'repro']) {
      assert.match(html, new RegExp(`<section[^>]*id="${id}"`), `${lang}: section ${id}`)
    }
    assert.match(html, /<h1[^>]*>/)
    assert.equal((html.match(/<h1/g) ?? []).length, 1)
  }
  assert.deepEqual([...missingKeys], [], 'no key was missing')
})

test('markup: pins table headers are the CSV columns; every limitations section renders; the stale run is labelled', () => {
  const html = render(models())
  const pinsTable = html.slice(html.indexOf('pw-data-pins'))
  const headers = [...pinsTable.slice(0, pinsTable.indexOf('</thead>')).matchAll(/<code class="pw-mono">([^<]+)<\/code>/g)].map((m) => m[1])
  assert.deepEqual(headers, [...PINS_CSV_COLUMNS])
  for (const s of LIMITATIONS_SECTIONS) assert.match(html, new RegExp(`id="limits-${s.id}"`))
  assert.match(visible(html), /Newest attempt, not served/)
  assert.match(visible(html), /no run-history endpoint/)
  assert.match(visible(html), /Cell/i)
})

test('markup: the server disclaimer inside the pins table is verbatim and marked English; MODIS grid comes from /methods', () => {
  const html = render(models(), 'th')
  assert.ok(html.includes('lang="en"'))
  assert.ok(visible(html).includes(HIGHLIGHTS_ANOMALY.disclaimer.slice(0, 80)))
  assert.match(visible(html), /4,638\s*m/)
  const noRes = visible(render(models({ resolutionText: null })))
  assert.doesNotMatch(noRes, /4638/)
})

test('markup: states degrade per block; one failed block does not blank the others', () => {
  const err = new Error('nope')
  const html = render(models({
    pins: buildPinsTable({ highlights: null, request: { loading: false, error: err } }),
    run: buildRunTable({ raster: null, request: { loading: true, error: null } }),
  }))
  assert.match(html, /aria-busy="true"/)
  assert.match(visible(html), /This block could not be loaded/)
  assert.match(html, /id="limits-truth_boundary"/, 'limitations still render')
  assert.match(html, /id="api"/)
})

test('markup: the stylesheet colours nothing red or green and the page never says 1 km for MODIS', async () => {
  const src = await Promise.all([
    '../src/pages/DataPage.jsx', '../src/lib/dataModel.js', '../src/lib/limitationsMap.js',
    '../src/components/RunTable.jsx', '../src/components/ApiReference.jsx', '../src/components/LimitationsList.jsx',
  ].map((p) => readFile(new URL(p, import.meta.url), 'utf8')))
  for (const text of src) {
    assert.doesNotMatch(text, /--risk-/)
    assert.doesNotMatch(text, /\b1\s*km\b/i)
    assert.doesNotMatch(text, /4638/, 'the MODIS grid size is read from /methods, not written here')
  }
  const css = await readFile(new URL('../src/styles/dashboard.css', import.meta.url), 'utf8')
  const dataCss = css.slice(css.indexOf('Data & limits page (/data)'))
  assert.doesNotMatch(dataCss, /--risk-|#(?:f00|0f0|ff0000|00ff00)\b|\b(?:red|green)\b/i)
  const dict = [...EN.entries()].filter(([k]) => k.startsWith('data.') || k.startsWith('limits.'))
  for (const [k, v] of dict) assert.doesNotMatch(String(v), /\b1\s*km\b/i, k)
  for (const [k, v] of [...TH.entries()].filter(([k]) => k.startsWith('data.') || k.startsWith('limits.'))) {
    assert.doesNotMatch(String(v), /1\s*(km|กม|กิโลเมตร)/, k)
  }
})
