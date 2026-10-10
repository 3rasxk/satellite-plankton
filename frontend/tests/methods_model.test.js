/**
 * The Methods page (`/methods`): its view model (src/lib/methodsModel.js)
 * and its markup (src/pages/MethodsPage.jsx, src/components/{IndexCard,
 * GateTable,ReferenceList}.jsx).
 *
 * Claims under test:
 *   - the model builds the sections in the documented order from a real
 *     `/methods` payload;
 *   - every displayed number is an API field: each value's `field` path
 *     resolves, in the payload of the endpoint its source names, to exactly
 *     the raw value shown; and no number from the payload is hard-coded in
 *     the page, its components, the model or the methods i18n prose;
 *   - the TEST baseline section has content only in mode 'test' (season
 *     windows, signature, history, per-site support, Level A base rates
 *     with the "not accuracy" sentence, Level B summary); with the mode off
 *     it carries the off-explanation and nothing else;
 *   - an anchor exists for each index key returned, and for every
 *     `/methods#…` anchor any file in src links to;
 *   - references render verbatim, DOIs as doi.org links, and every DOI is
 *     in LIMITATIONS.md;
 *   - the server disclaimer is passed on verbatim; long-form prose uses the
 *     serif `.prose` class; no risk colour; every key exists in TH and EN.
 *
 * Fixture: tests/fixtures/methods_payload.json, from the live API (backend
 * with BASELINE_MODE=test, 2026-10-10). Markup renders through a Vite SSR
 * loader with no DOM, as in tests/sites_model.test.js.
 */
import test, { before, after } from 'node:test'
import assert from 'node:assert/strict'
import { readFile, readdir } from 'node:fs/promises'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { createServer } from 'vite'
import react from '@vitejs/plugin-react'

import en from '../src/i18n/en.js'
import th from '../src/i18n/th.js'
import { missingKeys } from '../src/i18n/index.js'
import { formatValue } from '../src/lib/format.js'
import {
  METHODS_SECTIONS, FIXED_ANCHORS, INDEX_ROLES, buildMethodsModel, buildLevelBModel, wantsLevelB, doiHref,
} from '../src/lib/methodsModel.js'
import { SITE_INDEX_FIELDS } from '../src/lib/sitesModel.js'
import { INDEX_FIELDS } from '../src/lib/mapModel.js'

const NBSP = '\u00a0'
const FIXTURE = JSON.parse(await readFile(new URL('./fixtures/methods_payload.json', import.meta.url), 'utf8'))

function deepFreeze(o) {
  if (o && typeof o === 'object') {
    Object.values(o).forEach(deepFreeze)
    Object.freeze(o)
  }
  return o
}

const METHODS = deepFreeze(FIXTURE.methods)
const HIGHLIGHTS = deepFreeze(FIXTURE.highlights_anomaly)
const OFF_BASELINE = {
  mode: 'off', valid: null, kind: null, version: null, built_at: null, history_start: null, history_end: null,
  season_rule: null, min_independent_dates: null, median_independent_dates: null, min_season_dates_by_location: null,
  preprocessing_signature: null, base_rates: null, reason: null,
}
const METHODS_OFF = deepFreeze({
  ...METHODS,
  disclaimer: 'Satellite index values describe water colour at pixel resolution. Small or scattered blooms may not be visible. Anomaly detection is not computed.',
  gates: { ...METHODS.gates, signal_anomaly_active: false },
  baseline: OFF_BASELINE,
})
const METHODS_INVALID = deepFreeze({
  ...METHODS,
  baseline: { ...OFF_BASELINE, mode: 'test', valid: false, kind: 'test', reason: 'preprocessing_signature mismatch' },
})

const ok = { loading: false, error: null }
const levelBReady = () => buildLevelBModel({ highlights: HIGHLIGHTS, request: ok })
const testModel = () => buildMethodsModel({ methods: METHODS, request: ok, levelB: levelBReady() })

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

/** `a.b[2].c` -> the value in `root`, own properties only (undefined if absent). */
function resolve(root, path) {
  let node = root
  for (const part of path.replace(/\[(\d+)\]/g, '.$1').split('.')) {
    if (node === null || typeof node !== 'object' || !Object.hasOwn(node, part)) return undefined
    node = node[part]
  }
  return node
}

