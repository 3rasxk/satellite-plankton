/**
 * The Monitoring-sites pages (`/sites`, `/sites/:siteId`): their view model
 * (src/lib/sitesModel.js) and their markup.
 *
 * Claims under test:
 *   - sorting is stable and puts unknown values last in both directions;
 *   - every site status (incl. `no_data_yet`, `error`, an unknown string)
 *     gets a row with the closed-vocabulary chips and "—" + its own reason,
 *     never 0; a measured 0 stays 0;
 *   - the CSV export has the documented column order (csv.js) and the
 *     GeoJSON export equals the API response;
 *   - an anomaly chip appears only with a valid TEST baseline and a
 *     non-null level, and always says "(TEST)";
 *   - the MODIS table rows equal the API points; its resolution is the
 *     `/methods` value (4638 m), never "1 km"; a /timeseries failure or
 *     timeout degrades that block only;
 *   - no risk colour/wording, every model key exists in TH and EN.
 *
 * Fixtures are trimmed from the live API (backend with BASELINE_MODE=test,
 * 2026-10-10). Markup renders through a Vite SSR loader with no DOM, as in
 * tests/overview.test.js.
 */
import test, { before, after } from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { createServer } from 'vite'
import react from '@vitejs/plugin-react'

import en from '../src/i18n/en.js'
import th from '../src/i18n/th.js'
import { createT, missingKeys } from '../src/i18n/index.js'
import { SITES_CSV_COLUMNS, TIMESERIES_CSV_COLUMNS } from '../src/lib/csv.js'
import { SITE_STATUSES } from '../src/lib/statusChip.js'
import {
  SITE_COLUMNS, SITE_INDEX_FIELDS, TIMESERIES_TIMEOUT_MS,
  buildSitesModel, buildSiteRow, buildSiteDetailModel, buildModisModel,
  sortRows, nextSort, ariaSort, siteBaseline, anomalyCell, sitesGeoJson, sitesExports,
  findSite, modisRows, modisChartData, columnSource, isTimeout,
} from '../src/lib/sitesModel.js'

const NBSP = ' '
const DISCLAIMER = 'Satellite index values describe water colour at pixel resolution. Small or scattered blooms may not be visible. TEST baseline mode: …'

function deepFreeze(o) {
  if (o && typeof o === 'object') {
    Object.values(o).forEach(deepFreeze)
    Object.freeze(o)
  }
  return o
}

function site(id, name, lng, lat, over = {}) {
  return {
    type: 'Feature',
    geometry: { type: 'Point', coordinates: [lng, lat] },
    properties: {
      disclaimer: DISCLAIMER,
      site_id: id,
      name,
      site_type: 'monitoring_grid',
      risk_level: null,
      triggered_rules: [],
      confidence_label: 'indicative, rule-based -- not a validated forecast',
      status: 'ok',
      detected: null,
      spatial_anomaly_z: null,
      signal_anomaly_level: 'normal',
      signal_robust_z: 1.020230629103153,
      signal_anomaly_reason: null,
      index_used: 'ndci',
      index_values: { ndci: 0.07746194641245618, '2bda': 1.1679322519244035, '3bda': 0.1356341106597835, b2_b3_ratio: 0.9113519076247312 },
      cloud_fraction: 0.0,
      actual_date: '2026-09-29',
      true_color_image_url: `/risk-map/${id}/image?image_type=true_color`,
      ndci_heatmap_image_url: `/risk-map/${id}/image?image_type=ndci_heatmap`,
      fetched_at: '2026-10-10T14:25:49.083057+00:00',
      stale: false,
      error: null,
      ...over,
    },
  }
}

const NO_READING = {
  signal_anomaly_level: null, signal_robust_z: null, index_values: null, cloud_fraction: null, actual_date: null,
  true_color_image_url: null, ndci_heatmap_image_url: null,
}

const BASELINE = {
  mode: 'test', valid: true, kind: 'test', version: 'TEST-20261009-9fc9a022',
  built_at: '2026-10-09T01:09:04+00:00', history_start: '2017-12-13', history_end: '2026-10-07',
  season_rule: 'calendar-month window, target month +/- 1 (cyclic)',
  min_independent_dates: 35, median_independent_dates: 42,
  min_season_dates_by_location: { bangsaen: 43, siracha: 42, thachin_mouth: 36, chaophraya_mouth: 44, chaam: 35, bangpakong_mouth: 44, pattaya: 38 },
  preprocessing_signature: '9fc9a022c04817ec', base_rates: null, reason: null,
}

