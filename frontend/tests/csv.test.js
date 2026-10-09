/**
 * CSV exports: RFC 4180 escaping, unknown as an empty cell (never 0),
 * full-precision API values, and fixed, documented column orders that
 * carry their own provenance (endpoint, run, dates, server disclaimer).
 */
import test from 'node:test'
import assert from 'node:assert/strict'

import {
  toCsv, sitesCsv, timeseriesCsv, pinsCsv, cellCsv,
  SITES_CSV_COLUMNS, TIMESERIES_CSV_COLUMNS, PINS_CSV_COLUMNS, CELL_CSV_COLUMNS,
} from '../src/lib/csv.js'

const DISCLAIMER = 'Satellite index values describe water colour at pixel resolution. Small or scattered blooms may not be visible.'

function parse(csv) {
  // Minimal RFC 4180 reader for the assertions below.
  const rows = []
  let row = []
  let cell = ''
  let quoted = false
  for (let i = 0; i < csv.length; i += 1) {
    const c = csv[i]
    if (quoted) {
      if (c === '"' && csv[i + 1] === '"') { cell += '"'; i += 1 } else if (c === '"') quoted = false
      else cell += c
    } else if (c === '"') quoted = true
    else if (c === ',') { row.push(cell); cell = '' } else if (c === '\r' && csv[i + 1] === '\n') {
      row.push(cell); rows.push(row); row = []; cell = ''; i += 1
    } else cell += c
  }
  if (cell !== '' || row.length) { row.push(cell); rows.push(row) }
  return rows
}

const asRecords = (csv) => {
  const [header, ...body] = parse(csv)
  return body.map((r) => Object.fromEntries(header.map((h, i) => [h, r[i]])))
}

test('toCsv escapes commas, quotes and newlines per RFC 4180, with CRLF line ends', () => {
  const csv = toCsv(['a', 'b', 'c'], [
    { a: 'plain', b: 'with, comma', c: 'say "hi"' },
    { a: 'line\nbreak', b: 'cr\r\nlf', c: 'ok' },
  ])
  assert.equal(csv,
    'a,b,c\r\n'
    + 'plain,"with, comma","say ""hi"""\r\n'
    + '"line\nbreak","cr\r\nlf",ok\r\n')
  assert.deepEqual(parse(csv), [
    ['a', 'b', 'c'],
    ['plain', 'with, comma', 'say "hi"'],
    ['line\nbreak', 'cr\r\nlf', 'ok'],
  ])
})

test('toCsv: null/undefined/NaN/Infinity are empty cells; a real zero stays 0; numbers unrounded', () => {
  const csv = toCsv(['v'], [{ v: null }, { v: undefined }, { v: Number.NaN }, { v: Infinity }, { v: 0 }, { v: -0.012 }, { v: 0.1803278625011444 }, {}])
  assert.equal(csv, 'v\r\n\r\n\r\n\r\n\r\n0\r\n-0.012\r\n0.1803278625011444\r\n\r\n')
})

test('toCsv: column objects, booleans, objects, and the optional BOM', () => {
  const cols = [{ header: 'id', key: 'k' }, { header: 'twice', get: (r) => r.k * 2 }, 'flag', 'obj']
  const csv = toCsv(cols, [{ k: 2, flag: false, obj: { x: 1 } }])
  assert.equal(csv, 'id,twice,flag,obj\r\n2,4,false,"{""x"":1}"\r\n')
  assert.ok(toCsv(['a'], [], { bom: true }).startsWith('﻿a\r\n'))
  assert.ok(!toCsv(['a'], []).startsWith('﻿'))
  assert.equal(toCsv(['a'], null), 'a\r\n')
})

