/**
 * The shared dashboard components (src/components/ui), the language
 * providers, the baseline hook and the 404 page, rendered to static markup.
 *
 * These are claims tests as much as markup tests: an unknown value must
 * read as "—" with its reason and never as 0; a status chip must carry text
 * and an icon, never colour alone, and no risk class; a source popover must
 * restate the provenance rows it was given and invent none; the footer must
 * carry the three truth-boundary points and the server disclaimer verbatim
 * in both languages; the TEST strip must appear only while a valid TEST
 * baseline is in force. The last test greps the new UI and page sources so
 * the four `--risk-*` tokens stay unused (dashboard spec §2 point 5).
 *
 * No DOM: components are rendered with react-dom/server through a Vite SSR
 * loader (JSX transform), as in tests/rasterScanBanner.test.js.
 */
import test, { before, after } from 'node:test'
import assert from 'node:assert/strict'
import { readdir, readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { createServer } from 'vite'
import react from '@vitejs/plugin-react'

import en from '../src/i18n/en.js'
import th from '../src/i18n/th.js'
import { STATUS, ANOMALY_CHIP_KEYS, chipForPixelState, chipForSite, chipForAnomalyLevel } from '../src/lib/statusChip.js'
import { refForPixelField } from '../src/lib/provenance.js'

let server
const ui = {}
let StaticLangProvider
let LangProvider
let useLang
let baselineModule
let NotFoundPage
let App
let PlaceholderPage

before(async () => {
  server = await createServer({
    configFile: false,
    plugins: [react()],
    cacheDir: 'node_modules/.vite-ui-components-tests',
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true, watch: null, hmr: false, ws: false },
  })
  for (const name of [
    'Value', 'StatusChip', 'SourceChip', 'TruthFooter', 'BaselineBanner', 'NavBar', 'LangToggle',
    'FigureFrame', 'CiteButton', 'PageHeader', 'EmptyState', 'ErrorState',
  ]) {
    ui[name] = (await server.ssrLoadModule(`/src/components/ui/${name}.jsx`)).default
  }
  ;({ StaticLangProvider, LangProvider } = await server.ssrLoadModule('/src/i18n/LangContext.jsx'))
  ;({ useLang } = await server.ssrLoadModule('/src/i18n/useLang.js'))
  baselineModule = await server.ssrLoadModule('/src/hooks/useBaseline.js')
  NotFoundPage = (await server.ssrLoadModule('/src/pages/NotFoundPage.jsx')).default
  PlaceholderPage = (await server.ssrLoadModule('/src/pages/PlaceholderPage.jsx')).default
  App = (await server.ssrLoadModule('/src/App.jsx')).default
})

after(async () => server?.close())

const DICTS = { en, th }

/** Visible text of static markup: tags removed, entities decoded. */
function text(html) {
  return html
    .replace(/<[^>]+>/g, ' ')
    .replace(/&quot;/g, '"')
    .replace(/&#x27;|&#39;/g, "'")
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&amp;/g, '&')
    .replace(/\s+/g, ' ')
}

function render(element, { lang = 'en', path = null } = {}) {
  const withLang = createElement(StaticLangProvider, { lang }, element)
  return renderToStaticMarkup(path ? createElement(MemoryRouter, { initialEntries: [path] }, withLang) : withLang)
}

/** Every class attribute value in the markup, joined. */
const classNames = (html) => [...html.matchAll(/class="([^"]*)"/g)].map((m) => m[1]).join(' ')

// The TEST-mode disclaimer GET /methods actually served on 2026-10-10
// (backend running with BASELINE_MODE=test), copied verbatim.
const SERVER_DISCLAIMER =
  'Satellite index values describe water colour at pixel resolution. Small or scattered blooms may not be ' +
  'visible. TEST baseline mode: a Sentinel-2 NDCI reading, at a monitoring site or at a raster cell, may be ' +
  "compared with that same location's own earlier record for the same season. Any resulting anomaly is " +
  'provisional and uncalibrated, has never been checked against recorded bloom events, and is a statistical ' +
  'statement only — not a bloom detection, a species identification, a risk level or a forecast. Index ' +
  'values alone establish neither bloom presence nor absence.'

// ---------------------------------------------------------------- Value