const RISK_MAP = deepFreeze({
  disclaimer: DISCLAIMER,
  type: 'FeatureCollection',
  features: [
    site('bangsaen', 'Bang Saen, Chonburi', 100.88, 13.26),
    site('siracha', 'Si Racha, Chonburi', 100.88, 13.16, { ...NO_READING, status: 'no_imagery', signal_anomaly_reason: 'no_imagery' }),
    site('thachin_mouth', 'Tha Chin River mouth, Samut Sakhon', 100.27, 13.42, {
      signal_robust_z: -1.1510428880124746, actual_date: '2026-10-07',
      index_values: { ndci: -0.03536536450230729, '2bda': 0.9316852471314662, '3bda': -0.04219029048633189, b2_b3_ratio: 0.8103300355522804 },
    }),
    site('chaophraya_mouth', 'Chao Phraya River mouth, Samut Prakan', 100.58, 13.4, {
      signal_anomaly_level: 'watch', signal_robust_z: 2.4, actual_date: '2026-10-07', stale: true, cloud_fraction: 0.12,
      index_values: { ndci: 0, '2bda': 0.8586974489555749, '3bda': -0.07156540828245968, b2_b3_ratio: 0.6687643957188049 },
    }),
    site('chaam', 'Cha-am, Phetchaburi', 99.98, 12.8, { ...NO_READING, status: 'no_data_yet', fetched_at: null, signal_anomaly_reason: 'no_cached_reading_yet' }),
    site('bangpakong_mouth', 'Bang Pakong River mouth, Chachoengsao', 101.0, 13.45, {
      ...NO_READING, status: 'error', error: 'Earth Engine request failed: quota exceeded', signal_anomaly_reason: 'not_assessed_against_active_baseline',
    }),
    site('pattaya', 'Pattaya, Chonburi', 100.85, 12.93, {
      signal_anomaly_level: null, signal_robust_z: null, signal_anomaly_reason: 'insufficient_independent_dates', actual_date: '2026-10-02',
    }),
  ],
  baseline: BASELINE,
})

const RISK_MAP_OFF = deepFreeze({
  ...RISK_MAP,
  baseline: null,
  features: RISK_MAP.features.map((f) => ({
    ...f,
    properties: { ...f.properties, signal_anomaly_level: null, signal_robust_z: null, signal_anomaly_reason: null },
  })),
})

const METHODS = deepFreeze({
  modis: {
    collection: 'NASA/OCEANDATA/MODIS-Aqua/L3SMI', bands: ['chlor_a', 'sst'], grid_resolution_m: 4638,
    record_start: '2002-07-04',
    note: 'Level-3 mapped product sampled on its ~4.6 km grid (the instrument\'s ~1 km figure is before Level-3 binning).',
  },
})

const TIMESERIES = deepFreeze({
  disclaimer: DISCLAIMER,
  lat: 13.26,
  lng: 100.88,
  source: 'MODIS-Aqua chlor_a, 2002-present (data-pipeline get_modis_chlorophyll_history)',
  points: [
    { date: '2002-09-05', chlor_a: 4.985896587371826, anomaly_z: -0.9374189526329668, reason: null, cloud_fraction: null, actual_date: null },
    { date: '2002-09-07', chlor_a: 28.245512008666992, anomaly_z: 0.504552253082922, reason: null, cloud_fraction: null, actual_date: null },
    { date: '2002-09-30', chlor_a: 11.180045127868652, anomaly_z: -0.016183868086313807, reason: null, cloud_fraction: null, actual_date: null },
    { date: '2003-01-02', chlor_a: 0, anomaly_z: null, reason: 'climatology window had no other observations', cloud_fraction: null, actual_date: null },
  ],
})

const ok = { loading: false, error: null }
const T = { en: createT('en'), th: createT('th') }

function flatten(obj, prefix = '', out = new Map()) {
  for (const [k, v] of Object.entries(obj)) {
    const key = prefix ? `${prefix}.${k}` : k
    if (v !== null && typeof v === 'object') flatten(v, key, out)
    else out.set(key, v)
  }
  return out
}
const TH = flatten(th)
const EN = flatten(en)

/** Every `{key}` / `labelKey` / `titleKey` / ... string reachable in a model. */
function modelKeys(node, out = new Set()) {
  if (Array.isArray(node)) node.forEach((n) => modelKeys(n, out))
  else if (node && typeof node === 'object') {
    for (const [k, v] of Object.entries(node)) {
      if ((k === 'key' && typeof v === 'string' && /^[a-z_]+\.[a-z0-9_.]+$/.test(v)) || (/Key$/.test(k) && typeof v === 'string')) out.add(v)
      else if (typeof v !== 'function') modelKeys(v, out)
    }
  }
  return out
}

// ------------------------------------------------------------------ sorting

test('sortRows: stable, unknown last in both directions', () => {
  const rows = [
    { id: 'a', sort: { v: 2 } }, { id: 'b', sort: { v: null } }, { id: 'c', sort: { v: 1 } },
    { id: 'd', sort: { v: 2 } }, { id: 'e', sort: { v: null } }, { id: 'f', sort: {} },
  ]
  assert.deepEqual(sortRows(rows, 'v', 'asc').map((r) => r.id), ['c', 'a', 'd', 'b', 'e', 'f'])
  assert.deepEqual(sortRows(rows, 'v', 'desc').map((r) => r.id), ['a', 'd', 'c', 'b', 'e', 'f'])
  assert.deepEqual(rows.map((r) => r.id), ['a', 'b', 'c', 'd', 'e', 'f'], 'input not mutated')
  // Strings compare deterministically; equal keys keep the input order.
  const s = [{ id: 1, sort: { n: 'b' } }, { id: 2, sort: { n: 'a' } }, { id: 3, sort: { n: 'b' } }]
  assert.deepEqual(sortRows(s, 'n', 'asc').map((r) => r.id), [2, 1, 3])
  assert.deepEqual(sortRows(s, 'n', 'desc').map((r) => r.id), [1, 3, 2])
  assert.deepEqual(sortRows(null, 'x'), [])
})

