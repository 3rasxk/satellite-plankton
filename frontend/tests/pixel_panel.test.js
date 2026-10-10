/**
 * The cell inspector (RasterPixelPanel) with its provenance upgrade:
 *   - the TEST anomaly block and every "(TEST)" label appear only when the
 *     response carries `anomaly` -- a cell without one says no anomaly
 *     assessment was returned and shows no TEST wording;
 *   - a z the server did not compute is "—" with the server's reason, never
 *     a number;
 *   - each index links to its definition on /methods and has a source chip;
 *     the observed pixel and the drawn square's centre are both stated; the
 *     run, the read scale and the one-sampled-pixel statement are there;
 *   - the four actions exist in every state: Copy citation, Copy permalink,
 *     Download cell CSV, Open raw JSON (the exact API request);
 *   - English renders with no raw keys.
 * The older claims (unmeasured is never a number, three states kept apart)
 * stay in tests/rasterPixel.test.js.
 */
import test, { before, after } from 'node:test'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'
import react from '@vitejs/plugin-react'

import en from '../src/i18n/en.js'
import th from '../src/i18n/th.js'
import { PIXEL_TEST } from './fixtures/map_payloads.js'

let server
let RasterPixelPanel
let StaticLangProvider

before(async () => {
  server = await createServer({
    configFile: false,
    plugins: [react()],
    cacheDir: 'node_modules/.vite-pixel-panel-tests',
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true, watch: null, hmr: false, ws: false },
    resolve: { alias: {
      'react-leaflet': fileURLToPath(new URL('./fixtures/leaflet.js', import.meta.url)),
      leaflet: fileURLToPath(new URL('./fixtures/leaflet_core.js', import.meta.url)),
    } },
  })
  ;({ default: RasterPixelPanel } = await server.ssrLoadModule('/src/components/RasterPixelPanel.jsx'))
  ;({ StaticLangProvider } = await server.ssrLoadModule('/src/i18n/LangContext.jsx'))
})

after(async () => server?.close())

const render = (props, lang) => {
  const panel = createElement(RasterPixelPanel, props)
  return renderToStaticMarkup(lang ? createElement(StaticLangProvider, { lang }, panel) : panel)
}
const visible = (html) => html.replace(/<[^>]+>/g, ' ').replace(/&#x27;/g, "'").replace(/&quot;/g, '"')
  .replace(/&amp;/g, '&').replace(/\s+/g, ' ')

const WITHOUT_ANOMALY = { ...PIXEL_TEST, anomaly: null }
const NOT_ASSESSED = {
  ...PIXEL_TEST,
  anomaly: { ...PIXEL_TEST.anomaly, robust_z: null, level: null, reason: 'too_old' },
}

test('the anomaly block and its TEST label render only when the cell has an anomaly', () => {
  for (const [lang, dict] of [['en', en], ['th', th]]) {
    const withHtml = render({ pixel: PIXEL_TEST }, lang)
    const withText = visible(withHtml)
    assert.match(withHtml, /data-test-block="true"/)
    assert.ok(withText.includes(dict.map.anomaly.heading))
    assert.ok(withText.includes('(TEST)'))
    assert.ok(withText.includes(dict.status.anomaly_normal_test), `${lang}: the level chip carries TEST`)
    assert.ok(withText.includes('1.42'), 'robust z as the API sent it')
    assert.ok(withText.includes('0.0399'), 'baseline median')
    assert.ok(withText.includes('0.0273'), 'baseline MAD')
    assert.ok(withText.includes('45'), 'independent dates')
    assert.ok(withText.includes('m10+-1') && withText.includes('TEST-20261009-9fc9a022'))
    assert.ok(withText.includes(dict.map.pin.bands))

    const withoutHtml = render({ pixel: WITHOUT_ANOMALY }, lang)
    const withoutText = visible(withoutHtml)
    assert.doesNotMatch(withoutHtml, /data-test-block/)
    assert.doesNotMatch(withoutText, /TEST/, `${lang}: a TEST label without an anomaly`)
    assert.ok(withoutText.includes(dict.map.cell.no_anomaly))
  }
})

test('a z the server did not compute is "—" with the reason, never a number', () => {
  for (const [lang, dict] of [['en', en], ['th', th]]) {
    const html = render({ pixel: NOT_ASSESSED }, lang)
    const block = html.slice(html.indexOf('data-test-block'))
    const zRow = block.slice(0, block.indexOf('</div>', block.indexOf(dict.map.anomaly.robust_z)) + 6)
    assert.match(zRow, /data-null="true"/)
    assert.ok(visible(zRow).includes('—'))
    assert.ok(visible(zRow).includes(dict.reason.too_old), `${lang}: the reason is stated beside the dash`)
    assert.ok(visible(block).includes('too_old'), 'the server code, verbatim')
    assert.ok(visible(block).includes(dict.status.anomaly_not_assessed_test))
  }
})

test('provenance: definition links, source chips, both coordinates, scale, run', () => {
  const html = render({ pixel: PIXEL_TEST }, 'en')
  for (const anchor of ['ndci', '2bda', '3bda', 'b2_b3_ratio']) assert.match(html, new RegExp(`href="/methods#${anchor}"`))
  assert.ok((html.match(/class="pw-source-btn"/g) ?? []).length >= 9, 'each value has its source chip')
  assert.match(html, /aria-label="Show the source of index_values\.ndci"/)
  const text = visible(html)
  assert.ok(text.includes(en.map.cell.cell), 'observed label')
  assert.ok(text.includes('12.68870°'), 'the observed pixel')
  assert.ok(text.includes(en.map.cell.centre), 'centre label')
  assert.ok(text.includes('12.68952°'), 'the drawn square centre')
  assert.ok(text.includes('2026-10-07 03:54Z'), 'acquired_at in UTC')
  assert.ok(html.includes('200\u00a0m'), 'the read scale, NBSP-joined to its unit')
  assert.ok(text.includes('Each cell is one real nearest-neighbour pixel sampled every ~200 m'))
  assert.ok(text.includes('Run 6'))
  assert.ok(text.includes(PIXEL_TEST.meaning), 'the server meaning, verbatim')
  assert.doesNotMatch(text, /\bmap\.[a-z_]+\.[a-z_.]+/, 'a raw key leaked')
})

test('actions: copy citation, copy permalink, download cell CSV, open raw JSON -- in every state', () => {
  for (const pixel of [PIXEL_TEST, { ...PIXEL_TEST, state: 'not_measured', index_values: null, anomaly: null }]) {
    const html = render({ pixel, permalink: () => 'http://localhost:5173/map?lat=12.69&lng=100.355&run=6' }, 'en')
    const text = visible(html)
    assert.ok(text.includes(en.action.copy_citation))
    assert.ok(text.includes(en.action.copy_permalink))
    assert.ok(text.includes(en.map.cell.download_csv))
    assert.match(html, /<a class="pw-btn[^"]*" href="[^"]*\/raster-scan\/pixel\?lat=12\.69&amp;lng=100\.355&amp;run_id=6" target="_blank"/)
    assert.ok(text.includes(en.action.open_raw_json))
  }
})

test('the default (no provider) is Thai, as before', () => {
  const text = visible(render({ pixel: PIXEL_TEST }))
  assert.ok(text.includes(th.map.cell.title))
  assert.ok(text.includes(th.action.copy_citation))
})
