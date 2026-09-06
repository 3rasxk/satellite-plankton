import test, { before, after } from 'node:test'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'
import react from '@vitejs/plugin-react'

let server
let RegionalScanLayer
let RegionalScanBanner
let OverviewPage
let setResponses

before(async () => {
  server = await createServer({
    configFile: false,
    plugins: [react()],
    cacheDir: 'node_modules/.vite-regional-tests',
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true, watch: null, hmr: false, ws: false },
    resolve: { alias: {
      'react-leaflet': fileURLToPath(new URL('./fixtures/leaflet.js', import.meta.url)),
      '../hooks/useApi.js': fileURLToPath(new URL('./fixtures/useApi.js', import.meta.url)),
    } },
  })
  ;({ default: RegionalScanLayer } = await server.ssrLoadModule('/src/components/RegionalScanLayer.jsx'))
  ;({ default: RegionalScanBanner } = await server.ssrLoadModule('/src/components/RegionalScanBanner.jsx'))
  ;({ default: OverviewPage } = await server.ssrLoadModule('/src/pages/OverviewPage.jsx'))
  ;({ setResponses } = await server.ssrLoadModule('/tests/fixtures/useApi.js'))
})

after(async () => server?.close())

const markerCount = (html) => (html.match(/data-scan-marker=/g) || []).length
const point = (id, status, index_values = null) => ({
  point_id: id, lat: 13, lng: 100.5, status, index_values,
  actual_date: null, threshold_tier: null, spatial_anomaly_z: null,
})

test('every status renders a pin; null tiers, low indices and cluster membership never hide it', () => {
  const points = [
    point('negative', 'ok', { ndci: -0.8, '2bda': 0.1 }),
    point('zero', 'ok', { ndci: 0 }),
    point('secondary-only', 'ok', { b2_b3_ratio: 1.23 }),
    ...['no_imagery', 'no_water_pixels', 'no_climatology', 'error', 'no_data_yet']
      .map((status) => point(status, status)),
  ]
  const html = renderToStaticMarkup(createElement(RegionalScanLayer, { data: {
    run: { date_used: '2026-09-06' }, points,
    clusters: [{ member_point_ids: ['negative'], cell_count: 1, centroid_lat: 13, centroid_lng: 100.5 }],
  } }))
  assert.equal(markerCount(html), points.length)
  assert.match(html, /-0\.800/)
  assert.match(html, /0\.000/)
  assert.match(html, /1\.230/)
})

test('planned grid renders before a run and does not invent readings or a scene date', () => {
  const points = Array.from({ length: 9119 }, (_, i) => point(String(i), 'no_data_yet'))
  const html = renderToStaticMarkup(createElement(RegionalScanLayer, { data: { run: null, points } }))
  assert.equal(markerCount(html), 9119)
  assert.match(html, /ยังไม่ได้สแกน/)
  assert.doesNotMatch(html, /0\.000|2026-09-06/)
})

test('all four cached indices keep their own actual scene date', () => {
  const measured = { ...point('measured', 'ok', {
    ndci: -0.2, '2bda': 0.5, '3bda': 0.03, b2_b3_ratio: 0.8,
  }), actual_date: '2026-09-01' }
  const html = renderToStaticMarkup(createElement(RegionalScanLayer, { data: {
    run: { date_used: '2026-09-06' }, points: [measured],
  } }))
  for (const [label, value] of [['NDCI', '-0.200'], ['2BDA', '0.500'], ['3BDA', '0.030'], ['B2/B3', '0.800']]) {
    assert.ok(html.includes(`<dt>${label}</dt><dd class="mono">${value}</dd>`))
  }
  assert.match(html, /2026-09-01/)
  assert.doesNotMatch(html, /2026-09-06/)
  assert.match(html, /ก่อนวันเป้าหมาย 5 วัน/)
})

test('retained readings use their snapshot target while a later scan is running', () => {
  const data = {
    run: { status: 'running', date_used: '2026-09-07' },
    snapshot_date_used: '2026-09-06', grid_spacing_km: 5, max_scene_age_days: 14,
    points: [{ ...point('retained', 'ok', { ndci: -0.2 }), actual_date: '2026-08-23' }],
  }
  const layer = renderToStaticMarkup(createElement(RegionalScanLayer, { data }))
  assert.match(layer, /ก่อนวันเป้าหมาย 14 วัน/)
  assert.doesNotMatch(layer, /ก่อนวันเป้าหมาย 15 วัน/)
  const banner = renderToStaticMarkup(createElement(RegionalScanBanner, { data }))
  assert.match(banner, /ข้อมูลที่แสดงมาจากรอบวันที่/)
  assert.match(banner, /2026-09-06/)
  assert.match(banner, /2026-09-07/)
})

test('overview loads regional pins by default independently of the seven-site API', () => {
  setResponses({
    getRiskMap: { error: new Error('Monitoring-site service unavailable') },
    getRegionalScan: { data: { run: null, grid_spacing_km: 5, points: [point('planned', 'no_data_yet')] } },
  })
  const html = renderToStaticMarkup(createElement(OverviewPage))
  assert.equal(markerCount(html), 1)
  assert.doesNotMatch(html, /Show regional scan|ระดับความเสี่ยง|จุดตรวจวัดประจำ|regional-layer-controls/)
})

test('grid counts include missing readings and retain the API interpretation disclaimer', () => {
  const html = renderToStaticMarkup(createElement(RegionalScanBanner, { data: {
    run: { status: 'running', date_used: '2026-09-06' }, grid_spacing_km: 5, max_scene_age_days: 14,
    points: [point('pending', 'no_data_yet'), point('cloud', 'no_imagery'), point('read', 'ok', { ndci: -0.4 })],
    disclaimer: 'Index values alone establish neither bloom presence nor absence.',
  } }))
  assert.match(html, /แสดงทุกจุด 3 จุด/)
  assert.match(html, /มีค่าอ่าน 1 · ยังไม่ได้สแกน 1 · ไม่มีค่าอ่าน 1/)
  assert.match(html, /Index values alone establish neither bloom presence nor absence\./)
  assert.match(html, /no anomaly detection active/)
  assert.match(html, /ไม่เกิน 14 วันก่อนวันเป้าหมาย/)
})