const RISK_MAP = Object.freeze({
  type: 'FeatureCollection',
  disclaimer: DISCLAIMER,
  baseline: { mode: 'test', valid: true, version: 'TEST-20261009-9fc9a022' },
  features: [
    {
      type: 'Feature', geometry: { type: 'Point', coordinates: [100.88, 13.26] },
      properties: {
        disclaimer: DISCLAIMER, site_id: 'bangsaen', name: 'Bang Saen, Chonburi', risk_level: null,
        status: 'ok', signal_anomaly_level: 'normal', signal_robust_z: 1.020230629103153,
        signal_anomaly_reason: null, index_used: 'ndci',
        index_values: { ndci: 0.07746194641245618, '2bda': 1.1679322519244035, '3bda': 0.1356341106597835, b2_b3_ratio: 0.9113519076247312 },
        cloud_fraction: 0.0, actual_date: '2026-09-29', fetched_at: '2026-10-09T13:05:19.872400+00:00',
        stale: false, error: null,
      },
    },
    {
      type: 'Feature', geometry: { type: 'Point', coordinates: [100.9, 13.17] },
      properties: {
        disclaimer: DISCLAIMER, site_id: 'siracha', name: 'Si Racha, Chonburi', risk_level: null,
        status: 'no_imagery', signal_anomaly_level: null, signal_robust_z: null,
        signal_anomaly_reason: 'no_imagery', index_used: null, index_values: null,
        cloud_fraction: null, actual_date: null, fetched_at: '2026-10-09T13:06:00+00:00',
        stale: false, error: null,
      },
    },
  ],
})

test('sitesCsv: fixed columns, API field paths as headers, no risk column', () => {
  assert.deepEqual([...SITES_CSV_COLUMNS], [
    'site_id', 'name', 'lat', 'lng', 'status', 'stale', 'actual_date', 'cloud_fraction', 'index_used',
    'index_values.ndci', 'index_values.2bda', 'index_values.3bda', 'index_values.b2_b3_ratio',
    'signal_anomaly_level', 'signal_robust_z', 'signal_anomaly_reason',
    'baseline.mode', 'baseline.version', 'fetched_at', 'error', 'endpoint', 'disclaimer',
  ])
  assert.ok(!SITES_CSV_COLUMNS.some((c) => /risk/.test(c)))
  const csv = sitesCsv(RISK_MAP)
  assert.deepEqual(parse(csv)[0], [...SITES_CSV_COLUMNS])
  const [ok, none] = asRecords(csv)
  assert.equal(ok.site_id, 'bangsaen')
  assert.equal(ok.lat, '13.26')
  assert.equal(ok.lng, '100.88')
  assert.equal(ok['index_values.ndci'], '0.07746194641245618')
  assert.equal(ok['index_values.2bda'], '1.1679322519244035')
  assert.equal(ok.cloud_fraction, '0')
  assert.equal(ok.stale, 'false')
  assert.equal(ok.signal_robust_z, '1.020230629103153')
  assert.equal(ok['baseline.version'], 'TEST-20261009-9fc9a022')
  assert.equal(ok.endpoint, 'GET /risk-map')
  assert.equal(ok.disclaimer, DISCLAIMER)
  assert.equal(none['index_values.ndci'], '')
  assert.equal(none.cloud_fraction, '')
  assert.equal(none.signal_anomaly_reason, 'no_imagery')
  assert.equal(sitesCsv(null), `${SITES_CSV_COLUMNS.join(',')}\r\n`)
})

test('timeseriesCsv: one row per API point, same numbers', () => {
  assert.deepEqual([...TIMESERIES_CSV_COLUMNS],
    ['date', 'chlor_a', 'anomaly_z', 'reason', 'lat', 'lng', 'source', 'endpoint', 'disclaimer'])
  const ts = {
    lat: 13.26, lng: 100.88, source: 'MODIS-Aqua chlor_a, 2002-present (data-pipeline get_modis_chlorophyll_history)',
    disclaimer: DISCLAIMER,
    points: [
      { date: '2026-09-01', chlor_a: 3.21, anomaly_z: -0.4, reason: null },
      { date: '2026-09-02', chlor_a: 0, anomaly_z: null, reason: 'climatology window had no other observations' },
    ],
  }
  const recs = asRecords(timeseriesCsv(ts))
  assert.equal(recs.length, 2)
  assert.equal(recs[0].chlor_a, '3.21')
  assert.equal(recs[0].anomaly_z, '-0.4')
  assert.equal(recs[1].chlor_a, '0')
  assert.equal(recs[1].anomaly_z, '')
  assert.equal(recs[1].reason, 'climatology window had no other observations')
  assert.equal(recs[0].endpoint, 'GET /timeseries?lat=13.26&lng=100.88')
  assert.equal(recs[0].source, ts.source)
  assert.equal(timeseriesCsv(null), `${TIMESERIES_CSV_COLUMNS.join(',')}\r\n`)
})

