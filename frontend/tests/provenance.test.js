/**
 * sourceRef and its helpers: where a displayed number came from.
 *
 * A judge clicks a number and must see the endpoint, the field path, the
 * exact value the API returned (unrounded), its unit, the observation
 * date, the run, and a link to the formula -- plus a raw-JSON URL that
 * reproduces the response. Nothing may be invented: what is not known
 * is "—".
 */
import test from 'node:test'
import assert from 'node:assert/strict'

import {
  sourceRef, refForPixelField, refForSiteField, refForRasterField, SOURCE_ROW_IDS,
} from '../src/lib/provenance.js'
import { createT, missingKeys } from '../src/i18n/index.js'

const PIXEL = Object.freeze({
  state: 'reading', meaning: 'index readings at this cell', run_id: 6, date_used: '2026-10-09',
  scale_m: 200, query_lat: 13.0, query_lng: 100.6,
  cell_lat: 12.999520476493597, cell_lng: 100.59963372269286,
  pixel_centre_lat: 13.0003360400002, pixel_centre_lng: 100.59963350562057,
  pixel_row: 342, pixel_col: 382,
  index_values: { ndci: 0.1803278625011444, bda2: 1.440000057220459, bda3: 0.41555556654930115, b2_b3: 0.8784530162811279 },
  unreadable_bands: [], date_ms: 1791345282024, acquired_date: '2026-10-07',
  acquired_at: '2026-10-07T03:54:42.024000Z',
  anomaly: { robust_z: 3.4452417189507827, median_ndci: 0.04491525515913963, mad: 0.026510346680879593,
    n_dates: 47, level: 'high', reason: null, baseline_version: 'TEST-20261009-9fc9a022', season_key: 'm10+-1' },
})

const NOT_MEASURED = Object.freeze({
  state: 'not_measured', meaning: 'no usable reading', run_id: 6, query_lat: 12.7, query_lng: 100.1,
  cell_lat: null, cell_lng: null, index_values: null, acquired_date: null, anomaly: null,
})

const FEATURE = Object.freeze({
  type: 'Feature',
  geometry: { type: 'Point', coordinates: [100.88, 13.26] },
  properties: {
    site_id: 'bangsaen', name: 'Bang Saen, Chonburi', status: 'ok', risk_level: null,
    index_values: { ndci: 0.07746194641245618, '2bda': 1.1679322519244035, '3bda': 0.1356341106597835, b2_b3_ratio: 0.9113519076247312 },
    cloud_fraction: 0.0, actual_date: '2026-09-29', signal_robust_z: 1.020230629103153,
    fetched_at: '2026-10-09T13:05:19.872400+00:00', stale: false,
  },
})

const RASTER = Object.freeze({
  run_id: 6, date_used: '2026-10-09', scale_m: 200, cell_count: 235290, scene_count: 32,
  oldest_scene_date: '2026-09-29', newest_scene_date: '2026-10-07',
  coverage: { measured_fraction: 0.642290001011268, measured_pixels: 209594, polygon_pixels: 326323 },
})

const row = (ref, id) => ref.rows.find((r) => r.id === id)

test('sourceRef builds the eight rows in a fixed order with i18n labels', () => {
  assert.deepEqual([...SOURCE_ROW_IDS],
    ['endpoint', 'field', 'value', 'unit', 'observed_date', 'run_id', 'scene_id', 'formula'])
  const ref = sourceRef({
    endpoint: '/raster-scan/pixel', field: 'index_values.ndci', value: 0.1803278625011444,
    unit: 'dimensionless', observedDate: '2026-10-07', runId: 6, sceneId: null,
    formulaKey: 'ndci', params: { lat: 13, lng: 100.6, run_id: 6 },
  })
  assert.equal(ref.endpoint, '/raster-scan/pixel')
  assert.equal(ref.field, 'index_values.ndci')
  assert.match(ref.url, /\/raster-scan\/pixel\?lat=13&lng=100\.6&run_id=6$/)
  assert.deepEqual(ref.rows.map((r) => r.id), [...SOURCE_ROW_IDS])
  assert.deepEqual(ref.rows.map((r) => r.labelKey), SOURCE_ROW_IDS.map((id) => `source.${id}`))
  assert.equal(row(ref, 'endpoint').text, 'GET /raster-scan/pixel?lat=13&lng=100.6&run_id=6')
  assert.equal(row(ref, 'field').text, 'index_values.ndci')
  // The value is the API's own, unrounded: a judge can match it to the JSON.
  assert.equal(row(ref, 'value').text, '0.1803278625011444')
  assert.equal(row(ref, 'value').value, 0.1803278625011444)
  assert.equal(row(ref, 'unit').textKey, 'unit.dimensionless')
  assert.equal(row(ref, 'observed_date').text, '2026-10-07')
  assert.equal(row(ref, 'run_id').text, '6')
  assert.equal(row(ref, 'scene_id').text, '—')
  assert.equal(row(ref, 'formula').text, 'ndci')
  assert.equal(row(ref, 'formula').href, '/methods#ndci')
})

test('unknown rows are "—", never fabricated; null params are dropped from the URL', () => {
  const ref = sourceRef({ endpoint: '/risk-map', field: 'x', params: { a: null, b: undefined, c: 0 } })
  assert.match(ref.url, /\/risk-map\?c=0$/)
  for (const id of ['value', 'unit', 'observed_date', 'run_id', 'scene_id', 'formula']) {
    assert.equal(row(ref, id).text, '—', id)
  }
  assert.equal(row(ref, 'formula').href, null)
  // A measured zero is a value, not unknown.
  assert.equal(row(sourceRef({ endpoint: '/x', field: 'v', value: 0 }), 'value').text, '0')
  assert.equal(row(sourceRef({ endpoint: '/x', field: 'v', value: false }), 'value').text, 'false')
  // No endpoint: no URL to open.
  assert.equal(sourceRef({}).url, null)
})