/** Every node of a model that shows an API value: has `field` and `source`. */
function valueNodes(node, out = []) {
  if (Array.isArray(node)) node.forEach((n) => valueNodes(n, out))
  else if (node && typeof node === 'object') {
    if (typeof node.field === 'string' && node.source && Object.hasOwn(node, 'raw')) out.push(node)
    for (const v of Object.values(node)) if (typeof v !== 'function') valueNodes(v, out)
  }
  return out
}

/** Every i18n key a model names (`key`, `*Key`). */
function modelKeys(node, out = new Set()) {
  if (Array.isArray(node)) node.forEach((n) => modelKeys(n, out))
  else if (node && typeof node === 'object') {
    for (const [k, v] of Object.entries(node)) {
      if ((k === 'key' && typeof v === 'string' && /^methods\./.test(v)) || (/Key$/.test(k) && typeof v === 'string')) out.add(v)
      else if (typeof v !== 'function') modelKeys(v, out)
    }
  }
  return out
}

// ------------------------------------------------------------------ model

test('sections in the documented order; the TOC follows them', () => {
  const m = testModel()
  assert.equal(m.state, 'ready')
  assert.deepEqual(m.sections.map((s) => s.id), [...METHODS_SECTIONS])
  assert.deepEqual(METHODS_SECTIONS, ['sources', 'indices', 'quality', 'gates', 'baseline', 'latest_scene', 'references'])
  assert.deepEqual(m.toc.map((s) => s.id), [...METHODS_SECTIONS])
  assert.equal(m.apiVersion, METHODS.api_version)
  assert.equal(m.isTest, true)
  assert.deepEqual(m.disclaimer, { text: METHODS.disclaimer, endpoint: '/methods' }, 'server disclaimer verbatim')
})

test('every displayed number resolves to its API field, unchanged', () => {
  const m = testModel()
  const nodes = valueNodes(m)
  assert.ok(nodes.length > 80, `found ${nodes.length} displayed values`)
  const payloads = { '/methods': METHODS, '/raster-scan/highlights': HIGHLIGHTS }
  let numbers = 0
  for (const n of nodes) {
    const payload = payloads[n.source.endpoint]
    assert.ok(payload, `${n.field}: unknown endpoint ${n.source.endpoint}`)
    const api = resolve(payload, n.field)
    assert.deepEqual(n.raw ?? null, api ?? null, `${n.source.endpoint} ${n.field}`)
    const fieldRow = n.source.rows.find((r) => r.id === 'field')
    assert.equal(fieldRow.text, n.field, 'the popover names the same field')
    if (typeof n.raw === 'number') numbers += 1
  }
  assert.ok(numbers > 60)
  // Spot checks of what the reader sees.
  const sources = m.sections.find((s) => s.id === 'sources')
  assert.equal(sources.modis.facts[0].text, `4,638${NBSP}m`)
  assert.equal(sources.sentinel2.facts.find((f) => f.id === 'scale_factor').text, '10,000')
  assert.deepEqual(sources.sentinel2.scaleNote, { key: 'methods.s2.scale_note', params: { scale: '10,000' } })
  assert.deepEqual(sources.sentinel2.sceneAgeNote.params, { days: '14' })
})

test('bands: only API wavelengths; B2/B3 are "not documented", never invented', () => {
  const m = testModel()
  const s2 = m.sections.find((s) => s.id === 'sources').sentinel2
  assert.deepEqual(s2.bands.map((b) => b.band), METHODS.sentinel2.bands)
  const byBand = Object.fromEntries(s2.bands.map((b) => [b.band, b]))
  assert.equal(byBand.B4.wavelength.text, `665${NBSP}nm`)
  assert.equal(byBand.B2.wavelengthDocumented, false)
  assert.equal(byBand.B2.wavelength.text, '—')
  assert.equal(byBand.B5.resolution.text, `20${NBSP}m`)
  assert.equal(s2.wavelengthsNote, METHODS.sentinel2.wavelengths_note)
})

