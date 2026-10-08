/**
 * Clicking a raster cell, and what the panel is allowed to say about it.
 *
 * The point of these tests is the same one the backend suite defends, one
 * layer up: an unmeasured cell must never be shown as a number, and above
 * all never as 0.0 — a masked pixel downloads as 0.0 and 0.0 is also a
 * perfectly real NDCI reading, so a panel that prints one for the other
 * tells a viewer "we looked and saw almost nothing" about water nobody
 * could see. The three states the overlay paints have to survive into
 * words.
 *
 * The panel is rendered from API payloads only — no colours are decoded,
 * no index is recomputed here — so a fixture below is simply a response
 * shaped exactly as backend/src/schemas.py's RasterPixelResponse.
 */
import test, { before, after } from 'node:test'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'
import react from '@vitejs/plugin-react'

let server
let RasterPixelPanel
let RasterPixelProbe

before(async () => {
  server = await createServer({
    configFile: false,
    plugins: [react()],
    cacheDir: 'node_modules/.vite-raster-pixel-tests',
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true, watch: null, hmr: false, ws: false },
    resolve: { alias: {
      'react-leaflet': fileURLToPath(new URL('./fixtures/leaflet.js', import.meta.url)),
      leaflet: fileURLToPath(new URL('./fixtures/leaflet_core.js', import.meta.url)),
    } },
  })
  ;({ default: RasterPixelPanel } = await server.ssrLoadModule(
    '/src/components/RasterPixelPanel.jsx',
  ))
  ;({ default: RasterPixelProbe } = await server.ssrLoadModule(
    '/src/components/RasterPixelProbe.jsx',
  ))
})

after(async () => server?.close())

// A reading, as the API returns one. The float values are what a float32
// blob widens to — deliberately not round numbers, so a panel that
// substituted its own would be obvious.
const READING = {
  state: 'reading',
  meaning: 'index readings at this cell',
  run_id: 12,
  scale_m: 200,
  query_lat: 12.9601,
  query_lng: 100.0402,
  cell_lat: 12.960134,
  cell_lng: 100.040217,
  pixel_centre_lat: 12.96011,
  pixel_centre_lng: 100.04019,
  pixel_row: 214,
  pixel_col: 401,
  index_values: {
    ndci: 0.03150000050663948,
    bda2: 1.1799999475479126,
    bda3: 0.28999999165534973,
    b2_b3: 0.8299999833106995,
  },
  unreadable_bands: [],
  date_ms: 1788492600000,
  acquired_date: '2026-09-04',
  acquired_at: '2026-09-04T03:30:00Z',
}

const NOT_MEASURED = {
  state: 'not_measured',
  meaning:
    'inside the study area, no usable reading here -- cloud, land-masked, or no scene covered it',
  run_id: 12,
  scale_m: 200,
  query_lat: 12.99,
  query_lng: 100.045,
  cell_lat: null,
  cell_lng: null,
  pixel_centre_lat: 12.98998,
  pixel_centre_lng: 100.04502,
  pixel_row: 220,
  pixel_col: 410,
  index_values: null,
  unreadable_bands: [],
  date_ms: null,
  acquired_date: null,
  acquired_at: null,
}

const OUTSIDE = {
  ...NOT_MEASURED,
  state: 'outside_study_area',
  meaning: 'outside the study area -- nothing was looked at here',
  pixel_row: null,
  pixel_col: null,
  pixel_centre_lat: null,
  pixel_centre_lng: null,
}

const panel = (props) => renderToStaticMarkup(createElement(RasterPixelPanel, props))

test('a reading shows all four indices and the value the API sent', () => {
  const html = panel({ pixel: READING })
  for (const label of ['NDCI', '2BDA', '3BDA', 'B2/B3']) {
    assert.ok(html.includes(label), `the panel does not show the ${label} reading`)
  }
  for (const value of Object.values(READING.index_values)) {
    assert.ok(
      html.includes(value.toFixed(4)),
      `the panel does not show ${value.toFixed(4)}, which the API returned`,
    )
  }
})

test("a reading shows THIS cell's own acquisition date, not the run's", () => {
  // One raster routinely mixes acquisition dates: the composite is
  // most-recent-wins per pixel. The panel is given only the cell's own
  // date and must print that.
  const html = panel({ pixel: READING })
  assert.ok(html.includes('2026-09-04'), "the cell's own acquisition date is not shown")
  assert.ok(
    html.includes(READING.cell_lat.toFixed(5)),
    'the sampled pixel\'s own coordinate is not shown',
  )
})