test('sortRows over the real rows: dates, indices and z with nulls last', () => {
  const m = buildSitesModel({ riskMap: RISK_MAP, request: ok })
  const by = (col, dir) => sortRows(m.rows, col, dir).map((r) => r.id)
  assert.deepEqual(by('actual_date', 'desc'),
    ['thachin_mouth', 'chaophraya_mouth', 'pattaya', 'bangsaen', 'siracha', 'chaam', 'bangpakong_mouth'])
  assert.deepEqual(by('actual_date', 'asc'),
    ['bangsaen', 'pattaya', 'thachin_mouth', 'chaophraya_mouth', 'siracha', 'chaam', 'bangpakong_mouth'])
  // A measured 0 sorts as 0, not as unknown.
  assert.deepEqual(by('ndci', 'asc').slice(0, 2), ['thachin_mouth', 'chaophraya_mouth'])
  assert.deepEqual(by('ndci', 'asc').slice(-3), ['siracha', 'chaam', 'bangpakong_mouth'])
  // Anomaly sorts by z only where a chip is shown (pattaya has a reason, not a z).
  assert.deepEqual(by('anomaly', 'desc'), ['chaophraya_mouth', 'bangsaen', 'thachin_mouth', 'siracha', 'chaam', 'bangpakong_mouth', 'pattaya'])
  // Status order is the API's list order (ok first); never alphabetical by label.
  assert.deepEqual(by('status', 'asc').slice(-3), ['siracha', 'bangpakong_mouth', 'chaam'])
  assert.deepEqual(by('name', 'asc')[0], 'bangpakong_mouth')
})

test('nextSort / ariaSort: toggle on the same column, ascending on a new one', () => {
  assert.deepEqual(nextSort({ column: 'name', direction: 'asc' }, 'name'), { column: 'name', direction: 'desc' })
  assert.deepEqual(nextSort({ column: 'name', direction: 'desc' }, 'name'), { column: 'name', direction: 'asc' })
  assert.deepEqual(nextSort({ column: 'name', direction: 'desc' }, 'ndci'), { column: 'ndci', direction: 'asc' })
  assert.equal(ariaSort({ column: 'ndci', direction: 'desc' }, 'ndci'), 'descending')
  assert.equal(ariaSort({ column: 'ndci', direction: 'asc' }, 'ndci'), 'ascending')
  assert.equal(ariaSort({ column: 'ndci', direction: 'asc' }, 'name'), 'none')
})

test('buildSitesModel: no (or an unknown) sort keeps the API order', () => {
  const apiOrder = RISK_MAP.features.map((f) => f.properties.site_id)
  const none = buildSitesModel({ riskMap: RISK_MAP, request: ok })
  assert.equal(none.sort, null)
  assert.deepEqual(none.rows.map((r) => r.id), apiOrder)
  const m = buildSitesModel({ riskMap: RISK_MAP, request: ok, sort: { column: 'risk_level', direction: 'asc' } })
  assert.equal(m.sort, null)
  assert.deepEqual(m.rows.map((r) => r.id), apiOrder)
  const off = buildSitesModel({ riskMap: RISK_MAP_OFF, request: ok, sort: { column: 'anomaly', direction: 'desc' } })
  assert.equal(off.sort, null, 'no anomaly column without a baseline')
  const sorted = buildSitesModel({ riskMap: RISK_MAP, request: ok, sort: { column: 'ndci', direction: 'desc' } })
  assert.deepEqual(sorted.sort, { column: 'ndci', direction: 'desc' })
  assert.equal(sorted.rows[0].id, 'bangsaen')
  assert.deepEqual(nextSort(null, 'ndci'), { column: 'ndci', direction: 'asc' })
  assert.equal(ariaSort(null, 'ndci'), 'none')
})

// ------------------------------------------------------------------- rows

test('rows for every site status: chips, "—" with the site\'s own reason, never 0', () => {
  const m = buildSitesModel({ riskMap: RISK_MAP, request: ok })
  const row = (id) => m.rows.find((r) => r.id === id)

  const okRow = row('bangsaen')
  assert.deepEqual(okRow.chips.map((c) => c.key), ['measured', 'not_evaluated'])
  assert.equal(okRow.cells.ndci.text, '0.0775')
  assert.equal(okRow.cells.cloud_fraction.text, `0.0${NBSP}%`, 'a measured 0 cloud stays 0')
  assert.equal(okRow.cells.lat.text, '13.26°')
  assert.equal(okRow.cells.actual_date.text, '2026-09-29')
  assert.equal(okRow.cells.fetched_at.text, '2026-10-10 14:25Z')
  assert.equal(okRow.href, '/sites/bangsaen')

  const zero = row('chaophraya_mouth')
  assert.equal(zero.cells.ndci.text, '0.0000')
  assert.equal(zero.cells.ndci.isNull, false)
  assert.deepEqual(zero.chips.map((c) => c.key), ['measured', 'not_evaluated', 'stale'])
  assert.equal(zero.stale, true)

  const noImg = row('siracha')
  assert.deepEqual(noImg.chips.map((c) => c.key), ['no_usable_data'])
  for (const f of SITE_INDEX_FIELDS) {
    assert.equal(noImg.cells[f.key].text, '—')
    assert.equal(noImg.cells[f.key].reason, 'no_imagery')
  }
  assert.equal(noImg.cells.actual_date.reason, 'no_imagery')
  assert.equal(noImg.cells.cloud_fraction.text, '—')

  const notYet = row('chaam')
  assert.deepEqual(notYet.chips.map((c) => c.key), ['not_checked_yet'])
  assert.equal(notYet.cells.ndci.reason, 'no_data_yet')
  assert.equal(notYet.cells.fetched_at.reason, 'no_data_yet')

  const err = row('bangpakong_mouth')
  assert.deepEqual(err.chips.map((c) => c.key), ['no_usable_data'])
  assert.equal(err.nullReason, 'error')
  assert.equal(err.nullReasonText, 'Earth Engine request failed: quota exceeded', 'server error text verbatim')

  const unknown = buildSiteRow(site('x', 'X', 100, 13, { ...NO_READING, status: 'something_new' }), siteBaseline(RISK_MAP))
  assert.deepEqual(unknown.chips.map((c) => c.key), ['no_usable_data'], 'an unknown status never reads as measured')
  assert.equal(unknown.cells.ndci.reason, 'something_new', 'shown verbatim as an API code')

  for (const r of m.rows) {
    for (const cell of Object.values(r.cells)) {
      if (cell.raw === null) assert.equal(cell.text, '—', `${r.id}: null shown as ${cell.text}`)
    }
  }
})