test('Value: null renders "—" with the reason in words, never 0', () => {
  for (const lang of ['en', 'th']) {
    for (const value of [null, undefined, Number.NaN, Number.POSITIVE_INFINITY]) {
      const html = render(createElement(ui.Value, { value, spec: { kind: 'index' } }), { lang })
      const visible = text(html)
      assert.match(visible, /—/)
      assert.ok(visible.includes(DICTS[lang].reason.not_available), `${lang}: reason text missing: ${visible}`)
      assert.doesNotMatch(visible, /\d/, `${lang}: a digit leaked into an unknown value: ${visible}`)
      assert.match(html, /title="[^"]+"/, 'the reason is also a tooltip')
      assert.match(html, /data-null="true"/)
    }
  }
})

test('Value: an API reason code is explained; an unknown code is shown verbatim', () => {
  const known = text(render(createElement(ui.Value, { value: null, spec: { kind: 'index', reason: 'no_imagery' } })))
  assert.ok(known.includes(en.reason.no_imagery), known)
  const unknown = text(render(createElement(ui.Value, { value: null, spec: { kind: 'index', reason: 'mystery_code' } })))
  assert.ok(unknown.includes('mystery_code'), unknown)
  const thai = text(render(createElement(ui.Value, { value: null, spec: { kind: 'index', reason: 'not_measured' } }), { lang: 'th' }))
  assert.ok(thai.includes(th.reason.not_measured), thai)
})

test('Value: a real zero stays 0.000; negatives use U+2212; numbers are tabular', () => {
  const zero = render(createElement(ui.Value, { value: 0, spec: { kind: 'index' } }))
  assert.ok(text(zero).includes('0.000'), zero)
  assert.match(zero, /data-null="false"/)
  assert.doesNotMatch(text(zero), /—/)
  const negative = text(render(createElement(ui.Value, { value: -0.0123, spec: { kind: 'index' } })))
  assert.ok(negative.includes('−0.012'), negative)
  assert.match(zero, /class="[^"]*pw-num[^"]*"/, 'numbers carry the tabular-numeral class')
})

test('Value: with a source ref it renders a SourceChip next to the number', () => {
  const pixel = { query_lat: 13.1, query_lng: 100.9, run_id: 7, acquired_date: '2026-09-30', index_values: { ndci: 0.04 } }
  const html = render(createElement(ui.Value, {
    value: 0.04, spec: { kind: 'index' }, source: refForPixelField(pixel, 'index_values.ndci'),
  }))
  assert.ok(text(html).includes('0.040'))
  assert.match(html, /<button[^>]*aria-expanded="false"/)
})

// ----------------------------------------------------------- StatusChip

function everyChip() {
  const chips = [
    ...['reading', 'not_measured', 'outside_study_area', 'garbage'].map(chipForPixelState),
    ...chipForSite({ status: 'ok', risk_level: null, stale: true }),
    ...chipForSite({ status: 'no_data_yet' }),
    ...chipForSite({ status: 'no_imagery' }),
    ...[null, 'normal', 'watch', 'high'].flatMap((level) => [chipForAnomalyLevel(level, false), chipForAnomalyLevel(level, true)]),
  ]
  const byKey = new Map(chips.map((c) => [c.key, c]))
  return [...byKey.values()]
}

test('StatusChip: every descriptor renders text + icon + data-tone/data-hatch, never a risk class', () => {
  const chips = everyChip()
  const keys = new Set(chips.map((c) => c.key))
  for (const key of [...Object.values(STATUS), ...ANOMALY_CHIP_KEYS]) assert.ok(keys.has(key), `fixture lacks ${key}`)
  for (const lang of ['en', 'th']) {
    for (const chip of chips) {
      const html = render(createElement(ui.StatusChip, { chip }), { lang })
      assert.ok(text(html).includes(DICTS[lang].status[chip.key]), `${lang}:${chip.key}: ${html}`)
      assert.match(html, /<svg[^>]*aria-hidden="true"/, `${chip.key}: icon missing`)
      assert.match(html, new RegExp(`data-tone="${chip.tone}"`))
      assert.match(html, new RegExp(`data-hatch="${chip.hatch}"`))
      assert.match(html, new RegExp(`data-status="${chip.key}"`))
      assert.doesNotMatch(classNames(html), /risk/i, `${chip.key}: risk class in ${html}`)
      assert.doesNotMatch(html, /--risk-|style=/, `${chip.key}: inline colour in ${html}`)
    }
  }
})

