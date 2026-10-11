/**
 * Pins on the raster map: the rail's list, the markers, the legend wording
 * and the page structure that keeps control clicks off the map.
 *
 *   - PinList rows are real buttons, in rank order, keyboard-focusable, with
 *     the selected row marked; a failed request shows its status and the
 *     server's reason, never "no pins";
 *   - markers are drawn only for the pins of the run shown, numbered, in
 *     the mode's shape, and not at all when "Show highlights" is off;
 *   - no pin or legend string mentions risk except in the negation "not a
 *     risk level" / "ไม่ใช่ระดับความเสี่ยง", in either language;
 *   - nothing reads `risk_tier`;
 *   - on the page, every control sits outside the Leaflet container, so no
 *     control click can reach the map's click handler (the pixel request).
 *
 * Markup renders through a Vite SSR loader with the `leaflet` alias
 * fixtures (real leaflet needs `window`).
 */
import test, { before, after } from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'
import react from '@vitejs/plugin-react'

import en from '../src/i18n/en.js'
import th from '../src/i18n/th.js'
import { buildPinsModel } from '../src/lib/mapModel.js'
import { HIGHLIGHTS_ANOMALY, HIGHLIGHTS_NDCI, RASTER } from './fixtures/map_payloads.js'

let server
let PinList
let HighlightPins
let PinLegend
let RasterPage
let StaticLangProvider
let setResponses

before(async () => {
  server = await createServer({
    configFile: false,
    plugins: [react()],
    cacheDir: 'node_modules/.vite-pins-tests',
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true, watch: null, hmr: false, ws: false },
    resolve: { alias: {
      'react-leaflet': fileURLToPath(new URL('./fixtures/leaflet.js', import.meta.url)),
      leaflet: fileURLToPath(new URL('./fixtures/leaflet_core.js', import.meta.url)),
      '../hooks/useApi.js': fileURLToPath(new URL('./fixtures/useApi.js', import.meta.url)),
    } },
  })
  ;({ default: PinList } = await server.ssrLoadModule('/src/components/PinList.jsx'))
  ;({ default: HighlightPins } = await server.ssrLoadModule('/src/components/HighlightPins.jsx'))
  ;({ default: PinLegend } = await server.ssrLoadModule('/src/components/PinLegend.jsx'))
  ;({ default: RasterPage } = await server.ssrLoadModule('/src/pages/RasterPage.jsx'))
  ;({ StaticLangProvider } = await server.ssrLoadModule('/src/i18n/LangContext.jsx'))
  ;({ setResponses } = await server.ssrLoadModule('/tests/fixtures/useApi.js'))
})

after(async () => server?.close())