test('every documented site status has a row model', () => {
  const baseline = siteBaseline(RISK_MAP)
  for (const status of SITE_STATUSES) {
    const over = status === 'ok' ? {} : { ...NO_READING, status }
    const r = buildSiteRow(site(`s_${status}`, status, 100, 13, over), baseline)
    assert.ok(r.chips.length >= 1, status)
    assert.equal(r.status, status)
    if (status !== 'ok') assert.equal(r.cells.ndci.reason, status)
  }
})

test('state: loading, error, empty, stale; notes count readings and stale rows', () => {
  assert.equal(buildSitesModel({ riskMap: null, request: { loading: true } }).state, 'loading')
  const e = buildSitesModel({ riskMap: null, request: { loading: false, error: new Error('x') } })
  assert.equal(e.state, 'error')
  assert.equal(e.error.endpoint, '/risk-map')
  assert.equal(buildSitesModel({ riskMap: { ...RISK_MAP, features: [] }, request: ok }).state, 'empty')
  const m = buildSitesModel({ riskMap: RISK_MAP, request: ok })
  assert.equal(m.state, 'stale')
  assert.deepEqual(m.notes.map((n) => n.key), ['sites.note.readings', 'sites.note.stale', 'sites.note.test'])
  assert.deepEqual(m.notes[0].params, { n: '4', total: '7' })
  assert.equal(m.notes[2].params.version, 'TEST-20261009-9fc9a022')
  assert.equal(m.disclaimer.text, DISCLAIMER)
  assert.equal(m.disclaimer.endpoint, '/risk-map')
})

// ---------------------------------------------------------------- anomaly

test('anomaly chip only with a valid TEST baseline and a non-null level, always "(TEST)"', () => {
  const b = siteBaseline(RISK_MAP)
  assert.equal(b.isTest, true)
  const shown = anomalyCell(RISK_MAP.features[0], b)
  assert.equal(shown.chip.key, 'anomaly_normal_test')
  assert.equal(shown.z.text, '1.02')
  const watch = anomalyCell(RISK_MAP.features[3], b)
  assert.equal(watch.chip.key, 'anomaly_watch_test')
  assert.equal(watch.chip.hatch, true)

  const reasonOnly = anomalyCell(RISK_MAP.features[6], b)
  assert.equal(reasonOnly.chip, null)
  assert.equal(reasonOnly.z.text, '—')
  assert.equal(reasonOnly.reasonCode, 'insufficient_independent_dates')

  // Mode off: no column, no chip, even if a level were (wrongly) sent.
  const off = siteBaseline(RISK_MAP_OFF)
  assert.equal(off.present, false)
  const stray = anomalyCell(site('x', 'X', 100, 13, { signal_anomaly_level: 'high', signal_robust_z: 9 }), off)
  assert.equal(stray.visible, false)
  assert.equal(stray.chip, null)
  assert.equal(stray.z.text, '—')
  assert.ok(!buildSitesModel({ riskMap: RISK_MAP_OFF, request: ok }).columns.some((c) => c.id === 'anomaly'))

  // Test mode with an invalid baseline: the column stays, no chip, the reason shows.
  const invalidMap = { ...RISK_MAP, baseline: { ...BASELINE, valid: false, version: null, reason: 'preprocessing mismatch' } }
  const inv = siteBaseline(invalidMap)
  assert.equal(inv.present, true)
  assert.equal(inv.isTest, false)
  const c = anomalyCell(site('x', 'X', 100, 13, { signal_anomaly_level: 'watch', signal_robust_z: 2, signal_anomaly_reason: null }), inv)
  assert.equal(c.chip, null)
  assert.equal(c.reasonCode, 'baseline_invalid:preprocessing mismatch')
  const im = buildSitesModel({ riskMap: invalidMap, request: ok })
  assert.ok(im.columns.some((col) => col.id === 'anomaly'))
  assert.ok(im.notes.some((n) => n.key === 'sites.note.test_invalid'))
})

// ---------------------------------------------------------------- exports