test('symbol units are shown as symbols; word units carry an i18n key', () => {
  const deg = row(sourceRef({ endpoint: '/x', field: 'cell_lat', value: 13, unit: '°' }), 'unit')
  assert.equal(deg.text, '°')
  assert.equal(deg.textKey, null)
  const count = row(sourceRef({ endpoint: '/x', field: 'cell_count', value: 1, unit: 'count' }), 'unit')
  assert.equal(count.textKey, 'unit.count')
})

test('refForPixelField: endpoint, query, run, acquisition date and formula link', () => {
  const ref = refForPixelField(PIXEL, 'index_values.ndci')
  assert.equal(ref.endpoint, '/raster-scan/pixel')
  assert.match(ref.url, /\/raster-scan\/pixel\?lat=13&lng=100\.6&run_id=6$/)
  assert.equal(row(ref, 'value').text, '0.1803278625011444')
  assert.equal(row(ref, 'observed_date').text, '2026-10-07')
  assert.equal(row(ref, 'run_id').text, '6')
  assert.equal(row(ref, 'formula').href, '/methods#ndci')
  // Raster band names map to the /methods index keys.
  assert.equal(row(refForPixelField(PIXEL, 'index_values.bda2'), 'formula').text, '2bda')
  assert.equal(row(refForPixelField(PIXEL, 'index_values.bda3'), 'formula').text, '3bda')
  assert.equal(row(refForPixelField(PIXEL, 'index_values.b2_b3'), 'formula').text, 'b2_b3_ratio')
  assert.equal(row(refForPixelField(PIXEL, 'anomaly.robust_z'), 'formula').href, '/methods#robust_z')
  assert.equal(row(refForPixelField(PIXEL, 'anomaly.robust_z'), 'value').text, '3.4452417189507827')
  assert.equal(row(refForPixelField(PIXEL, 'cell_lat'), 'unit').text, '°')
  assert.equal(row(refForPixelField(PIXEL, 'scale_m'), 'unit').text, 'm')
  assert.equal(row(refForPixelField(PIXEL, 'acquired_date'), 'formula').text, '—')
})

test('refForPixelField on an unmeasured cell: the value is "—", the source is still stated', () => {
  const ref = refForPixelField(NOT_MEASURED, 'index_values.ndci')
  assert.equal(row(ref, 'value').text, '—')
  assert.equal(row(ref, 'value').value, null)
  assert.equal(row(ref, 'observed_date').text, '—')
  assert.match(ref.url, /\/raster-scan\/pixel\?lat=12\.7&lng=100\.1&run_id=6$/)
  assert.doesNotThrow(() => refForPixelField(null, 'index_values.ndci'))
})

test('refForSiteField: /risk-map, the feature-qualified field path and the scene date', () => {
  const ref = refForSiteField(FEATURE, 'index_values.ndci')
  assert.equal(ref.endpoint, '/risk-map')
  assert.match(ref.url, /\/risk-map$/)
  assert.equal(ref.field, 'features[site_id=bangsaen].properties.index_values.ndci')
  assert.equal(row(ref, 'value').text, '0.07746194641245618')
  assert.equal(row(ref, 'observed_date').text, '2026-09-29')
  assert.equal(row(ref, 'run_id').text, '—')
  assert.equal(row(ref, 'formula').href, '/methods#ndci')
  assert.equal(row(refForSiteField(FEATURE, 'index_values.2bda'), 'formula').text, '2bda')
  // A real 0.0 cloud fraction stays 0.
  assert.equal(row(refForSiteField(FEATURE, 'cloud_fraction'), 'value').text, '0')
  const lat = refForSiteField(FEATURE, 'lat')
  assert.equal(lat.field, 'features[site_id=bangsaen].geometry.coordinates[1]')
  assert.equal(row(lat, 'value').text, '13.26')
  assert.equal(row(refForSiteField(FEATURE, 'lng'), 'value').text, '100.88')
})

test('refForRasterField: /raster-scan, run and the scene-date span', () => {
  const ref = refForRasterField(RASTER, 'coverage.measured_fraction')
  assert.equal(ref.endpoint, '/raster-scan')
  assert.equal(row(ref, 'value').text, '0.642290001011268')
  assert.equal(row(ref, 'run_id').text, '6')
  assert.equal(row(ref, 'observed_date').text, '2026-09-29–2026-10-07')
  assert.equal(row(ref, 'unit').textKey, 'unit.fraction')
  const one = refForRasterField({ ...RASTER, oldest_scene_date: '2026-10-07' }, 'cell_count')
  assert.equal(row(one, 'observed_date').text, '2026-10-07')
  assert.equal(row(refForRasterField(null, 'run_id'), 'value').text, '—')
})

test('every source label and unit key is translated in both languages', () => {
  missingKeys.clear()
  for (const lang of ['th', 'en']) {
    const t = createT(lang)
    for (const id of SOURCE_ROW_IDS) t(`source.${id}`)
    for (const u of ['dimensionless', 'count', 'fraction']) t(`unit.${u}`)
  }
  assert.equal(missingKeys.size, 0, [...missingKeys].join(', '))
})
