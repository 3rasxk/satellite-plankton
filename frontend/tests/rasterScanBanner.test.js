/**
 * The raster scan banner: what the picture on screen is, in words.
 *
 * These tests are about claims, not layout. The banner is the only place
 * a viewer is told that one raster mixes acquisitions unevenly, that a
 * quarter of the study area carries a reading and the rest does not,
 * that a 200 m cell is a single sampled 10 m pixel rather than an
 * average, and that no anomaly statistic exists. Each of those is a
 * sentence that would be an overclaim if it were dropped, softened, or
 * invented, so each is asserted on the rendered markup.
 *
 * The payloads below are the shape `GET /raster-scan` really serves
 * (backend/src/schemas.py's RasterScanResponse), with synthetic values
 * chosen to exercise uneven date shares and missing metadata.
 */
import test, { before, after } from 'node:test'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'
import react from '@vitejs/plugin-react'

let server
let RasterScanBanner
let RasterPage
let setResponses

before(async () => {
  server = await createServer({
    configFile: false,
    plugins: [react()],
    cacheDir: 'node_modules/.vite-raster-banner-tests',
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true, watch: null, hmr: false, ws: false },
    resolve: { alias: {
      'react-leaflet': fileURLToPath(new URL('./fixtures/leaflet.js', import.meta.url)),
      leaflet: fileURLToPath(new URL('./fixtures/leaflet_core.js', import.meta.url)),
      '../hooks/useApi.js': fileURLToPath(new URL('./fixtures/useApi.js', import.meta.url)),
    } },
  })
  ;({ default: RasterScanBanner } = await server.ssrLoadModule('/src/components/RasterScanBanner.jsx'))
  ;({ default: RasterPage } = await server.ssrLoadModule('/src/pages/RasterPage.jsx'))
  ;({ setResponses } = await server.ssrLoadModule('/tests/fixtures/useApi.js'))
})

after(async () => server?.close())

const DISCLAIMER =
  'Satellite index values describe water colour at pixel resolution. ' +
  'Small or scattered blooms may not be visible.'

// Synthetic example, not a captured live response. Candidate scenes
// and contributing days deliberately have different counts.
const SCAN = {
  run_id: 12,
  status: 'ok',
  date_used: '2026-09-08',
  scale_m: 200,
  cell_count: 97884,
  scene_count: 24,
  oldest_scene_date: '2026-08-28',
  newest_scene_date: '2026-09-07',
  scene_dates: [
    { date: '2026-09-07', cells: 59709, share: 0.61 },
    { date: '2026-09-04', cells: 19577, share: 0.2 },
    { date: '2026-08-28', cells: 18598, share: 0.19 },
  ],
  completed_at: '2026-09-08T04:12:00+00:00',
  coverage: { measured_fraction: 0.257, measured_pixels: 86311, polygon_pixels: 335840 },
  bounds: [[12.5, 99.9], [13.6, 101.0]],
  overlay_url: '/raster-scan/overlay.png',
  stale_run_id: null,
  reason: null,
  disclaimer: DISCLAIMER,
}

const render = (data, props = {}) =>
  renderToStaticMarkup(createElement(RasterScanBanner, { data, ...props }))


test('every acquisition day is shown with its own share, not just the range', () => {
  const html = render(SCAN)
  for (const entry of SCAN.scene_dates) {
    assert.ok(html.includes(entry.date), `day ${entry.date} is missing from the breakdown`)
    assert.ok(
      html.includes(`${(entry.share * 100).toFixed(1)}%`),
      `day ${entry.date} is shown without its share -- the range alone hides it`,
    )
  }
  // The span is still stated; the breakdown is in addition to it.
  assert.ok(html.includes('2026-08-28') && html.includes('2026-09-07'))
  assert.match(html, /59,709 เซลล์/)
})

test('the day most of the raster came from is named, which a date range cannot do', () => {
  const html = render(SCAN)
  assert.match(html, /วันที่ให้เซลล์มากที่สุดคือ/)
  assert.match(html, /61\.0% ของเซลล์ทั้งหมด/)
  assert.match(html, /เซลล์ที่เก็บไว้มีวันที่ถ่ายภาพ 3 วัน/)
  assert.match(html, /ภาพที่นำมาพิจารณา 24 ภาพ/)
  assert.doesNotMatch(html, /24 ภาพถ่าย ใน 3 วัน/)
})