test('exports: sites CSV has the documented column order; GeoJSON is the API response', () => {
  const ex = sitesExports(RISK_MAP)
  const csv = ex.csv.content()
  const header = csv.replace(/^﻿/, '').split('\r\n')[0]
  assert.equal(header, SITES_CSV_COLUMNS.join(','))
  assert.equal(csv.trim().split('\r\n').length, 1 + RISK_MAP.features.length)
  assert.ok(!/risk_level/.test(header), 'no risk column')
  assert.match(ex.csv.filename, /\.csv$/)

  const geo = ex.geojson.content()
  assert.deepEqual(JSON.parse(geo), RISK_MAP)
  assert.equal(sitesGeoJson(RISK_MAP), geo)
  assert.match(ex.geojson.filename, /\.geojson$/)
  assert.match(ex.geojson.type, /^application\/geo\+json/)
  assert.equal(sitesGeoJson(null), null)
  assert.equal(sitesExports(null), null)
})

test('column header sources name the endpoint, field path, unit, meaning and formula', () => {
  for (const col of SITE_COLUMNS) {
    const src = columnSource(col)
    assert.equal(src.endpoint, '/risk-map')
    assert.equal(src.field, col.path)
    assert.match(src.url, /\/risk-map$/)
    const rows = Object.fromEntries(src.rows.map((r) => [r.id, r]))
    assert.equal(rows.endpoint.text, 'GET /risk-map')
    assert.equal(rows.field.text, col.path)
    assert.equal(rows.about.textKey, `sites.about.${col.id}`)
    assert.ok(EN.has(rows.about.textKey) && TH.has(rows.about.textKey), rows.about.textKey)
    if (col.labelKey) assert.ok(EN.has(col.labelKey) && TH.has(col.labelKey), col.labelKey)
  }
  const ndci = Object.fromEntries(columnSource(SITE_COLUMNS.find((c) => c.id === 'ndci')).rows.map((r) => [r.id, r]))
  assert.equal(ndci.formula.href, '/methods#ndci')
  assert.equal(ndci.unit.textKey, 'unit.dimensionless')
})

// ----------------------------------------------------------------- detail

test('detail: unknown site id is not_found; loading/error before /risk-map arrives', () => {
  assert.equal(buildSiteDetailModel({ riskMap: RISK_MAP, siteId: 'nope', request: ok }).state, 'not_found')
  assert.equal(buildSiteDetailModel({ riskMap: RISK_MAP, siteId: '', request: ok }).state, 'not_found')
  assert.equal(buildSiteDetailModel({ riskMap: null, siteId: 'bangsaen', request: { loading: true } }).state, 'loading')
  const e = buildSiteDetailModel({ riskMap: null, siteId: 'bangsaen', request: { error: new Error('down') } })
  assert.equal(e.state, 'error')
  assert.equal(e.error.endpoint, '/risk-map')
  assert.equal(findSite(RISK_MAP, 'pattaya').properties.name, 'Pattaya, Chonburi')
})

test('detail: images with date and cloud; absent URL -> stated reason', () => {
  const d = buildSiteDetailModel({ riskMap: RISK_MAP, siteId: 'bangsaen', request: ok, methods: METHODS })
  assert.equal(d.state, 'ready')
  assert.deepEqual(d.images.map((i) => i.id), ['true_color', 'ndci_heatmap'])
  assert.equal(d.images[0].url, '/risk-map/bangsaen/image?image_type=true_color')
  assert.equal(d.images[1].url, '/risk-map/bangsaen/image?image_type=ndci_heatmap')
  assert.equal(d.images[0].date.text, '2026-09-29')
  assert.equal(d.images[0].cloud.text, `0.0${NBSP}%`)
  assert.equal(d.images[0].absent, null)

  const none = buildSiteDetailModel({ riskMap: RISK_MAP, siteId: 'siracha', request: ok })
  assert.equal(none.images[0].url, null)
  assert.equal(none.images[0].absent.key, 'site.image.absent')
  assert.equal(none.images[0].absent.statusReason, 'no_imagery')
  assert.equal(none.images[0].date.text, '—')

  // A reading whose image failed to render: no status reason, just "no cached image".
  const okNoImage = { ...RISK_MAP, features: [site('z', 'Z', 100, 13, { true_color_image_url: null })] }
  const z = buildSiteDetailModel({ riskMap: okNoImage, siteId: 'z', request: ok })
  assert.equal(z.images[0].absent.statusReason, null)
  assert.equal(z.images[0].absent.serverStatus, null)
  assert.equal(z.images[1].absent, null)
  // The server's image_status, when a response carries it, is the reason.
  const withStatus = { ...RISK_MAP, features: [site('w', 'W', 100, 13, { ndci_heatmap_image_url: null, image_status: 'render_failed' })] }
  assert.equal(buildSiteDetailModel({ riskMap: withStatus, siteId: 'w', request: ok }).images[1].absent.serverStatus, 'render_failed')
})

test('detail: index values with source refs and /methods links; primary index marked', () => {
  const d = buildSiteDetailModel({ riskMap: RISK_MAP, siteId: 'thachin_mouth', request: ok })
  assert.deepEqual(d.indices.map((i) => i.key), ['ndci', '2bda', '3bda', 'b2_b3_ratio'])
  assert.deepEqual(d.indices.map((i) => i.href), ['/methods#ndci', '/methods#2bda', '/methods#3bda', '/methods#b2_b3_ratio'])
  assert.equal(d.indices[0].used, true)
  assert.equal(d.indices[0].value.text, '−0.0354')
  const src = Object.fromEntries(d.indices[0].source.rows.map((r) => [r.id, r]))
  assert.equal(src.field.text, 'features[site_id=thachin_mouth].properties.index_values.ndci')
  assert.equal(src.value.text, '-0.03536536450230729', 'unrounded in the popover')
  assert.equal(src.formula.href, '/methods#ndci')

  const err = buildSiteDetailModel({ riskMap: RISK_MAP, siteId: 'bangpakong_mouth', request: ok })
  assert.equal(err.indices[0].value.text, '—')
  assert.equal(err.indices[0].reasonText, 'Earth Engine request failed: quota exceeded')
  assert.deepEqual(err.statusNote, { reasonCode: 'error', serverText: 'Earth Engine request failed: quota exceeded' })
})