test('StatusChip: a missing descriptor reads as "no usable data", never as a reading', () => {
  const html = render(createElement(ui.StatusChip, { chip: null }))
  assert.ok(text(html).includes(en.status.no_usable_data), html)
  assert.doesNotMatch(text(html), new RegExp(en.status.measured))
})

// ----------------------------------------------------------- SourceChip

const PIXEL = {
  query_lat: 13.25, query_lng: 100.85, run_id: 12, acquired_date: '2026-09-30',
  index_values: { ndci: 0.0412, bda2: null },
}

test('SourceChip: a keyboard-focusable button with an accessible name; closed by default', () => {
  const html = render(createElement(ui.SourceChip, { source: refForPixelField(PIXEL, 'index_values.ndci') }))
  assert.match(html, /<button[^>]*type="button"/)
  assert.match(html, /aria-expanded="false"/)
  assert.ok(html.includes('aria-label="Show the source of index_values.ndci"'), html)
  assert.doesNotMatch(html, /role="dialog"/, 'the popover is not rendered until opened')
})

test('SourceChip: the open popover restates the endpoint/field rows and the raw-JSON link, inventing nothing', () => {
  const source = refForPixelField(PIXEL, 'index_values.ndci')
  for (const lang of ['en', 'th']) {
    const html = render(createElement(ui.SourceChip, { source, defaultOpen: true }), { lang })
    const visible = text(html)
    assert.match(html, /aria-expanded="true"/)
    assert.match(html, /role="dialog"/)
    for (const id of ['endpoint', 'field', 'value', 'unit', 'observed_date', 'run_id', 'scene_id', 'formula']) {
      assert.ok(visible.includes(DICTS[lang].source[id]), `${lang}: row label ${id} missing`)
    }
    assert.ok(visible.includes('GET /raster-scan/pixel?lat=13.25&lng=100.85&run_id=12'), visible)
    assert.ok(visible.includes('index_values.ndci'))
    assert.ok(visible.includes('0.0412'), 'the value as returned, unrounded')
    assert.ok(visible.includes(DICTS[lang].unit.dimensionless), 'word units are translated')
    assert.ok(visible.includes('2026-09-30'))
    assert.ok(html.includes(`href="${source.url.replace(/&/g, '&amp;')}"`), 'raw JSON link is the API URL')
    assert.ok(visible.includes(DICTS[lang].action.open_raw_json))
    assert.match(html, /href="\/methods#ndci"/)
  }
  // The scene id is not known for a cell: shown as "—", never filled in.
  const sceneRow = render(createElement(ui.SourceChip, { source, defaultOpen: true }))
    .match(/data-row="scene_id"[\s\S]*?<\/div>/)
  assert.ok(sceneRow && text(sceneRow[0]).includes('—'), String(sceneRow))
})

test('SourceChip: no raw-JSON link when the ref has no URL', () => {
  const html = render(createElement(ui.SourceChip, {
    source: { endpoint: null, field: null, url: null, rows: [] }, defaultOpen: true,
  }))
  assert.doesNotMatch(html, /Open raw JSON/)
  assert.doesNotThrow(() => render(createElement(ui.SourceChip, { source: null, defaultOpen: true })))
})

// ---------------------------------------------------------- TruthFooter

test('TruthFooter: the three binding points and the server disclaimer verbatim, in both languages', () => {
  for (const lang of ['en', 'th']) {
    const d = DICTS[lang]
    const html = render(createElement(ui.TruthFooter, { disclaimer: SERVER_DISCLAIMER, disclaimerSource: '/methods' }), { lang, path: '/' })
    const visible = text(html)
    assert.match(html, /^<footer/)
    for (const key of ['point_1', 'point_2', 'point_3', 'null_rule']) {
      assert.ok(visible.includes(d.truth[key]), `${lang}: truth.${key} missing`)
    }
    assert.ok(!visible.includes(d.truth.point_3_test), 'not the TEST variant outside test mode')
    assert.ok(visible.includes(SERVER_DISCLAIMER), `${lang}: disclaimer not verbatim`)
    assert.ok(visible.includes(d.truth.server_disclaimer), 'labelled as server text')
    assert.ok(visible.includes('GET /methods'), 'names the response it came with')
    assert.match(html, /href="\/methods"/)
    assert.match(html, /href="\/data"/)
    assert.match(visible, /dev/, 'app version / git SHA fall back to "dev" outside a Vite build')
  }
})