const NDCI_PINS = Object.freeze({
  disclaimer: DISCLAIMER, run_id: 6, mode: 'ndci', metric: 'ndci',
  ranking: 'descending value within this run; not a risk level',
  n_requested: 5, min_separation_m: 3000, cohort_size: 209594, reason: null, baseline: null,
  pins: [{
    rank: 1, cell_lat: 13.049944, cell_lng: 100.620321, pixel_centre_lat: 13.050137, pixel_centre_lng: 100.620126,
    index_values: { ndci: 0.112, bda2: 1.25, bda3: 0.41, b2_b3: 0.83 }, percentile: 99.99,
    metric_value: 0.112, date_ms: 1788492600000, acquired_date: '2026-09-04', acquired_at: '2026-09-04T03:30:00Z',
    edge_of_no_data: false, risk_tier: null, visible_bands_dn: { red: 412.0, green: 655.0, blue: 803.0 },
  }],
})

const ANOMALY_PINS = Object.freeze({
  ...NDCI_PINS, mode: 'anomaly', metric: 'robust_z',
  ranking: "descending robust z against this location's own TEST seasonal baseline; not a risk level",
  baseline: { mode: 'test', valid: true, version: 'TEST-20261009-9fc9a022' },
  pins: [{
    ...NDCI_PINS.pins[0], metric_value: 3.4, robust_z: 3.4, median_ndci: 0.043, mad: 0.0137,
    n_dates: 44, anomaly_level: 'high', visible_bands_dn: null,
  }],
})

test('pinsCsv: one column set for both modes, anomaly fields empty in ndci mode', () => {
  assert.deepEqual([...PINS_CSV_COLUMNS], [
    'run_id', 'mode', 'metric', 'rank', 'metric_value', 'percentile',
    'cell_lat', 'cell_lng', 'pixel_centre_lat', 'pixel_centre_lng',
    'index_values.ndci', 'index_values.bda2', 'index_values.bda3', 'index_values.b2_b3',
    'acquired_date', 'acquired_at', 'date_ms', 'edge_of_no_data',
    'robust_z', 'median_ndci', 'mad', 'n_dates', 'anomaly_level',
    'visible_bands_dn.red', 'visible_bands_dn.green', 'visible_bands_dn.blue',
    'baseline.version', 'ranking', 'cohort_size', 'min_separation_m', 'endpoint', 'disclaimer',
  ])
  const [ndci] = asRecords(pinsCsv(NDCI_PINS))
  assert.equal(ndci.run_id, '6')
  assert.equal(ndci.rank, '1')
  assert.equal(ndci['index_values.ndci'], '0.112')
  assert.equal(ndci.date_ms, '1788492600000')
  assert.equal(ndci.robust_z, '')
  assert.equal(ndci.anomaly_level, '')
  assert.equal(ndci['visible_bands_dn.red'], '412')
  assert.equal(ndci['baseline.version'], '')
  assert.equal(ndci.ranking, 'descending value within this run; not a risk level')
  assert.equal(ndci.endpoint, 'GET /raster-scan/highlights?run_id=6&n=5&min_separation_m=3000&mode=ndci')
  const [anom] = asRecords(pinsCsv(ANOMALY_PINS))
  assert.equal(anom.robust_z, '3.4')
  assert.equal(anom.anomaly_level, 'high')
  assert.equal(anom['visible_bands_dn.red'], '')
  assert.equal(anom['baseline.version'], 'TEST-20261009-9fc9a022')
  assert.equal(anom.endpoint, 'GET /raster-scan/highlights?run_id=6&n=5&min_separation_m=3000&mode=anomaly')
  assert.equal(pinsCsv(null), `${PINS_CSV_COLUMNS.join(',')}\r\n`)
  assert.equal(parse(pinsCsv({ ...NDCI_PINS, pins: [] })).length, 1)
})