test('detail: TEST anomaly block with z, level, reason, version and the site\'s baseline support', () => {
  const d = buildSiteDetailModel({ riskMap: RISK_MAP, siteId: 'chaophraya_mouth', request: ok })
  assert.equal(d.anomaly.state, 'test')
  assert.equal(d.anomaly.chip.key, 'anomaly_watch_test')
  assert.equal(d.anomaly.z.text, '2.40')
  assert.equal(d.anomaly.version, 'TEST-20261009-9fc9a022')
  assert.equal(d.anomaly.support.text, '44')
  const sup = Object.fromEntries(d.anomaly.supportSource.rows.map((r) => [r.id, r]))
  assert.equal(sup.field.text, 'baseline.min_season_dates_by_location.chaophraya_mouth')
  assert.equal(sup.value.text, '44')
  assert.equal(d.anomaly.declaredMin.text, '35')

  const p = buildSiteDetailModel({ riskMap: RISK_MAP, siteId: 'pattaya', request: ok })
  assert.equal(p.anomaly.chip, null)
  assert.equal(p.anomaly.z.text, '—')
  assert.equal(p.anomaly.reasonCode, 'insufficient_independent_dates')
  assert.equal(p.anomaly.support.text, '38')

  const missing = { ...RISK_MAP, features: [site('new_site', 'New', 100, 13)] }
  const n = buildSiteDetailModel({ riskMap: missing, siteId: 'new_site', request: ok })
  assert.equal(n.anomaly.support.text, '—')
  assert.equal(n.anomaly.support.reason, 'site_not_in_baseline')

  assert.equal(buildSiteDetailModel({ riskMap: RISK_MAP_OFF, siteId: 'bangsaen', request: ok }).anomaly.state, 'off')
  const inv = { ...RISK_MAP, baseline: { ...BASELINE, valid: false, reason: 'artefact missing' } }
  const i = buildSiteDetailModel({ riskMap: inv, siteId: 'bangsaen', request: ok })
  assert.equal(i.anomaly.state, 'invalid')
  assert.equal(i.anomaly.chip, null)
})

// ------------------------------------------------------------------- MODIS

test('MODIS table rows equal the API points (same order, same numbers)', () => {
  const rows = modisRows(TIMESERIES)
  assert.equal(rows.length, TIMESERIES.points.length)
  rows.forEach((r, i) => {
    assert.equal(r.raw, TIMESERIES.points[i])
    assert.equal(r.chlor.raw, TIMESERIES.points[i].chlor_a)
    assert.equal(r.z.raw, TIMESERIES.points[i].anomaly_z)
    assert.equal(r.date.text, TIMESERIES.points[i].date)
  })
  assert.equal(rows[0].chlor.text, `4.99${NBSP}mg${NBSP}m⁻³`)
  assert.equal(rows[3].chlor.text, `0.00${NBSP}mg${NBSP}m⁻³`, 'a measured 0 stays 0')
  assert.equal(rows[3].z.text, '—')
  assert.equal(rows[3].reasonText, 'climatology window had no other observations')
  const chart = modisChartData(TIMESERIES)
  assert.equal(chart.length, 4)
  assert.equal(chart[3].anomaly_z, null, 'a null z is never drawn as 0')
  assert.equal(chart[3].chlor_a, 0)
  assert.equal(chart[0].t, Date.UTC(2002, 8, 5))
})