test('TruthFooter: the TEST variant of point 3, and an honest line when no disclaimer was received', () => {
  const test3 = text(render(createElement(ui.TruthFooter, { disclaimer: SERVER_DISCLAIMER, isTest: true }), { path: '/' }))
  assert.ok(test3.includes(en.truth.point_3_test))
  assert.ok(!test3.includes(en.truth.point_3))
  for (const lang of ['en', 'th']) {
    const none = text(render(createElement(ui.TruthFooter, { disclaimer: null }), { lang, path: '/' }))
    assert.ok(none.includes(DICTS[lang].truth.no_server_disclaimer), none)
    assert.ok(none.includes(DICTS[lang].truth.point_2))
  }
})

// ------------------------------------------------------- BaselineBanner

const TEST_ON = { status: 'ready', mode: 'test', valid: true, version: 'TEST-20261009-9fc9a022', reason: null, isTest: true }

test('BaselineBanner: renders only while a TEST baseline is in force', () => {
  for (const baseline of [
    null,
    { status: 'loading', mode: null, valid: null, isTest: false },
    { status: 'ready', mode: 'off', valid: null, version: null, isTest: false },
    { status: 'ready', mode: null, valid: null, isTest: false },
  ]) {
    assert.equal(render(createElement(ui.BaselineBanner, { baseline })), '', JSON.stringify(baseline))
  }
  for (const lang of ['en', 'th']) {
    const html = render(createElement(ui.BaselineBanner, { baseline: TEST_ON }), { lang, path: '/' })
    const visible = text(html)
    assert.ok(visible.includes(DICTS[lang].truth.test_banner), `${lang}: ${visible}`)
    assert.ok(visible.includes('TEST-20261009-9fc9a022'))
    assert.match(html, /data-state="test"/)
    assert.match(html, /href="\/methods#baseline"/)
    assert.doesNotMatch(classNames(html), /risk/i)
  }
})

test('BaselineBanner: test mode with an invalid baseline says so with the reason; a failed read says unknown', () => {
  const invalid = render(createElement(ui.BaselineBanner, {
    baseline: { status: 'ready', mode: 'test', valid: false, version: null, reason: 'manifest_missing', isTest: false },
  }), { path: '/' })
  assert.ok(text(invalid).includes(en.banner.test_baseline_invalid.replace('{reason}', 'manifest_missing')), invalid)
  assert.ok(!text(invalid).includes(en.truth.test_banner), 'an invalid baseline is not presented as in force')
  const failed = render(createElement(ui.BaselineBanner, {
    baseline: { status: 'error', mode: null, valid: null, isTest: false },
  }), { lang: 'th', path: '/' })
  assert.ok(text(failed).includes(th.baseline.unknown), failed)
  assert.ok(!text(failed).includes(th.truth.test_banner))
})

// --------------------------------------------------------------- NavBar

const ROUTES = [['/', 'overview'], ['/map', 'map'], ['/sites', 'sites'], ['/methods', 'methods'], ['/data', 'data']]

function navLinks(html) {
  const nav = html.match(/<nav[\s\S]*?<\/nav>/)
  assert.ok(nav, 'a <nav> landmark')
  return [...nav[0].matchAll(/<a ([^>]*)>([\s\S]*?)<\/a>/g)].map(([, attrs, inner]) => ({
    href: attrs.match(/href="([^"]*)"/)?.[1],
    current: /aria-current="page"/.test(attrs),
    label: text(inner).trim(),
  }))
}