test('cellCsv: one row, every inspector field incl. the anomaly block and run/date provenance', () => {
  assert.deepEqual([...CELL_CSV_COLUMNS], [
    'run_id', 'date_used', 'scale_m', 'state', 'meaning', 'query_lat', 'query_lng',
    'cell_lat', 'cell_lng', 'pixel_centre_lat', 'pixel_centre_lng', 'pixel_row', 'pixel_col',
    'index_values.ndci', 'index_values.bda2', 'index_values.bda3', 'index_values.b2_b3', 'unreadable_bands',
    'acquired_date', 'acquired_at', 'date_ms',
    'anomaly.robust_z', 'anomaly.median_ndci', 'anomaly.mad', 'anomaly.n_dates', 'anomaly.level',
    'anomaly.reason', 'anomaly.season_key', 'anomaly.baseline_version',
    'anomaly.visible_bands_dn.red', 'anomaly.visible_bands_dn.green', 'anomaly.visible_bands_dn.blue',
    'endpoint', 'disclaimer',
  ])
  const pixel = {
    disclaimer: DISCLAIMER, state: 'reading', meaning: 'index readings at this cell, a measurement', run_id: 6,
    date_used: '2026-10-09', scale_m: 200, query_lat: 13.0, query_lng: 100.6,
    cell_lat: 12.999520476493597, cell_lng: 100.59963372269286,
    pixel_centre_lat: 13.0003360400002, pixel_centre_lng: 100.59963350562057, pixel_row: 342, pixel_col: 382,
    index_values: { ndci: 0.1803278625011444, bda2: 1.440000057220459, bda3: null, b2_b3: 0.8784530162811279 },
    unreadable_bands: ['bda3'], date_ms: 1791345282024, acquired_date: '2026-10-07',
    acquired_at: '2026-10-07T03:54:42.024000Z',
    anomaly: { robust_z: 3.4452417189507827, median_ndci: 0.04491525515913963, mad: 0.026510346680879593,
      n_dates: 47, level: 'high', reason: null, baseline_version: 'TEST-20261009-9fc9a022', season_key: 'm10+-1',
      visible_bands_dn: { red: 412, green: 0, blue: null } },
  }
  const recs = asRecords(cellCsv(pixel))
  assert.equal(recs.length, 1)
  const [r] = recs
  assert.equal(r['index_values.ndci'], '0.1803278625011444')
  assert.equal(r['index_values.bda3'], '')
  assert.equal(r.unreadable_bands, 'bda3')
  assert.equal(r['anomaly.robust_z'], '3.4452417189507827')
  assert.equal(r['anomaly.visible_bands_dn.green'], '0')
  assert.equal(r['anomaly.visible_bands_dn.blue'], '')
  assert.equal(r.meaning, 'index readings at this cell, a measurement')
  assert.equal(r.endpoint, 'GET /raster-scan/pixel?lat=13&lng=100.6&run_id=6')

  const [nm] = asRecords(cellCsv({ state: 'not_measured', run_id: 6, query_lat: 12.7, query_lng: 100.1, index_values: null, anomaly: null, unreadable_bands: [] }))
  assert.equal(nm.state, 'not_measured')
  assert.equal(nm['index_values.ndci'], '')
  assert.equal(nm['anomaly.level'], '')
  assert.equal(nm.unreadable_bands, '')
  assert.equal(cellCsv(null), `${CELL_CSV_COLUMNS.join(',')}\r\n`)
})
