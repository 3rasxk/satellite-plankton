/**
 * The glass restyle's components, rendered to static markup (no DOM):
 *   - the top bar keeps the five routes in its <nav> and adds the freshness
 *     chip and the help button outside it;
 *   - the reading guide is a labelled modal dialog, three steps, and renders
 *     nothing while closed;
 *   - the segmented tab row has tab/tabpanel semantics;
 *   - on the map, stations are drawn as markers (their API names escaped),
 *     listed as real buttons outside the Leaflet container, and never carry
 *     a risk class;
 *   - the NDCI colour bar says "Lower / Higher NDCI" with the API's domain;
 *   - the station panel shows "—" with a reason for a missing value, the
 *     footer note and the server disclaimer verbatim, and no risk wording,
 *     gauge or "recommended action".
 */
import test, { before, after } from 'node:test'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { createServer } from 'vite'
import react from '@vitejs/plugin-react'

import en from '../src/i18n/en.js'
import th from '../src/i18n/th.js'
import { buildUpdateChip } from '../src/lib/mapListModel.js'
import { HIGHLIGHTS_NDCI, RASTER } from './fixtures/map_payloads.js'

let server
let StaticLangProvider
let NavBar
let ReadingGuide
let Segmented
let RasterPage
let NdciScaleBar
let SiteDetailPanel
let setResponses

before(async () => {
  server = await createServer({
    configFile: false,
    plugins: [react()],
    cacheDir: 'node_modules/.vite-glass-ui-tests',
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true, watch: null, hmr: false, ws: false },
    resolve: { alias: {
      'react-leaflet': fileURLToPath(new URL('./fixtures/leaflet.js', import.meta.url)),
      leaflet: fileURLToPath(new URL('./fixtures/leaflet_core.js', import.meta.url)),
      '../hooks/useApi.js': fileURLToPath(new URL('./fixtures/useApi.js', import.meta.url)),
    } },
  })
  ;({ StaticLangProvider } = await server.ssrLoadModule('/src/i18n/LangContext.jsx'))
  NavBar = (await server.ssrLoadModule('/src/components/ui/NavBar.jsx')).default
  ReadingGuide = (await server.ssrLoadModule('/src/components/ui/ReadingGuide.jsx')).default
  Segmented = (await server.ssrLoadModule('/src/components/ui/Segmented.jsx')).default
  RasterPage = (await server.ssrLoadModule('/src/pages/RasterPage.jsx')).default
  ;({ NdciScaleBar } = await server.ssrLoadModule('/src/components/RasterLegend.jsx'))
  ;({ SiteDetailPanel } = await server.ssrLoadModule('/src/components/MapDetailPanel.jsx'))
  ;({ setResponses } = await server.ssrLoadModule('/tests/fixtures/useApi.js'))
})

after(async () => server?.close())