test('NavBar: the five routes in both languages, the active one marked aria-current', () => {
  for (const lang of ['en', 'th']) {
    for (const [path, activeKey] of [...ROUTES, ['/sites/bangsaen', 'sites']]) {
      const html = render(createElement(ui.NavBar), { lang, path })
      const links = navLinks(html)
      assert.deepEqual(links.map((l) => l.href), ROUTES.map(([p]) => p))
      assert.deepEqual(links.map((l) => l.label), ROUTES.map(([, k]) => DICTS[lang].nav[k]))
      assert.deepEqual(links.filter((l) => l.current).map((l) => l.href), [ROUTES.find(([, k]) => k === activeKey)[0]],
        `${lang} ${path}`)
      assert.match(html, new RegExp(`aria-label="${DICTS[lang].nav.main_label}"`))
      assert.ok(text(html).includes('Plankton Watch'))
      assert.ok(text(html).includes(DICTS[lang].app.tagline))
    }
  }
})

test('NavBar: an unknown path marks no link current; the menu button reports its state', () => {
  const html = render(createElement(ui.NavBar), { path: '/nope' })
  assert.equal(navLinks(html).filter((l) => l.current).length, 0)
  assert.match(html, /<button[^>]*aria-expanded="false"[^>]*aria-controls="[^"]+"/)
})

test('LangToggle: a labelled group of two buttons, the current language pressed', () => {
  for (const lang of ['en', 'th']) {
    const html = render(createElement(ui.LangToggle), { lang })
    assert.match(html, new RegExp(`role="group"[^>]*aria-label="${DICTS[lang].nav.language}"`))
    const pressed = [...html.matchAll(/<button[^>]*aria-pressed="true"[^>]*lang="(\w+)"/g)].map((m) => m[1])
    assert.deepEqual(pressed, [lang])
    assert.ok(text(html).includes('TH') && text(html).includes('EN'))
  }
})

// ------------------------------------------------- LangProvider / useLang

function LangProbe() {
  const { lang, t } = useLang()
  return createElement('span', null, `${lang}|${t('nav.overview')}`)
}

test('LangProvider: ?lang= picks the language; the default is Thai', () => {
  const at = (path) => renderToStaticMarkup(
    createElement(MemoryRouter, { initialEntries: [path] }, createElement(LangProvider, null, createElement(LangProbe))),
  )
  assert.equal(text(at('/?lang=en')).trim(), `en|${en.nav.overview}`)
  assert.equal(text(at('/map?lang=th')).trim(), `th|${th.nav.overview}`)
  assert.equal(text(at('/')).trim(), `th|${th.nav.overview}`)
  assert.equal(text(at('/?lang=fr')).trim(), `th|${th.nav.overview}`)
})

// ---------------------------------------------------------- useBaseline

const METHODS_TEST = {
  disclaimer: SERVER_DISCLAIMER,
  baseline: { mode: 'test', valid: true, kind: 'test', version: 'TEST-20261009-9fc9a022', reason: null },
}

test('useBaseline: one /methods request shared by every caller; the state maps mode/valid/version', async () => {
  baselineModule.resetBaselineCache()
  let calls = 0
  const fetcher = async () => {
    calls += 1
    return METHODS_TEST
  }
  const [a, b] = await Promise.all([baselineModule.loadBaseline(fetcher), baselineModule.loadBaseline(fetcher)])
  await baselineModule.loadBaseline(fetcher)
  assert.equal(calls, 1)
  assert.deepEqual(a, b)
  assert.equal(a.status, 'ready')
  assert.equal(a.mode, 'test')
  assert.equal(a.valid, true)
  assert.equal(a.version, 'TEST-20261009-9fc9a022')
  assert.equal(a.isTest, true)
  assert.equal(a.disclaimer, SERVER_DISCLAIMER)

  // A component mounted after the load reads the shared state synchronously.
  function Probe() {
    const s = baselineModule.useBaseline()
    return createElement('span', null, `${s.status}|${s.isTest}|${s.version}`)
  }
  assert.equal(renderToStaticMarkup(createElement(Probe)), '<span>ready|true|TEST-20261009-9fc9a022</span>')
  baselineModule.resetBaselineCache()
  assert.equal(renderToStaticMarkup(createElement(Probe)), '<span>loading|false|null</span>')
})