test('index cards: one per index, anchored at its key, with the server worked example', () => {
  const m = testModel()
  const cards = m.sections.find((s) => s.id === 'indices').cards
  assert.deepEqual(cards.map((c) => c.anchor), METHODS.indices.map((i) => i.key))
  for (const key of METHODS.indices.map((i) => i.key)) assert.ok(m.anchors.includes(key), key)
  cards.forEach((c, i) => {
    const api = METHODS.indices[i]
    assert.equal(c.formula, api.formula)
    assert.equal(c.note, api.note)
    assert.equal(c.example.value.raw, api.worked_example.value, 'the server value, not recomputed')
    assert.deepEqual(c.example.bands.map((b) => b.band), api.bands, 'the bands the index uses')
    assert.deepEqual(c.example.bands.map((b) => b.raw), api.bands.map((b) => api.worked_example.bands[b]))
    assert.ok(INDEX_ROLES.includes(c.role))
    assert.equal(c.roleKey, `methods.role.${api.role}`)
  })
  const ndci = cards[0]
  assert.equal(ndci.domain.min.text, '−0.05')
  assert.equal(ndci.domain.max.text, '0.15')
  assert.equal(ndci.example.value.text, '0.076923')
  const bda2 = cards.find((c) => c.key === '2bda')
  assert.equal(bda2.role, 'derived')
  assert.match(EN.get('methods.role.derived'), /not an independent signal/)
  assert.equal(bda2.domain, null, 'no display domain agreed')
  const ratio = cards.find((c) => c.key === 'b2_b3_ratio')
  assert.ok(ratio.bands.every((b) => b.wavelengthDocumented === false))
})

test('quality screens: the degenerate ±1 rule and the low-signal rule labelled developer-chosen, not validated', () => {
  const q = testModel().sections.find((s) => s.id === 'quality')
  assert.deepEqual(q.screens.map((s) => s.id), ['degenerate_ndci', 'low_signal'])
  const [deg, low] = q.screens
  assert.equal(deg.rule, METHODS.quality_screens.degenerate_ndci.rule)
  assert.equal(deg.values[0].text, '0.999999')
  assert.equal(low.labelKey, 'methods.quality.not_validated')
  assert.equal(EN.get('methods.quality.not_validated'), 'Developer-chosen, not validated')
  assert.equal(low.values[0].text, `50${NBSP}DN`)
  assert.equal(low.status, 'developer-chosen, not validated')
  assert.equal(q.masks.find((x) => x.id === 'cloud_mask_scl_classes').text, '0, 1, 3, 7, 8, 9, 10')
  assert.equal(q.masks.find((x) => x.id === 'max_cloud_fraction').text, `50${NBSP}%`)
})

test('gates: the booleans as returned, the floors, and the robust-z statistic', () => {
  const g = testModel().sections.find((s) => s.id === 'gates')
  const rows = Object.fromEntries(g.rows.map((r) => [r.id, r.value]))
  assert.equal(rows.risk_evaluation_active.raw, false)
  assert.equal(rows.risk_evaluation_active.stateKey, 'methods.gates.inactive')
  assert.equal(rows.signal_anomaly_active.raw, true)
  assert.deepEqual(g.floors.map((f) => f.value.text), ['30', `14${NBSP}d`])
  assert.deepEqual(g.whyNoRisk.params, { min_dates: '30', max_age: `14${NBSP}d` })
  assert.equal(g.statistic.anchor, 'robust_z')
  assert.equal(g.statistic.formula, METHODS.gates.signal_anomaly_statistic.formula)
  assert.deepEqual(g.statistic.levels.params, { watch: '2.0', high: '3.0' })
  const missing = buildMethodsModel({ methods: { ...METHODS, gates: {} }, request: ok })
  const r = missing.sections.find((s) => s.id === 'gates').rows[0].value
  assert.equal(r.isNull, true, 'a missing gate is unknown, never "off"')
  assert.equal(r.stateKey, null)
})