test('one contributing day is not described as multiple acquisition days', () => {
  const html = render({ ...SCAN, scene_dates: [
    { date: '2026-09-07', cells: 97884, share: 1 },
  ] })
  assert.match(html, /เซลล์ที่เก็บไว้มีวันที่ถ่ายภาพ 1 วัน/)
  assert.doesNotMatch(html, /หลายวันถ่ายภาพ/)
})

test('native 20 m sampling does not invent a coarsening ratio for 20 m bands', () => {
  const html = render({ ...SCAN, scale_m: 20 })
  assert.match(html, /1 ใน 4 พิกเซลของแบนด์ 10 ม\./)
  assert.doesNotMatch(html, /null|undefined|1 ใน 0/)
})

test('the shares are the API\'s own, not recomputed in the browser', () => {
  // Deliberately inconsistent: if the banner divided cells by the total
  // itself it would show 0.1% and 99.9% here. It must show what the run
  // recorded, and it must find the real maximum rather than trusting the
  // order the array happens to arrive in.
  const html = render({
    ...SCAN,
    scene_dates: [
      { date: '2026-09-04', cells: 1, share: 0.39 },
      { date: '2026-09-07', cells: 999, share: 0.61 },
    ],
  })
  assert.ok(html.includes('61.0%') && html.includes('39.0%'))
  assert.ok(!html.includes('99.9'), 'the banner recomputed a share from cell counts')
  assert.match(
    html,
    /วันที่ให้เซลล์มากที่สุดคือ.*2026-09-07/s,
    'the dominant day was taken from array order rather than from the counts',
  )
})

test('a run with no recorded breakdown says so and never implies an even spread', () => {
  const html = render({ ...SCAN, scene_dates: null })
  assert.match(html, /ไม่ได้บันทึกสัดส่วนเซลล์รายวัน/)
  assert.match(html, /ไม่ได้แปลว่ากระจายเท่า ๆ กัน/)
  assert.ok(!html.includes('raster-scan-day-list'), 'an empty day list was still drawn')
})

test('coverage names its denominator: the polygon, land included -- not water', () => {
  const html = render(SCAN)
  assert.match(html, /25\.7% ของพื้นที่ในกรอบพื้นที่ศึกษา/)
  // The complement is stated outright rather than left to subtraction.
  assert.match(html, /74\.3% ไม่มีค่าอ่าน/)
  assert.match(html, /รวมแผ่นดินที่อยู่ในกรอบ/)
  assert.match(html, /ไม่ใช่สัดส่วนของ [“"]พื้นน้ำ[”"]/)
  assert.match(html, /86,311 จาก 335,840/)
})

test('unmeasured area is never described as a low reading', () => {
  const html = render(SCAN)
  assert.match(html, /เมฆบัง แผ่นดิน หรือไม่มีภาพครอบคลุม/)
  assert.match(html, /ไม่ใช่ค่าดัชนีต่ำ/)
  assert.match(html, /ไม่ใช่ค่าศูนย์/)
})

test('coverage with no pixel count still states the percentage and its denominator', () => {
  // An overlay drawn before the count was recorded serves a real
  // fraction and a null count. The claim survives; only the supporting
  // parenthetical goes.
  const html = render({
    ...SCAN,
    coverage: { measured_fraction: 0.257, measured_pixels: null, polygon_pixels: 335840 },
  })
  assert.match(html, /25\.7% ของพื้นที่ในกรอบพื้นที่ศึกษา/)
  assert.match(html, /รวมแผ่นดินที่อยู่ในกรอบ/)
  assert.ok(!html.includes('335,840'), 'a pixel count was shown for a run that recorded none')
})

test('no coverage recorded means no coverage number is invented', () => {
  const html = render({ ...SCAN, coverage: null })
  assert.match(html, /ไม่ได้บันทึกสัดส่วนพื้นที่ที่วัดได้/)
  assert.ok(
    !html.includes('ของพื้นที่ในกรอบพื้นที่ศึกษา'),
    'a coverage percentage appeared for a run that recorded none',
  )
})