test('useBaseline: mode off, invalid test mode and a failed request never claim TEST', async () => {
  const cases = [
    [{ baseline: { mode: 'off', valid: null, kind: null, version: null, reason: null } }, { mode: 'off', isTest: false }],
    [{ baseline: { mode: 'test', valid: false, kind: 'test', version: null, reason: 'manifest_missing' } },
      { mode: 'test', valid: false, isTest: false, reason: 'manifest_missing' }],
    [{}, { mode: null, isTest: false }],
  ]
  for (const [payload, expected] of cases) {
    baselineModule.resetBaselineCache()
    const state = await baselineModule.loadBaseline(async () => payload)
    for (const [k, v] of Object.entries(expected)) assert.equal(state[k], v, `${JSON.stringify(payload)}.${k}`)
  }
  baselineModule.resetBaselineCache()
  let calls = 0
  const failing = async () => {
    calls += 1
    throw Object.assign(new Error('Network Error'), { code: 'ERR_NETWORK' })
  }
  const failed = await baselineModule.loadBaseline(failing)
  assert.equal(failed.status, 'error')
  assert.equal(failed.isTest, false)
  // A failure is not cached forever: the next caller retries.
  await baselineModule.loadBaseline(failing)
  assert.equal(calls, 2)
  baselineModule.resetBaselineCache()
})

// ------------------------------------------- FigureFrame, states, cite

test('FigureFrame: numbered caption, optional data-table disclosure and CSV button', () => {
  const bare = render(createElement(ui.FigureFrame, { number: 3, caption: 'Scene-date shares' }, createElement('div', null, 'chart')))
  assert.match(bare, /^<figure/)
  assert.match(bare, /<figcaption/)
  assert.ok(text(bare).includes('Fig. 3') && text(bare).includes('Scene-date shares') && text(bare).includes('chart'))
  assert.doesNotMatch(bare, /<details|Download CSV/)

  const full = render(createElement(ui.FigureFrame, {
    number: 2,
    caption: 'x',
    dataTable: createElement('table', null, createElement('tbody', null)),
    csv: { filename: 'x.csv', content: 'a,b\r\n' },
  }, 'body'), { lang: 'th' })
  assert.ok(text(full).includes('ภาพที่ 2'))
  assert.match(full, /<details[\s\S]*<summary[^>]*>[\s\S]*ดูตารางข้อมูล/)
  assert.ok(text(full).includes(th.action.download_csv))
})

test('ErrorState: HTTP status, the request and the server detail verbatim; a retry button', () => {
  const error = { response: { status: 503, data: { detail: 'Earth Engine is not configured on this server.' } } }
  const html = render(createElement(ui.ErrorState, { error, endpoint: '/raster-scan', onRetry() {} }))
  const visible = text(html)
  assert.ok(visible.includes('HTTP 503'))
  assert.ok(visible.includes('GET /raster-scan'))
  assert.ok(visible.includes('Earth Engine is not configured on this server.'))
  assert.ok(visible.includes(en.error.server_detail))
  assert.match(html, /<button[^>]*>[\s\S]*Retry/)
  const offline = text(render(createElement(ui.ErrorState, { error: { message: 'Network Error' } }), { lang: 'th' }))
  assert.ok(offline.includes(th.error.no_response), offline)
})

test('EmptyState and PageHeader render their headings and text', () => {
  const empty = render(createElement(ui.EmptyState, { title: 'Nothing yet', body: 'Because.' }))
  assert.ok(text(empty).includes('Nothing yet') && text(empty).includes('Because.'))
  assert.match(empty, /<h2/)
  const head = render(createElement(ui.PageHeader, { title: 'Methods', lede: 'How it works', eyebrow: 'Docs' }))
  assert.match(head, /<h1[^>]*>Methods<\/h1>/)
  assert.ok(text(head).includes('How it works'))
})

test('CiteButton: a labelled button and a polite live region; rendering never throws', () => {
  const html = render(createElement(ui.CiteButton, { runId: 12, oldestScene: '2026-09-20', newestScene: '2026-09-30' }))
  assert.match(html, /<button[^>]*type="button"/)
  assert.ok(text(html).includes(en.action.copy_citation))
  assert.match(html, /aria-live="polite"/)
  assert.doesNotThrow(() => render(createElement(ui.CiteButton, {})))
})

test('NotFoundPage: names the requested path and links home', () => {
  for (const lang of ['en', 'th']) {
    const html = render(createElement(NotFoundPage), { lang, path: '/nope/x' })
    assert.ok(text(html).includes(DICTS[lang].notfound.title))
    assert.ok(text(html).includes('/nope/x'))
    assert.match(html, /href="\/"/)
  }
})