const inLang = (lang, element) => renderToStaticMarkup(createElement(StaticLangProvider, { lang }, element))
const visible = (html) => html.replace(/<[^>]+>/g, ' ').replace(/&#x27;/g, "'").replace(/&quot;/g, '"')
  .replace(/&amp;/g, '&').replace(/\s+/g, ' ')
const model = (highlights, extra = {}) => buildPinsModel({ highlights, request: {}, runId: highlights.run_id, n: 5, ...extra })

test('PinList: one focusable button per pin, in rank order, the selected one pressed', () => {
  const reversed = { ...HIGHLIGHTS_ANOMALY, pins: [...HIGHLIGHTS_ANOMALY.pins].reverse() }
  const html = inLang('en', createElement(PinList, { pins: model(reversed), selectedRank: 2, onSelect() {} }))
  const ranks = [...html.matchAll(/<li data-pin="(\d+)"/g)].map((m) => Number(m[1]))
  assert.deepEqual(ranks, [1, 2, 3])
  const buttons = [...html.matchAll(/<button type="button" class="pw-map-pin-row"([^>]*)>/g)]
  assert.equal(buttons.length, 3, 'each row is a real button (Tab, Enter, Space)')
  assert.ok(buttons.every((b) => !/tabindex="-1"/.test(b[1])), 'no row is taken out of the Tab order')
  assert.deepEqual(buttons.map((b) => /aria-pressed="true"/.test(b[1])), [false, true, false])
  assert.match(buttons[0][1], /aria-label="Show pin 1 in the inspector and on the map"/)
  const text = visible(html)
  assert.ok(text.includes(en.map.pins.legend_anomaly))
  assert.ok(text.includes('Anomaly vs own history: high (TEST)'))
  assert.ok(text.includes('14.34'), 'robust z as the API sent it')
  assert.ok(text.includes(en.map.pin.caveat))
  assert.ok(text.includes(en.map.counts.heading_anomaly))
})

test('PinList: a failed request shows its status and the server reason, never "no pins"', () => {
  const conflict = { response: { status: 409, data: { detail: { reason: 'mode_off', message: 'anomaly mode needs BASELINE_MODE=test' } } } }
  const pins = buildPinsModel({ runId: 6, n: 5, request: { error: conflict } })
  for (const [lang, dict] of [['en', en], ['th', th]]) {
    const text = visible(inLang(lang, createElement(PinList, { pins, onRetry() {} })))
    assert.ok(text.includes(dict.map.pins.error))
    assert.ok(text.includes('HTTP 409'))
    assert.ok(text.includes('mode_off'), 'the machine reason is shown')
    assert.ok(text.includes('anomaly mode needs BASELINE_MODE=test'), 'the server message, verbatim')
    assert.ok(!text.includes(dict.map.pins.none), `${lang}: an error read as "no pins"`)
    assert.doesNotMatch(text, /map\.[a-z_.]+/, `${lang}: a raw key leaked`)
  }
})

test('PinList: an empty result states the server reason and the counts', () => {
  const pins = model({ ...HIGHLIGHTS_ANOMALY, pins: [], reason: 'no cells meet the condition (0 assessable of 10 measured)' })
  const text = visible(inLang('en', createElement(PinList, { pins })))
  assert.ok(text.includes(en.map.pins.none))
  assert.ok(text.includes('no cells meet the condition (0 assessable of 10 measured)'))
  assert.ok(text.includes(en.map.counts.assessable))
})

test('markers: numbered, in the mode\'s shape, for the run shown; none when hidden', () => {
  const html = inLang('en', createElement(HighlightPins, { pins: model(HIGHLIGHTS_ANOMALY), selectedRank: 1, onSelect() {} }))
  const markers = [...html.matchAll(/data-pin-marker="([^"]+)"[^>]*data-pin-title="([^"]+)"[^>]*data-pin-icon="([^"]*)"/g)]
  assert.equal(markers.length, 3)
  const [lat, lng] = markers[0][1].split(',').map(Number)
  assert.deepEqual([lat, lng], [HIGHLIGHTS_ANOMALY.pins[0].pixel_centre_lat, HIGHLIGHTS_ANOMALY.pins[0].pixel_centre_lng])
  assert.equal(markers[0][2], 'Pin 1')
  assert.match(markers[0][3], /data-shape=&quot;diamond&quot; data-selected=&quot;true&quot;&gt;&lt;span&gt;1&lt;/)
  assert.doesNotMatch(markers[1][3], /data-selected/)
  const ndci = inLang('en', createElement(HighlightPins, { pins: model(HIGHLIGHTS_NDCI) }))
  assert.match(ndci, /data-shape=&quot;square&quot;/)
  assert.doesNotMatch(ndci, /diamond/, 'the two pin kinds never share a marker shape')
  assert.equal(inLang('en', createElement(HighlightPins, { pins: model(HIGHLIGHTS_NDCI, { show: false }) })), '')
  assert.equal(inLang('en', createElement(HighlightPins, { pins: buildPinsModel({ runId: 7, highlights: HIGHLIGHTS_NDCI }) })), '')
})

test('PinLegend: the mode\'s legend entry, and none for a mode this UI does not know', () => {
  assert.ok(visible(inLang('en', createElement(PinLegend, { mode: 'ndci' }))).includes('Highest NDCI in this scan (rank within one image) — not a risk level'))
  assert.ok(visible(inLang('th', createElement(PinLegend, { mode: 'anomaly' }))).includes(th.map.pins.legend_anomaly))
  assert.equal(inLang('en', createElement(PinLegend, { mode: 'tier' })), '')
})

// ------------------------------------------------------------ wording

function flatten(obj, prefix = '', out = new Map()) {
  for (const [k, v] of Object.entries(obj)) {
    const key = prefix ? `${prefix}.${k}` : k
    if (v !== null && typeof v === 'object') flatten(v, key, out)
    else out.set(key, v)
  }
  return out
}

test('no pin or legend string mentions risk except in the negation "not a risk level"', () => {
  const NEGATION = { en: /not a risk level/g, th: /ไม่ใช่ระดับความเสี่ยง/g }
  const groups = ['map.pins.', 'map.pin.', 'map.legend.', 'map.counts.', 'map.anomaly.', 'overview.pins.', 'overview.map.legend_']
  let checked = 0
  for (const [lang, dict] of [['en', en], ['th', th]]) {
    for (const [key, value] of flatten(dict)) {
      if (!groups.some((g) => key.startsWith(g))) continue
      checked += 1
      const rest = value.replace(NEGATION[lang], '')
      assert.doesNotMatch(rest, /risk|เสี่ยง/i, `${lang}:${key} mentions risk outside the negation: ${value}`)
    }
  }
  assert.ok(checked > 100, 'the pin and legend strings were found')
})

test('no pin component reads a risk tier, and none uses a risk colour token', async () => {
  for (const file of [
    '../src/components/HighlightPins.jsx', '../src/components/PinList.jsx', '../src/components/PinLegend.jsx',
    '../src/components/RasterRail.jsx', '../src/components/SceneDateChart.jsx', '../src/pages/RasterPage.jsx',
    '../src/lib/mapModel.js',
  ]) {
    const source = await readFile(new URL(file, import.meta.url), 'utf8')
    assert.doesNotMatch(source, /\.risk_tier|\[['"]risk_tier['"]\]|risk_level/, `${file} reads a risk field`)
    assert.doesNotMatch(source, /risk-(normal|elevated|watch|warning)|RISK_COLOR|--risk-/, `${file} uses a risk token`)
  }
})

// ---------------------------------------------------------------- page

test('the map page: rail, truth bar and inspector sit outside the Leaflet container', () => {
  setResponses({ getRasterScan: { data: RASTER }, fetchHighlights: { data: HIGHLIGHTS_ANOMALY } })
  try {
    const html = inLang('en', createElement(RasterPage))
    const mapStart = html.indexOf('<main class="leaflet-map')
    const mapEnd = html.indexOf('</main>', mapStart)
    assert.ok(mapStart > 0 && mapEnd > mapStart, 'the map container rendered')
    const inside = html.slice(mapStart, mapEnd)
    // Pins are drawn on the map; no control is a child of it.
    assert.equal((inside.match(/data-pin-marker=/g) ?? []).length, 3)
    assert.doesNotMatch(inside, /<button|<select|<input|<details|<a /, 'a control inside the map would reach its click handler')
    // 2026-10 glass restyle: a fresh visit opens on the run's own true-colour
    // composite when the run stored one (RASTER does), not on NDCI.
    assert.match(inside, /data-overlay-url="[^"]*true-color\.png\?run_id=6"/)
    const outside = html.slice(0, mapStart) + html.slice(mapEnd)
    assert.match(outside, /class="pw-map-rail"/)
    assert.match(outside, /class="pw-map-truth"/)
    assert.match(outside, /class="pw-map-inspector"[^>]*aria-live="polite"/)
    assert.match(outside, /data-layer-mode="true_color"[^>]*aria-pressed="true"/)
    assert.match(outside, /class="pw-map-dock"/, 'the layer switch and legend float in the bottom dock')
    assert.match(outside, /class="pw-map-topline"/)
    const text = visible(html)
    assert.equal((html.match(/<h1/g) ?? []).length, 1)
    assert.ok(text.includes(en.map.truthbar.label))
    assert.ok(text.includes(en.map.pins.legend_anomaly))
    // True Color: the no-data caption, not the NDCI colour bar.
    assert.ok(text.includes(en.map.legend.transparent))
    assert.ok(!text.includes(en.glass.scale.lower), 'the NDCI bar is shown only in the NDCI layer')
    assert.ok(text.includes('Newest Sentinel-2 acquisition 2026-10-07'), 'the acquisition pill from newest_scene_date')
    assert.ok(text.includes('20260927T033541_20260927T034657_T47PQR'), 'a selected scene id is listed')
    assert.ok(text.includes(en.overview.scene.used.split('{')[0].trim()), 'the latest-scene line as on the Overview')
    assert.ok(text.includes(RASTER.disclaimer), 'the truth bar quotes the server disclaimer')
    assert.doesNotMatch(text, /\bmap\.[a-z_]+\.[a-z_.]+/, 'a raw key leaked')
  } finally {
    setResponses({})
  }
})

test('the map page in Thai: the rail, banner and legend follow the language', () => {
  setResponses({ getRasterScan: { data: RASTER }, fetchHighlights: { data: HIGHLIGHTS_NDCI } })
  try {
    const thText = visible(inLang('th', createElement(RasterPage)))
    // run 1's pins do not belong to run 6: said, not drawn.
    assert.ok(thText.includes('หมุดที่ได้รับเป็นของรอบสแกน 1'))
    // Default layer is True Color (2026-10): the legend dock shows the
    // no-data caption in the page's language.
    assert.ok(thText.includes(th.map.legend.transparent))
    assert.ok(thText.includes(th.map.rail.coverage))
    const enText = visible(inLang('en', createElement(RasterPage)))
    assert.ok(enText.includes(en.map.legend.transparent))
    assert.ok(enText.includes(en.map.rail.coverage))
    assert.ok(!enText.includes(th.map.legend.transparent), 'the English page shows no Thai legend')
  } finally {
    setResponses({})
  }
})