const render = (element, lang = 'en') => renderToStaticMarkup(
  createElement(MemoryRouter, null, createElement(StaticLangProvider, { lang }, element)),
)
const visible = (html) => html.replace(/<[^>]+>/g, ' ').replace(/&#x27;/g, "'").replace(/&quot;/g, '"')
  .replace(/&amp;/g, '&').replace(/\s+/g, ' ')

const DISCLAIMER = 'Satellite index values describe water colour at pixel resolution. Small or scattered blooms may not be visible.'

function site(id, name, over = {}) {
  return {
    type: 'Feature',
    geometry: { type: 'Point', coordinates: [100.88, 13.26] },
    properties: {
      site_id: id, name, status: 'ok', risk_level: null, stale: false, error: null,
      signal_anomaly_level: 'watch', signal_robust_z: 2.4, signal_anomaly_reason: null,
      index_values: { ndci: 0.0612, '2bda': 1.08, '3bda': null, b2_b3_ratio: 0.9 },
      cloud_fraction: 0.02, actual_date: '2026-10-07', fetched_at: '2026-10-10T14:25:49+00:00',
      true_color_image_url: null, ndci_heatmap_image_url: null, index_used: 'ndci',
      ...over,
    },
  }
}

const RISK_MAP = {
  type: 'FeatureCollection',
  disclaimer: DISCLAIMER,
  baseline: { mode: 'test', valid: true, version: 'TEST-1', reason: null, min_season_dates_by_location: { a: 40 }, min_independent_dates: 35 },
  features: [
    site('a', 'Bang <Saen> & "Co"'),
    site('b', 'Cha-am', { status: 'no_imagery', index_values: null, signal_anomaly_level: null, signal_robust_z: null, signal_anomaly_reason: 'no_imagery', actual_date: null, cloud_fraction: null }),
  ],
}

test('top bar: five routes in the nav; freshness chip and help button outside it', () => {
  const okAt = Date.parse(RASTER.poll.last_poll_ok_at)
  const chip = buildUpdateChip({ raster: RASTER, request: {}, now: okAt + 25 * 60000 })
  const html = render(createElement(NavBar, { status: chip, onHelp() {} }))
  const nav = html.match(/<nav[\s\S]*?<\/nav>/)[0]
  assert.equal((nav.match(/<a /g) ?? []).length, 5, 'only the five routes in the nav')
  const after = html.slice(html.indexOf('</nav>'))
  assert.match(after, /class="pw-updated" data-tone="ok"/)
  assert.ok(visible(after).includes('Updated 25 min ago'))
  assert.match(after, /<button[^>]*class="pw-help-btn"[^>]*aria-label="Open the reading guide"/)
  // No status, no help handler: neither is rendered (the shell supplies both).
  const bare = render(createElement(NavBar))
  assert.doesNotMatch(bare, /pw-updated|pw-help-btn/)
})

test('reading guide: a labelled modal dialog at step 1 of 3; nothing while closed', () => {
  assert.equal(render(createElement(ReadingGuide, { open: false })), '')
  for (const [lang, dict] of [['en', en], ['th', th]]) {
    const html = render(createElement(ReadingGuide, { open: true, onClose() {} }), lang)
    assert.match(html, /role="dialog"[^>]*aria-modal="true"[^>]*aria-labelledby="[^"]+"[^>]*aria-describedby="[^"]+"/)
    const text = visible(html)
    assert.ok(text.includes(dict.guide.steps.colours.title))
    assert.ok(text.includes(dict.guide.progress.replace('{n}', '1').replace('{total}', '3')))
    assert.match(html, new RegExp(`aria-label="${dict.guide.close}"`))
  }
  assert.match(en.guide.steps.colours.body, /not a risk level/)
  assert.match(en.guide.steps.estimates.body, /not a validated forecast|nothing here is a validated forecast/)
})

test('segmented tabs: tablist, one selected tab with tabindex 0, controls its panel', () => {
  const html = render(createElement(Segmented, {
    kind: 'tabs', idBase: 'x', label: 'Views', value: 'b',
    options: [{ value: 'a', label: 'A' }, { value: 'b', label: 'B' }],
  }))
  assert.match(html, /role="tablist" aria-label="Views"/)
  assert.match(html, /role="tab" id="x-tab-b" aria-selected="true" aria-controls="x-panel-b" tabindex="0"/)
  assert.match(html, /role="tab" id="x-tab-a" aria-selected="false" aria-controls="x-panel-a" tabindex="-1"/)
  const toggle = render(createElement(Segmented, { label: 'N', value: 3, options: [{ value: 3, label: '3' }, { value: 4, label: '4' }] }))
  assert.match(toggle, /role="group" aria-label="N"/)
  assert.equal((toggle.match(/aria-pressed="true"/g) ?? []).length, 1)
})

test('map page: stations drawn as markers (names escaped) and listed as buttons outside the map; no risk class', () => {
  setResponses({ getRasterScan: { data: RASTER }, fetchHighlights: { data: { ...HIGHLIGHTS_NDCI, run_id: RASTER.run_id } }, getRiskMap: { data: RISK_MAP } })
  try {
    const html = render(createElement(RasterPage))
    const mapStart = html.indexOf('<main class="leaflet-map')
    const mapEnd = html.indexOf('</main>', mapStart)
    const inside = html.slice(mapStart, mapEnd)
    const icons = [...inside.matchAll(/data-pin-icon="([^"]*)"/g)].map((m) => m[1])
    const siteIcons = icons.filter((h) => h.includes('pw-site-marker'))
    assert.equal(siteIcons.length, 2)
    assert.ok(siteIcons.some((h) => h.includes('data-kind=&quot;no_data&quot;')), 'a station without a reading is the hollow marker')
    // The icon html holds the name escaped once (&lt;Saen&gt;); React then
    // escapes the attribute again (&amp;lt;). A raw "<Saen>" would be markup.
    assert.ok(siteIcons.some((h) => h.includes('Bang &amp;lt;Saen&amp;gt; &amp;amp; &amp;quot;Co&amp;quot;')), 'API text is escaped in the icon html')
    assert.doesNotMatch(inside, /<button|<a /)
    const outside = html.slice(0, mapStart) + html.slice(mapEnd)
    assert.equal((outside.match(/class="pw-map-site-row"/g) ?? []).length, 2)
    const text = visible(html)
    assert.ok(text.includes('1 of 2 stations have an index reading'), 'headline from the real counts')
    assert.ok(text.includes(en.status.anomaly_watch_test), 'the TEST anomaly chip of the station')
    assert.doesNotMatch(html, /risk-(normal|elevated|watch|warning)|class="[^"]*risk/)
    assert.doesNotMatch(text, /Recommended action|risk gauge/i)
  } finally {
    setResponses({})
  }
})