test('unmeasured water is never shown as a number, and never as zero', () => {
  // The whole point. A masked cell downloads as 0.0 and 0.0 is also a
  // real NDCI reading, so printing one digit here would be the project's
  // cardinal overclaim in words.
  const html = panel({ pixel: NOT_MEASURED })
  assert.doesNotMatch(html, /\d\.\d{4}/, 'an index-shaped number appears for an unmeasured cell')
  assert.ok(!html.includes('NDCI'), 'an index label appears for a cell with no reading')
  assert.match(html, /ไม่ได้วัดค่า/)
  assert.match(html, /ไม่ใช่ค่าดัชนีต่ำ/)
  assert.match(html, /ไม่ใช่ค่าศูนย์/)
  assert.match(html, /ทั้งสามสาเหตุแยกจากกันไม่ได้จากข้อมูลที่เก็บไว้ จึงรายงานรวมเป็นสถานะเดียว/)
})

test('unmeasured water and outside the study area are different messages', () => {
  // Both are "no reading here" and they are not the same fact. The map
  // draws them differently; the words have to keep them apart.
  const unmeasured = panel({ pixel: NOT_MEASURED })
  const outside = panel({ pixel: OUTSIDE })
  assert.notEqual(unmeasured, outside)
  assert.match(outside, /นอกพื้นที่ศึกษา/)
  assert.doesNotMatch(outside, /ไม่ใช่ค่าดัชนีต่ำ/)
  assert.doesNotMatch(unmeasured, /นอกพื้นที่ศึกษา/)
})

test('the three causes of an unmeasured cell are not guessed apart', () => {
  // The stored raster keeps only the cells that survived, so it holds no
  // evidence separating cloud from land from no-pass. The panel must name
  // them as alternatives, never pick one.
  const html = panel({ pixel: NOT_MEASURED })
  assert.match(html, /เมฆบัง/)
  assert.match(html, /พื้นดิน/)
  assert.match(html, /ไม่มีภาพถ่ายครอบคลุม/)
})

test('a band that produced no finite number is named, not clamped to a value', () => {
  const html = panel({
    pixel: { ...READING, index_values: { ...READING.index_values, ndci: null },
             unreadable_bands: ['ndci'] },
  })
  assert.match(html, /คำนวณไม่ได้/)
  assert.ok(
    !html.includes('0.0000'),
    'a band with no finite value was shown as zero, which invents a reading',
  )
  // The bands that did produce a number are still shown.
  assert.ok(html.includes(READING.index_values.bda2.toFixed(4)))
})

test('a state this build does not recognise is shown as unmeasured, not as values', () => {
  // The safe direction has to be the default. A future state name
  // rendered through the value table would print whatever index_values
  // held, and for a masked cell that is 0.0.
  const html = panel({ pixel: { ...NOT_MEASURED, state: 'something_added_later' } })
  assert.doesNotMatch(html, /\d\.\d{4}/)
  assert.match(html, /ไม่ได้วัดค่า/)
})

test('the panel says index reading, not risk level', () => {
  const html = panel({ pixel: READING })
  assert.match(html, /ค่าดัชนี/)
  assert.match(html, /ไม่ใช่ระดับความเสี่ยง/)
  assert.doesNotMatch(html, /ความเสี่ยงสูง|เสี่ยงมาก|risk level|anomaly/i)
})

test('a cell is described as one sampled pixel, not an average of its square', () => {
  const html = panel({ pixel: READING })
  assert.match(html, /ไม่ใช่ค่าเฉลี่ย/)
})

test('a failed lookup is not reported as an absence of algae', () => {
  const html = panel({ pixel: null, error: new Error('Request failed with status code 404') })
  assert.match(html, /ไม่ได้แปลว่าไม่พบสาหร่าย/)
  assert.doesNotMatch(html, /\d\.\d{4}/)
})

test('nothing is rendered until something is clicked', () => {
  assert.equal(panel({ pixel: null }), '')
  assert.equal(panel({ pixel: null, loading: false, error: null }), '')
})

test('a map click reports the clicked point in (lat, lng) order', () => {
  // Swapped, a click in the upper Gulf becomes a query off Somalia, the
  // API answers "outside the study area" quite correctly, and nothing on
  // the map looks wrong. So the order is asserted rather than eyeballed.
  const picked = []
  renderToStaticMarkup(createElement(RasterPixelProbe, { onPick: (p) => picked.push(p) }))
  globalThis.__leafletMapHandlers.click({ latlng: { lat: 13.0512, lng: 100.6187 } })
  assert.deepEqual(picked, [{ lat: 13.0512, lng: 100.6187 }])
})

test('the probe draws nothing on the map itself', () => {
  assert.equal(
    renderToStaticMarkup(createElement(RasterPixelProbe, { onPick: () => {} })),
    '',
  )
})