test('a cell is stated as one sampled pixel and is never called an average', () => {
  const html = render(SCAN)
  assert.match(html, /พิกเซลจริง 1 พิกเซล/)
  assert.match(html, /nearest neighbour/)
  assert.match(html, /1 ใน 400 พิกเซลของแบนด์ 10 ม\./)
  assert.match(html, /1 ใน 100 ของแบนด์ 20 ม\./)
  // Neither overstated as an average nor understated as "a sample of the
  // area": every mention of an average here is a denial of one.
  const mentions = [...html.matchAll(/ค่าเฉลี่ย/g)]
  assert.ok(mentions.length > 0, 'the banner never addresses the averaging misreading at all')
  for (const mention of mentions) {
    assert.ok(
      html.slice(Math.max(0, mention.index - 40), mention.index).includes('ไม่ใช่'),
      'the banner describes a cell as an average somewhere',
    )
  }
  // The consequence, which is the part that actually changes a reading.
  assert.match(html, /เก็บมาทั้งก้อนหรือพลาดไปทั้งก้อน/)
})

test('the sampling ratio follows the run\'s own scale rather than a hardcoded 200 m', () => {
  const html = render({ ...SCAN, scale_m: 100 })
  assert.match(html, /ทุกระยะ 100 ม\./)
  assert.match(html, /1 ใน 100 พิกเซลของแบนด์ 10 ม\./)
  assert.match(html, /1 ใน 25 ของแบนด์ 20 ม\./)
  assert.ok(!html.includes('1 ใน 400'), 'the 200 m ratio was hardcoded')
})

test('no anomaly statistic, no risk level, no verdict', () => {
  const html = render(SCAN)
  assert.match(html, /ยังไม่มีการคำนวณค่าความผิดปกติ/)
  assert.match(html, /index values only — no anomaly detection active/)
  assert.match(html, /ไม่มีคำตัดสินว่าพบหรือไม่พบสาหร่าย/)
  assert.doesNotMatch(html, /ความเสี่ยงสูง|เสี่ยงมาก|risk level/i)
})

test('a stale run says the picture is older than the newest attempt', () => {
  const html = render({ ...SCAN, stale_run_id: 13 })
  assert.match(html, /มีรอบสแกนใหม่กว่า \(รอบที่ 13\)/)
  assert.match(html, /เป็นของรอบที่ 12 ซึ่งเก่ากว่ารอบล่าสุด/)
})

test('nothing claims staleness when the served run is the newest one', () => {
  const html = render(SCAN)
  assert.doesNotMatch(html, /เก่ากว่ารอบล่าสุด/)
})

test('the target date is labelled as not the date of the data, with the imagery\'s age', () => {
  const html = render(SCAN)
  assert.match(html, /วันที่เป้าหมายการสแกน/)
  assert.match(html, /2026-09-07<\/span> \(ก่อนวันเป้าหมาย 1 วัน\)/)
  assert.match(html, /2026-08-28<\/span> \(ก่อนวันเป้าหมาย 11 วัน\)/)
  assert.match(html, /วันที่เป้าหมายไม่ใช่วันที่ของข้อมูล/)
  // When the run was taken, stated as a date rather than as an age --
  // an age would be measured against the viewer's clock and would drift
  // away from every other figure in the banner.
  assert.match(html, /รอบนี้สแกนเมื่อ <span class="mono">2026-09-08<\/span> \(UTC\)/)
})

test('before any scan the reason is shown and no date or share is invented', () => {
  const html = render({
    run_id: null, status: null, date_used: null, scene_dates: null, coverage: null,
    reason: 'No raster overlay has been rendered yet.', disclaimer: DISCLAIMER,
  })
  assert.match(html, /No raster overlay has been rendered yet\./)
  assert.doesNotMatch(html, /\d{4}-\d{2}-\d{2}/, 'a date was shown for a scan that never ran')
  assert.doesNotMatch(html, /%/, 'a percentage was shown for a scan that never ran')
})

test('a failed load is not reported as an absence of algae', () => {
  const html = render(null, { error: new Error('network'), onRefresh() {} })
  assert.match(html, /โหลดภาพแรสเตอร์ไม่สำเร็จ/)
  assert.match(html, /ไม่ได้แปลว่าไม่พบสาหร่าย/)
  assert.match(html, /โหลดผลล่าสุด/)
})

test('the raster page shows the banner in place of its old one-line status', () => {
  setResponses({ getRasterScan: { data: SCAN } })
  const html = renderToStaticMarkup(createElement(RasterPage))
  assert.match(html, /raster-scan-banner/)
  assert.ok(!html.includes('raster-status'), 'the replaced inline status block is still rendered')
  // The three claims the old block could not make.
  assert.match(html, /61\.0% ของเซลล์ทั้งหมด/)
  assert.match(html, /25\.7% ของพื้นที่ในกรอบพื้นที่ศึกษา/)
  assert.match(html, /พิกเซลจริง 1 พิกเซล/)
  setResponses({})
})