test('MODIS block: resolution from /methods, CSV, loading/error/timeout degrade only this block', () => {
  const m = buildModisModel({ timeseries: TIMESERIES, request: ok, methods: METHODS, lat: 13.26, lng: 100.88, siteId: 'bangsaen' })
  assert.equal(m.state, 'ready')
  assert.equal(m.resolution.value.text, `4,638${NBSP}m`)
  assert.equal(m.count, 4)
  assert.equal(m.zMissing, 1)
  assert.equal(m.span, '2002-09-05–2003-01-02')
  assert.equal(m.endpoint, '/timeseries?lat=13.26&lng=100.88')
  assert.equal(m.sourceText, TIMESERIES.source)
  const csv = m.csv.content().replace(/^﻿/, '')
  assert.equal(csv.split('\r\n')[0], TIMESERIES_CSV_COLUMNS.join(','))
  assert.equal(csv.trim().split('\r\n').length, 1 + TIMESERIES.points.length)
  assert.equal(m.csv.filename, 'modis-chlor_a-bangsaen.csv')

  const noMethods = buildModisModel({ timeseries: TIMESERIES, request: ok, methods: null, lat: 13.26, lng: 100.88 })
  assert.equal(noMethods.resolution.value.text, '—', 'never a guessed resolution')

  assert.equal(buildModisModel({ timeseries: null, request: { loading: true }, lat: 13.26, lng: 100.88 }).state, 'loading')
  assert.equal(buildModisModel({ timeseries: null, request: {}, lat: 13.26, lng: 100.88 }).state, 'loading', 'not started yet is loading')
  const err = buildModisModel({ timeseries: null, request: { error: { response: { status: 503 } } }, lat: 13.26, lng: 100.88 })
  assert.equal(err.state, 'error')
  assert.equal(err.error.endpoint, '/timeseries?lat=13.26&lng=100.88')
  const timeout = buildModisModel({ timeseries: null, request: { error: { code: 'ECONNABORTED', message: 'timeout of 120000ms exceeded' } }, lat: 13.26, lng: 100.88 })
  assert.equal(timeout.state, 'timeout')
  assert.equal(timeout.timeoutSeconds, TIMESERIES_TIMEOUT_MS / 1000)
  assert.equal(isTimeout(new Error('timeout of 30000ms exceeded')), true)
  assert.equal(isTimeout(new Error('Network Error')), false)
  assert.equal(isTimeout(null), false)
  assert.equal(buildModisModel({ timeseries: { ...TIMESERIES, points: [] }, request: ok, lat: 13.26, lng: 100.88 }).state, 'empty')

  // The site page still renders its other blocks while /timeseries fails.
  const d = buildSiteDetailModel({
    riskMap: RISK_MAP, siteId: 'bangsaen', request: ok, timeseries: null,
    timeseriesRequest: { error: { response: { status: 502 } } }, methods: METHODS,
  })
  assert.equal(d.state, 'ready')
  assert.equal(d.modis.state, 'error')
  assert.equal(d.indices.length, 4)
})

test('every i18n key a model names exists in TH and EN', () => {
  const models = [
    buildSitesModel({ riskMap: RISK_MAP, request: ok }),
    buildSitesModel({ riskMap: { ...RISK_MAP, features: [] }, request: ok }),
    buildSitesModel({ riskMap: { ...RISK_MAP, baseline: { ...BASELINE, valid: false, reason: 'x' } }, request: ok }),
    ...RISK_MAP.features.map((f) => buildSiteDetailModel({
      riskMap: RISK_MAP, siteId: f.properties.site_id, request: ok, timeseries: TIMESERIES, timeseriesRequest: ok, methods: METHODS,
    })),
    buildModisModel({ timeseries: { ...TIMESERIES, points: [] }, request: ok, lat: 1, lng: 2 }),
    buildModisModel({ timeseries: null, request: ok, lat: null, lng: 2 }),
  ]
  const keys = new Set()
  for (const m of models) modelKeys(m, keys)
  assert.ok(keys.size > 20)
  for (const key of keys) {
    if (/^(status|reason|unit|source)\./.test(key) || /^(sites|site)\./.test(key)) {
      assert.ok(EN.has(key), `en.js lacks ${key}`)
      assert.ok(TH.has(key), `th.js lacks ${key}`)
    }
  }
})

// ----------------------------------------------------------------- markup

let server
let SitesView
let SiteDetailView
let StaticLangProvider

before(async () => {
  server = await createServer({
    configFile: false,
    plugins: [react()],
    cacheDir: 'node_modules/.vite-sites-tests',
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true, watch: null, hmr: false, ws: false },
  })
  SitesView = (await server.ssrLoadModule('/src/pages/SitesPage.jsx')).SitesView
  SiteDetailView = (await server.ssrLoadModule('/src/pages/SiteDetailPage.jsx')).SiteDetailView
  ;({ StaticLangProvider } = await server.ssrLoadModule('/src/i18n/LangContext.jsx'))
})

after(async () => server?.close())

function render(element, lang = 'en', path = '/sites') {
  return renderToStaticMarkup(createElement(MemoryRouter, { initialEntries: [path] },
    createElement(StaticLangProvider, { lang }, element)))
}