test('NDCI colour bar: Lower / Higher NDCI, the API domain with U+2212, the no-data caption', () => {
  const html = render(createElement(NdciScaleBar, { legend: RASTER.legend }))
  const text = visible(html)
  assert.ok(text.includes(en.glass.scale.lower) && text.includes(en.glass.scale.higher))
  assert.match(text, /≤\s*−0\.05/)
  assert.ok(text.includes(en.map.legend.transparent_strong))
  assert.doesNotMatch(text, /chlorophyll concentration/i, 'the ends are worded as NDCI, not chlorophyll')
  assert.equal(render(createElement(NdciScaleBar, { legend: null })), '')
})

test('station panel: tabs, "—" with a reason, footer note and server disclaimer verbatim; no risk wording', () => {
  for (const [lang, dict] of [['en', en], ['th', th]]) {
    const html = render(createElement(SiteDetailPanel, {
      riskMap: RISK_MAP, riskMapRequest: { loading: false, error: null }, siteId: 'a', methods: null, onClose() {},
    }), lang)
    const text = visible(html)
    assert.match(html, /role="tablist"/)
    assert.match(html, /role="tabpanel"/)
    assert.ok(text.includes(dict.glass.detail.tab_trend) && text.includes(dict.glass.detail.tab_imagery))
    assert.ok(text.includes(dict.glass.detail.footer_note))
    assert.ok(text.includes(DISCLAIMER), `${lang}: the server disclaimer verbatim`)
    assert.ok(text.includes(dict.glass.detail.group_anomaly))
    assert.ok(text.includes(dict.glass.detail.bands_none), 'no band values: "—" with the reason, never 0')
    assert.match(html, /data-null="true"/)
    assert.doesNotMatch(text, /Recommended action|แนะนำให้/)
  }
  const none = visible(render(createElement(SiteDetailPanel, {
    riskMap: RISK_MAP, riskMapRequest: { loading: false, error: null }, siteId: 'b', methods: null, onClose() {},
  })))
  assert.ok(none.includes(en.glass.detail.headline_none))
  assert.ok(!/\b0\.0000\b/.test(none), 'a station without a reading shows no zero index')
})