// ---------------------------------------------------------------- shell

function shellAt(path, lang = 'en') {
  const routes = createElement(Routes, null, createElement(Route, { element: createElement(App) },
    createElement(Route, { index: true, element: createElement(PlaceholderPage, { titleKey: 'nav.overview' }) }),
    createElement(Route, { path: 'map', element: createElement('div', { className: 'overview-page' }, 'MAP') }),
    createElement(Route, { path: 'sites/:siteId', element: createElement(PlaceholderPage, { titleKey: 'nav.sites' }) }),
    createElement(Route, { path: '*', element: createElement(NotFoundPage) })))
  return render(routes, { lang, path })
}

test('shell: skip link first, header/main/footer landmarks, map layout only on /map', () => {
  baselineModule.resetBaselineCache()
  for (const [path, layout] of [['/', 'page'], ['/map', 'map'], ['/sites/bangsaen', 'page'], ['/nope', 'page']]) {
    const html = shellAt(path)
    assert.match(html, new RegExp(`^<div class="pw-shell" data-layout="${layout}"><a class="pw-skip" href="#main"`), path)
    assert.match(html, /<header class="pw-header"/)
    assert.match(html, /<main id="main" class="pw-main" tabindex="-1"/)
    assert.match(html, /<footer class="pw-footer"/)
    assert.equal((html.match(/<h1/g) ?? []).length, layout === 'map' ? 0 : 1, `${path}: one page heading`)
  }
  assert.ok(text(shellAt('/map')).includes('MAP'))
  assert.ok(text(shellAt('/sites/bangsaen')).includes('Requested site ID: bangsaen'))
  assert.ok(text(shellAt('/', 'th')).includes(th.placeholder.title))
})

test('shell: the TEST strip and the /methods disclaimer appear on every page once the baseline is read', async () => {
  baselineModule.resetBaselineCache()
  const before = shellAt('/')
  assert.ok(!text(before).includes(en.truth.test_banner), 'nothing claimed before /methods answers')
  assert.ok(text(before).includes(en.truth.no_server_disclaimer))
  await baselineModule.loadBaseline(async () => METHODS_TEST)
  for (const path of ['/', '/map', '/sites/x', '/nope']) {
    const visible = text(shellAt(path))
    assert.ok(visible.includes(en.truth.test_banner), `${path}: TEST strip missing`)
    assert.ok(visible.includes(SERVER_DISCLAIMER), `${path}: footer disclaimer missing`)
    assert.ok(visible.includes('GET /methods'))
    assert.ok(visible.includes(en.truth.point_3_test), `${path}: TEST wording of point 3`)
  }
  baselineModule.resetBaselineCache()
})

// ------------------------------------------------- risk tokens unused

const FORBIDDEN = ['risk-normal', 'risk-elevated', 'risk-watch', 'risk-warning', 'RISK_COLOR']

async function sourceFiles(dir) {
  const out = []
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const full = new URL(`${entry.name}${entry.isDirectory() ? '/' : ''}`, dir)
    if (entry.isDirectory()) out.push(...await sourceFiles(full))
    else if (/\.(jsx?|css)$/.test(entry.name)) out.push(full)
  }
  return out
}

test('src/components/ui, src/pages and dashboard.css never reference the risk tokens', async () => {
  const dirs = [new URL('../src/components/ui/', import.meta.url), new URL('../src/pages/', import.meta.url)]
  const files = (await Promise.all(dirs.map(sourceFiles))).flat()
  assert.ok(files.length >= 13, 'the ui components and pages were found')
  const checked = []
  for (const file of files) {
    const name = fileURLToPath(file).split('/').pop()
    const source = await readFile(file, 'utf8')
    for (const word of FORBIDDEN) assert.ok(!source.includes(word), `${name} references ${word}`)
    checked.push(name)
  }
  assert.ok(checked.includes('NavBar.jsx') && checked.includes('NotFoundPage.jsx'))
  const css = await readFile(new URL('../src/styles/dashboard.css', import.meta.url), 'utf8')
  assert.doesNotMatch(css, /--risk-/, 'dashboard.css uses a risk token')

})