const visible = (html) => html.replace(/<[^>]+>/g, ' ').replace(/&#x27;/g, "'").replace(/&quot;/g, '"')
  .replace(/&amp;/g, '&').replace(/\s+/g, ' ')

test('SitesView: one h1, sortable headers with aria-sort, seven rows, header sources, exports', () => {
  missingKeys.clear()
  const model = buildSitesModel({ riskMap: RISK_MAP, request: ok, sort: { column: 'actual_date', direction: 'desc' } })
  const html = render(createElement(SitesView, { model, onSort: () => {}, onRetry: () => {} }))
  assert.equal((html.match(/<h1/g) ?? []).length, 1)
  assert.equal((html.match(/<tbody[\s\S]*?<\/tbody>/)[0].match(/<tr/g) ?? []).length, 7)
  assert.match(html, /aria-sort="descending"/)
  assert.equal((html.match(/aria-sort="/g) ?? []).length, model.columns.length)
  assert.equal((html.match(/<th[^>]*><button[^>]*class="pw-sort-btn"/g) ?? []).length, model.columns.length, 'every header is a button')
  assert.ok((html.match(/class="pw-source-btn"/g) ?? []).length >= model.columns.length, 'every header has a source popover')
  for (const f of RISK_MAP.features) assert.match(html, new RegExp(`href="/sites/${f.properties.site_id}"`))
  // The first row after a date-descending sort.
  assert.ok(html.indexOf('Tha Chin') < html.indexOf('Bang Saen'))
  const text = visible(html)
  assert.ok(text.includes('Download CSV'))
  assert.ok(text.includes(en.sites.export_geojson))
  assert.ok(text.includes('Anomaly vs own history: watch (TEST)'))
  assert.ok(text.includes('Not anomalous vs own history (TEST)'))
  assert.ok(text.includes('Risk not evaluated'))
  assert.ok(text.includes(en.reason.insufficient_independent_dates))
  assert.ok(html.includes('data-label="'), 'cells carry labels for the narrow-screen card list')
  assert.doesNotMatch(html, /risk-(normal|elevated|watch|warning)|RISK_COLOR/)
  assert.deepEqual([...missingKeys], [])
})

test('SitesView: mode off has no anomaly column and no (TEST); Thai renders without missing keys', () => {
  missingKeys.clear()
  const model = buildSitesModel({ riskMap: RISK_MAP_OFF, request: ok })
  const html = render(createElement(SitesView, { model, onSort: () => {} }), 'th')
  assert.doesNotMatch(html, /\(TEST\)/)
  assert.deepEqual([...missingKeys], [])
  const loading = render(createElement(SitesView, { model: buildSitesModel({ riskMap: null, request: { loading: true } }) }))
  assert.match(loading, /aria-busy="true"/)
  const err = render(createElement(SitesView, { model: buildSitesModel({ riskMap: null, request: { error: { response: { status: 503, data: { detail: 'GEE not configured' } } } } }) }))
  assert.ok(visible(err).includes('GEE not configured'))
  assert.ok(visible(err).includes('GET /risk-map'))
})

test('SiteDetailView: images, indices with method links, TEST block, MODIS figure + table, never "1 km"', () => {
  missingKeys.clear()
  const model = buildSiteDetailModel({
    riskMap: RISK_MAP, siteId: 'bangsaen', request: ok, timeseries: TIMESERIES, timeseriesRequest: ok, methods: METHODS,
  })
  const html = render(createElement(SiteDetailView, { model, onRetry: {} }), 'en', '/sites/bangsaen')
  assert.equal((html.match(/<h1/g) ?? []).length, 1)
  const text = visible(html)
  assert.ok(text.includes('Bang Saen, Chonburi'))
  for (const k of ['ndci', '2bda', '3bda', 'b2_b3_ratio']) assert.match(html, new RegExp(`href="/methods#${k}"`))
  assert.ok(text.includes('Not anomalous vs own history (TEST)'))
  assert.ok(text.includes('TEST-20261009-9fc9a022'))
  assert.ok(text.includes(en.site.modis.z_label))
  assert.ok(html.includes(`4,638${NBSP}m`))
  assert.doesNotMatch(text, /1\s*km/)
  // The data table under the chart: one row per API point.
  const table = html.match(/<table class="pw-table pw-modis-table"[\s\S]*?<\/table>/)
  assert.ok(table, 'MODIS data table present')
  assert.equal((table[0].match(/<tbody[\s\S]*?<\/tbody>/)[0].match(/<tr/g) ?? []).length, TIMESERIES.points.length)
  assert.ok(text.includes('climatology window had no other observations'))
  assert.doesNotMatch(html, /risk-(normal|elevated|watch|warning)|RISK_COLOR/)
  assert.deepEqual([...missingKeys], [])
})

test('SiteDetailView: /timeseries failure degrades only the MODIS block; no reading states its reason', () => {
  missingKeys.clear()
  const model = buildSiteDetailModel({
    riskMap: RISK_MAP, siteId: 'siracha', request: ok, timeseries: null,
    timeseriesRequest: { error: { code: 'ECONNABORTED', message: 'timeout of 120000ms exceeded' } }, methods: METHODS,
  })
  const html = render(createElement(SiteDetailView, { model, onRetry: {} }), 'th', '/sites/siracha')
  const text = visible(html)
  assert.ok(text.includes(th.reason.no_imagery))
  assert.ok(text.includes(createT('th')('site.modis.timeout', { seconds: '120' })))
  assert.match(html, /href="\/methods#ndci"/, 'the rest of the page still renders')
  assert.deepEqual([...missingKeys], [])

  const loading = buildSiteDetailModel({ riskMap: RISK_MAP, siteId: 'bangsaen', request: ok, timeseries: null, timeseriesRequest: { loading: true } })
  const lh = render(createElement(SiteDetailView, { model: loading, onRetry: {} }), 'en', '/sites/bangsaen')
  assert.ok(visible(lh).includes(en.site.modis.loading))
})

test('SiteDetailView: unknown site id renders the not-found page', () => {
  const model = buildSiteDetailModel({ riskMap: RISK_MAP, siteId: 'nope', request: ok })
  const html = render(createElement(SiteDetailView, { model, onRetry: {} }), 'en', '/sites/nope')
  assert.ok(visible(html).includes(en.notfound.title))
})

test('the sites pages and components use no risk colour tokens and no risk tiers', async () => {
  for (const file of ['src/pages/SitesPage.jsx', 'src/pages/SiteDetailPage.jsx', 'src/components/SitesTable.jsx',
    'src/components/SiteImages.jsx', 'src/components/ModisSeries.jsx', 'src/lib/sitesModel.js']) {
    const src = await readFile(new URL(`../${file}`, import.meta.url), 'utf8')
    assert.doesNotMatch(src, /--risk-|RISK_COLOR|riskColor/, file)
    assert.doesNotMatch(src, /risk_level\s*[!=]==?\s*['"]/, `${file} branches on a risk tier`)
  }
  assert.equal(T.en('site.modis.heading').includes('MODIS'), true)
})