test('TEST baseline: season windows, signature, history, per-site support, base rates, Level B', () => {
  const b = testModel().sections.find((s) => s.id === 'baseline').baseline
  assert.equal(b.state, 'test')
  assert.equal(b.anchor, 'baseline')
  assert.equal(b.seasonWindows.length, METHODS.season_windows.length)
  assert.equal(b.seasonWindows[0].key, 'm01+-1')
  assert.equal(b.seasonWindows[0].months.text, '12, 1, 2')
  assert.equal(b.signature.text, METHODS.baseline.preprocessing_signature)
  assert.equal(b.seasonRule, METHODS.season_rule)
  assert.deepEqual(b.intro.params, { start: '2017-12-13', end: '2026-10-07' })
  assert.deepEqual(b.perSite.map((s) => s.site), Object.keys(METHODS.baseline.min_season_dates_by_location))
  assert.equal(b.perSite.find((s) => s.site === 'chaam').count.text, '35')

  // Level A base rates: counts as returned; shares are API count / API count.
  const rates = b.rates
  assert.deepEqual(rates.counts.map((c) => [c.id, c.raw]), [['assessed', 1706], ['watch', 60], ['high', 123], ['no_assessment', 1155]])
  assert.deepEqual(rates.reasons.map((r) => [r.code, r.raw]), [['insufficient_independent_dates', 1155]])
  const br = METHODS.baseline.base_rates
  assert.equal(rates.watchShare.raw, br.watch / br.assessed)
  assert.equal(rates.watchShare.text, `3.5${NBSP}%`)
  assert.equal(rates.highShare.text, `7.2${NBSP}%`)
  assert.equal(rates.watchShare.text, formatValue(br.watch / br.assessed, { kind: 'percent', decimals: 1 }).text)
  assert.deepEqual(rates.summary, { key: 'methods.rates.summary', params: { watch: `3.5${NBSP}%`, high: `7.2${NBSP}%`, assessed: '1,706' } })
  const zero = buildMethodsModel({ methods: { ...METHODS, baseline: { ...METHODS.baseline, base_rates: { assessed: 0, watch: 0, high: 0, no_assessment: 4, reasons: {} } } }, request: ok })
  const zr = zero.sections.find((s) => s.id === 'baseline').baseline.rates
  assert.equal(zr.watchShare.text, '—', 'no denominator, no share')
  assert.equal(zr.summary.key, 'methods.rates.summary_none')

  // Level B summary from /raster-scan/highlights?mode=anomaly.
  assert.equal(b.levelB.state, 'ready')
  const lb = Object.fromEntries(b.levelB.facts.map((f) => [f.id, f]))
  assert.equal(lb.history_end.text, HIGHLIGHTS.baseline.level_b.history_end)
  assert.equal(lb.scale_m.text, `200${NBSP}m`)
  assert.equal(b.levelB.season.text, 'm10+-1')
  assert.equal(b.levelB.historyEndRule, HIGHLIGHTS.baseline.level_b.history_end_rule)
  assert.equal(lb.history_end.source.endpoint, '/raster-scan/highlights')
  assert.match(lb.history_end.source.url, /mode=anomaly/)
})

test('baseline mode off: the section keeps its anchor and only the off-explanation', () => {
  const m = buildMethodsModel({ methods: METHODS_OFF, request: ok })
  const b = m.sections.find((s) => s.id === 'baseline').baseline
  assert.deepEqual(b, { anchor: 'baseline', state: 'off', explanationKey: 'methods.baseline.off' })
  assert.ok(EN.has('methods.baseline.off') && TH.has('methods.baseline.off'))
  assert.equal(m.isTest, false)
  assert.ok(m.anchors.includes('baseline'))
  assert.ok(!m.anchors.includes('level_a') && !m.anchors.includes('level_b'))
  assert.equal(wantsLevelB(METHODS_OFF), false)
  assert.equal(wantsLevelB(METHODS), true)
  assert.equal(wantsLevelB(METHODS_INVALID), false)

  const inv = buildMethodsModel({ methods: METHODS_INVALID, request: ok }).sections.find((s) => s.id === 'baseline').baseline
  assert.equal(inv.state, 'invalid')
  assert.equal(inv.reason, 'preprocessing_signature mismatch')
  const unknown = buildMethodsModel({ methods: { ...METHODS, baseline: null }, request: ok }).sections.find((s) => s.id === 'baseline').baseline
  assert.equal(unknown.state, 'unknown')
})

test('loading and error states; Level B degrades on its own', () => {
  assert.equal(buildMethodsModel({ methods: null, request: { loading: true } }).state, 'loading')
  const e = buildMethodsModel({ methods: null, request: { error: { message: 'Network Error' } } })
  assert.equal(e.state, 'error')
  assert.equal(e.error.endpoint, '/methods')
  assert.equal(buildLevelBModel({ highlights: null, request: { loading: true } }).state, 'loading')
  const err = buildLevelBModel({ highlights: null, request: { error: { response: { status: 409, data: { detail: 'no cell baseline' } } } } })
  assert.equal(err.state, 'error')
  assert.equal(err.endpoint, '/raster-scan/highlights?mode=anomaly')
  assert.equal(buildLevelBModel({ highlights: { ...HIGHLIGHTS, baseline: { ...HIGHLIGHTS.baseline, level_b: null } }, request: ok }).state, 'empty')
  const m = buildMethodsModel({ methods: METHODS, request: ok, levelB: err })
  assert.equal(m.state, 'ready', 'the page renders while Level B fails')
})

test('references exactly as returned; DOIs link to doi.org and are in LIMITATIONS.md', async () => {
  const refs = testModel().sections.find((s) => s.id === 'references').references
  assert.equal(refs.length, METHODS.references.length)
  refs.forEach((r, i) => {
    assert.equal(r.citation, METHODS.references[i].citation)
    assert.equal(r.doi, METHODS.references[i].doi)
    assert.equal(r.note, METHODS.references[i].note)
    assert.equal(r.href, `https://doi.org/${METHODS.references[i].doi}`)
  })
  assert.equal(doiHref(null), null)
  const limitations = await readFile(new URL('../../LIMITATIONS.md', import.meta.url), 'utf8')
  for (const r of refs) assert.ok(limitations.includes(r.doi), `${r.doi} is not in LIMITATIONS.md`)
})

test('every i18n key the models name exists in TH and EN', () => {
  const models = [
    testModel(),
    buildMethodsModel({ methods: METHODS_OFF, request: ok }),
    buildMethodsModel({ methods: METHODS_INVALID, request: ok }),
    buildMethodsModel({ methods: { ...METHODS, baseline: null }, request: ok }),
    buildMethodsModel({ methods: METHODS, request: ok, levelB: buildLevelBModel({ highlights: { baseline: {} }, request: ok }) }),
  ]
  const keys = new Set()
  for (const m of models) modelKeys(m, keys)
  assert.ok(keys.size > 60, `found ${keys.size} keys`)
  for (const key of keys) {
    assert.ok(EN.has(key), `en.js lacks ${key}`)
    assert.ok(TH.has(key), `th.js lacks ${key}`)
  }
})

// --------------------------------------------------- no hard-coded numbers

const VIEW_FILES = ['src/pages/MethodsPage.jsx', 'src/components/IndexCard.jsx', 'src/components/GateTable.jsx', 'src/components/ReferenceList.jsx']
const stripComments = (src) => src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:'"`])\/\/.*$/gm, '$1')
const NUMERIC = /(?<![\w$.#-])\d+(?:\.\d+)?(?![\w])/g

test('no numeric literal in the page or its components, other than layout', async () => {
  for (const file of VIEW_FILES) {
    const src = stripComments(await readFile(new URL(`../${file}`, import.meta.url), 'utf8'))
      // Layout only: icon size and stroke, heading level.
      .replace(/\b(size|strokeWidth|level)=\{\d+(?:\.\d+)?\}/g, '')
    const found = src.match(NUMERIC) ?? []
    assert.deepEqual(found, [], `${file} hard-codes ${found.join(', ')}`)
  }
})

test('the model uses formatting decimals only; no payload number is written in it', async () => {
  const src = stripComments(await readFile(new URL('../src/lib/methodsModel.js', import.meta.url), 'utf8'))
  const found = new Set(src.match(NUMERIC) ?? [])
  const formatting = new Set(['0', '1', '2', '4', '6']) // decimals and "> 0"
  for (const n of found) assert.ok(formatting.has(n), `methodsModel.js hard-codes ${n}`)
})

test('the methods i18n prose contains no number: values arrive as {params}', () => {
  // Identifiers that contain digits are names, not values.
  const names = /\b[A-Za-z_]+\d+\w*\b|\bSentinel-2\b|\bLevel-3\b|\b[23]BDA\b|m⁻³/g
  for (const [lang, dict] of [['en', EN], ['th', TH]]) {
    for (const [key, value] of dict) {
      if (!key.startsWith('methods.')) continue
      const rest = value.replace(/\{[a-z_]+\}/g, '').replace(names, '')
      assert.doesNotMatch(rest, /\d/, `${lang}:${key} writes a number: ${value}`)
    }
  }
})

// ------------------------------------------------------------------ anchors

async function srcFiles(dir) {
  const out = []
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const full = new URL(`${entry.name}${entry.isDirectory() ? '/' : ''}`, dir)
    if (entry.isDirectory()) out.push(...await srcFiles(full))
    else if (/\.(jsx?)$/.test(entry.name)) out.push(full)
  }
  return out
}

/** Every `/methods#…` anchor the app links to: literal ones, plus the
 * values of the registries behind the computed links. */
async function linkedAnchors() {
  const anchors = new Set()
  const computedIn = new Set()
  for (const file of await srcFiles(new URL('../src/', import.meta.url))) {
    const src = await readFile(file, 'utf8')
    for (const m of src.matchAll(/\/methods#([A-Za-z0-9_]+)/g)) anchors.add(m[1])
    if (/\/methods#\$\{/.test(src)) computedIn.add(file.pathname.split('/src/')[1])
    for (const m of src.matchAll(/formula(?:Key)?:\s*'([a-z0-9_]+)'/g)) anchors.add(m[1])
  }
  // Computed `/methods#${…}` links come from these files only; a new one
  // must be added here with its registry.
  assert.deepEqual([...computedIn].sort(), ['lib/mapModel.js', 'lib/provenance.js', 'lib/sitesModel.js'])
  for (const f of SITE_INDEX_FIELDS) anchors.add(f.key)
  for (const f of INDEX_FIELDS) anchors.add(f.methods)
  return anchors
}

// ----------------------------------------------------------------- markup

let server
let MethodsView
let StaticLangProvider

before(async () => {
  server = await createServer({
    configFile: false,
    plugins: [react()],
    cacheDir: 'node_modules/.vite-methods-tests',
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true, watch: null, hmr: false, ws: false },
  })
  MethodsView = (await server.ssrLoadModule('/src/pages/MethodsPage.jsx')).MethodsView
  ;({ StaticLangProvider } = await server.ssrLoadModule('/src/i18n/LangContext.jsx'))
})

after(async () => server?.close())

function render(model, lang = 'en') {
  return renderToStaticMarkup(createElement(MemoryRouter, { initialEntries: ['/methods'] },
    createElement(StaticLangProvider, { lang }, createElement(MethodsView, { model, onRetry: () => {}, onRetryLevelB: () => {}, onPrint: () => {} }))))
}

const visible = (html) => html.replace(/<[^>]+>/g, ' ').replace(/&#x27;/g, "'").replace(/&quot;/g, '"')
  .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&').replace(/\s+/g, ' ')
const ids = (html) => new Set([...html.matchAll(/\sid="([^"]+)"/g)].map((m) => m[1]))

test('every /methods#… anchor used anywhere in src exists on the page, in every baseline mode', async () => {
  const anchors = await linkedAnchors()
  for (const a of ['ndci', '2bda', '3bda', 'b2_b3_ratio', 'modis', 'baseline', 'robust_z']) assert.ok(anchors.has(a), `expected ${a} to be linked`)
  for (const model of [testModel(), buildMethodsModel({ methods: METHODS_OFF, request: ok })]) {
    const html = render(model)
    const all = [...html.matchAll(/\sid="([^"]+)"/g)].map((m) => m[1])
    assert.equal(all.length, new Set(all).size, `duplicate ids: ${all.filter((x, i) => all.indexOf(x) !== i)}`)
    const found = ids(html)
    for (const a of anchors) assert.ok(found.has(a), `#${a} is linked but missing on the page`)
    for (const a of model.anchors) assert.ok(found.has(a), `model anchor #${a} not rendered`)
    for (const a of FIXED_ANCHORS.filter((x) => !x.startsWith('level_'))) assert.ok(found.has(a), a)
  }
})

test('MethodsView (EN, TEST): one h1, server texts verbatim, serif prose, base-rate sentence, no risk colour', () => {
  missingKeys.clear()
  const html = render(testModel())
  assert.equal((html.match(/<h1/g) ?? []).length, 1)
  const text = visible(html)
  for (const ix of METHODS.indices) {
    assert.ok(text.includes(ix.formula), ix.formula)
    assert.ok(text.includes(ix.note), `${ix.key} note verbatim`)
  }
  assert.ok(text.includes('Derived: not an independent signal'))
  assert.ok(text.includes(METHODS.modis.note))
  assert.ok(html.includes(`4,638${NBSP}m`))
  assert.ok(text.includes(METHODS.quality_screens.low_signal.rule))
  assert.ok(text.includes('Developer-chosen, not validated'))
  assert.ok(text.includes(METHODS.gates.signal_anomaly_statistic.formula))
  assert.ok(text.includes('watch on 3.5 % and high on 7.2 % of the 1,706 assessable past dates'), 'visible() folds the NBSP')
  assert.ok(text.includes(en.methods.rates.not_accuracy))
  assert.ok(text.includes(HIGHLIGHTS.baseline.level_b.history_end_rule))
  assert.ok(text.includes('2026-09-23'), 'Level B history_end')
  for (const r of METHODS.references) {
    assert.ok(text.includes(r.citation), 'citation verbatim')
    assert.ok(text.includes(r.note), 'reference note verbatim')
    assert.ok(html.includes(`href="https://doi.org/${r.doi}"`))
  }
  assert.ok((html.match(/class="prose"/g) ?? []).length >= 8, 'long-form prose is serif')
  assert.match(html, /<blockquote|class="pw-server-text" lang="en"/)
  assert.doesNotMatch(html, /risk-(normal|elevated|watch|warning)|RISK_COLOR|--risk-/)
  assert.deepEqual([...missingKeys], [])
})

test('MethodsView (TH): mode off has only the off-explanation; TEST mode renders without missing keys', () => {
  missingKeys.clear()
  const html = render(buildMethodsModel({ methods: METHODS_OFF, request: ok }), 'th')
  const text = visible(html)
  assert.ok(text.includes(th.methods.baseline.off))
  assert.doesNotMatch(html, /pw-season-table|pw-rates-table|id="level_b"/)
  assert.ok(!text.includes(th.methods.rates.not_accuracy))
  assert.match(html, /id="baseline"/)
  assert.deepEqual([...missingKeys], [])

  const thTest = visible(render(testModel(), 'th'))
  assert.ok(thTest.includes(th.methods.rates.not_accuracy))
  assert.ok(thTest.includes(METHODS.indices[1].note), 'server text stays English in Thai')
  assert.deepEqual([...missingKeys], [])

  const inv = visible(render(buildMethodsModel({ methods: METHODS_INVALID, request: ok }), 'en'))
  assert.ok(inv.includes(en.methods.baseline.invalid))
  assert.ok(inv.includes('preprocessing_signature mismatch'))
})

test('MethodsView: loading, error (endpoint named) and a failing Level B block', () => {
  const loading = render(buildMethodsModel({ methods: null, request: { loading: true } }))
  assert.match(loading, /aria-busy="true"/)
  const err = visible(render(buildMethodsModel({ methods: null, request: { error: { response: { status: 503 } } } })))
  assert.ok(err.includes('GET /methods'))
  assert.ok(err.includes('HTTP 503'))
  const lbErr = buildLevelBModel({ highlights: null, request: { error: { response: { status: 409, data: { detail: 'no cell baseline for m10+-1' } } } } })
  const page = visible(render(buildMethodsModel({ methods: METHODS, request: ok, levelB: lbErr })))
  assert.ok(page.includes('GET /raster-scan/highlights?mode=anomaly'))
  assert.ok(page.includes('no cell baseline for m10+-1'))
  assert.ok(page.includes(en.methods.rates.not_accuracy), 'Level A still renders')
})

test('the methods files use no risk colour tokens', async () => {
  for (const file of [...VIEW_FILES, 'src/lib/methodsModel.js']) {
    const src = await readFile(new URL(`../${file}`, import.meta.url), 'utf8')
    assert.doesNotMatch(src, /--risk-|RISK_COLOR|riskColor/, file)
  }
})
