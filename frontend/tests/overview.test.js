/**
 * The Overview page (`/`): its view model and its markup.
 *
 * `buildOverviewModel` (src/lib/overviewModel.js) turns the four API
 * responses into cards, lines and chips made of i18n keys, formatted values
 * and source refs; the page only renders it. These tests are claims tests:
 *   - stale data is never presented as current (stale run, failing or old
 *     poll, newest scene rejected) -- and a failing poll never reads as
 *     "no newer scene";
 *   - an unknown is "—", never 0; a real zero count stays 0;
 *   - `not_checked_yet` and `no_usable_data` are separate rows, never merged;
 *   - TEST anomaly pins always carry "(TEST)"; NDCI pins are a ranking;
 *   - every string the model names is an i18n key present in TH and EN.
 *
 * Fixtures are trimmed from the live API (backend with BASELINE_MODE=test,
 * run 6, 2026-10-10). Markup tests render through a Vite SSR loader with no
 * DOM, as in tests/ui_components.test.js.
 */
import test, { before, after } from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { createServer } from 'vite'
import react from '@vitejs/plugin-react'

import en from '../src/i18n/en.js'
import th from '../src/i18n/th.js'
import { createT, missingKeys } from '../src/i18n/index.js'
import { buildOverviewModel, renderMessage, ageMessage, PIN_COUNT } from '../src/lib/overviewModel.js'
import { classifyPoll } from '../src/lib/statusBanner.js'

const NBSP = '\u00a0'
const NOW = Date.parse('2026-10-09T20:00:00Z')

function deepFreeze(o) {
  if (o && typeof o === 'object') {
    Object.values(o).forEach(deepFreeze)
    Object.freeze(o)
  }
  return o
}

const DISCLAIMER_PLAIN = 'Satellite index values describe water colour at pixel resolution. Small or scattered blooms may not be visible. Sentinel-2 anomaly detection is not computed — no valid baseline exists. Index values alone establish neither bloom presence nor absence.'
const DISCLAIMER_TEST = 'Satellite index values describe water colour at pixel resolution. Small or scattered blooms may not be visible. TEST baseline mode: a Sentinel-2 NDCI reading, at a monitoring site or at a raster cell, may be compared with that same location\'s own earlier record for the same season. Any resulting anomaly is provisional and uncalibrated, has never been checked against recorded bloom events, and is a statistical statement only — not a bloom detection, a species identification, a risk level or a forecast. Index values alone establish neither bloom presence nor absence.'

const TEST_BASELINE = deepFreeze({
  mode: 'test', valid: true, kind: 'test', version: 'TEST-20261009-9fc9a022', reason: null,
})

const POLL_OK = deepFreeze({
  last_poll_started_at: '2026-10-09T19:03:12.102022+00:00',
  last_poll_ok_at: '2026-10-09T19:03:12.102022+00:00',
  last_error: null, last_error_at: null, last_error_kind: null,
})

const SCENE_USED = deepFreeze({
  acquisition_date: '2026-10-07', decision: 'passed', cloud_fraction: 0.40571297411298207,
  threshold_cloud_fraction: 0.5, min_water_pixels: 1000, reason: null, used_in_run_id: 6,
  assessed_at: '2026-10-09T13:04:47.527276+00:00', settled: true, used_in_served_run: true,
  reassessed_after_use: false,
})

const RASTER = deepFreeze({
  disclaimer: DISCLAIMER_PLAIN,
  run_id: 6, status: 'ok', date_used: '2026-10-09', scale_m: 200, cell_count: 235290,
  scene_count: 32, oldest_scene_date: '2026-09-29', newest_scene_date: '2026-10-07',
  scene_dates: [
    { date: '2026-10-07', cells: 182486, share: 0.7755790726337711 },
    { date: '2026-09-29', cells: 36755, share: 0.15621148370096477 },
    { date: '2026-10-02', cells: 16049, share: 0.06820944366526414 },
  ],
  completed_at: '2026-10-09T13:05:04.669994+00:00',
  coverage: { measured_fraction: 0.642290001011268, measured_pixels: 209594, polygon_pixels: 326323 },
  bounds: [[12.503567845000363, 99.91242253062555], [13.615681814999999, 101.02812976061746]],
  legend: {
    value: {
      ramp_hex: ['#0A1929', '#2E86AB', '#48C9A9', '#E8C547', '#D64545'],
      domain: [-0.05, 0.15],
      swatches: [
        { value: -0.05, hex: '#0a1929' },
        { value: 0.05, hex: '#48c9a9' },
        { value: 0.15, hex: '#d64545' },
      ],
      meaning: 'index reading at this cell -- a display ramp, not a risk score: no valid spectral-index baseline exists, so nothing here classifies a cell',
    },
    no_data: { rgba: [0, 0, 0, 0], meaning: 'transparent: no usable measurement -- cloud, land-masked, or no scene covered it. Not a low or zero reading.' },
  },
  overlay_url: '/raster-scan/overlay.png?run_id=6',
  true_color_url: '/raster-scan/true-color.png?run_id=6',
  stale_run_id: null,
  reason: null,
  latest_scene: SCENE_USED,
  last_used_scene_date: '2026-10-07',
  poll: POLL_OK,
})

const NO_RUN = deepFreeze({
  disclaimer: DISCLAIMER_PLAIN,
  run_id: null, status: null, date_used: null, scale_m: null, cell_count: null, scene_count: null,
  oldest_scene_date: null, newest_scene_date: null, scene_dates: null, coverage: null, bounds: null,
  legend: null, overlay_url: null, true_color_url: null, stale_run_id: null,
  reason: 'no raster scan has produced an overlay yet', latest_scene: null, last_used_scene_date: null, poll: null,
})

const SUMMARY = deepFreeze({
  disclaimer: DISCLAIMER_TEST,
  total_sites: 7,
  risk_level_counts: {
    normal: 0, elevated: 0, watch: 0, warning: 0, not_evaluated: 6, not_checked_yet: 0, no_usable_data: 1,
  },
  most_recent_detected_signal: null,
  stale_site_count: 0,
  oldest_fetched_at: '2026-10-09T23:55:24.765132+00:00',
  newest_fetched_at: '2026-10-09T23:56:40.164562+00:00',
  prediction_confidence_label: 'indicative, rule-based -- not a validated forecast',
  baseline: TEST_BASELINE,
})

function site(siteId, name, lng, lat, props) {
  return {
    type: 'Feature',
    geometry: { type: 'Point', coordinates: [lng, lat] },
    properties: {
      site_id: siteId, name, risk_level: null, status: 'ok', actual_date: '2026-10-07',
      cloud_fraction: 0, stale: false, error: null, signal_anomaly_level: 'normal', ...props,
    },
  }
}

const RISK_MAP = deepFreeze({
  disclaimer: DISCLAIMER_TEST,
  type: 'FeatureCollection',
  baseline: TEST_BASELINE,
  features: [
    site('bangsaen', 'Bang Saen, Chonburi', 100.88, 13.26, { actual_date: '2026-09-29' }),
    site('siracha', 'Si Racha, Chonburi', 100.9, 13.15, { status: 'no_imagery', actual_date: null, cloud_fraction: null }),
    site('thachin_mouth', 'Tha Chin River mouth, Samut Sakhon', 100.28, 13.47),
    site('chaophraya_mouth', 'Chao Phraya River mouth, Samut Prakan', 100.58, 13.5),
    site('chaam', 'Cha-am coast, Phetchaburi', 100.0, 12.8, { status: 'no_data_yet', actual_date: null }),
    site('bangpakong_mouth', 'Bang Pakong River mouth, Chachoengsao', 100.95, 13.45, { stale: true, actual_date: '2026-10-02' }),
    site('pattaya', 'Pattaya Beach, Chonburi', 100.86, 12.93, { actual_date: '2026-09-29' }),
  ],
})

const ANOMALY_PIN = deepFreeze({
  rank: 1, cell_lat: 13.337287023322537, cell_lng: 100.21335815052146,
  pixel_centre_lat: 13.338102480000089, pixel_centre_lng: 100.21335805562336,
  index_values: { ndci: 0.65398770570755, bda2: 4.780141830444336, bda3: 1.710598349571228, b2_b3: 0.9086294174194336 },
  percentile: 99.99951967876115, metric_value: 14.338169744761082, date_ms: 1791345282024,
  acquired_date: '2026-10-07', acquired_at: '2026-10-07T03:54:42.024000Z', edge_of_no_data: false,
  risk_tier: null, visible_bands_dn: { red: 141, green: 197, blue: 179 },
  robust_z: 14.338169744761082, median_ndci: 0.039851732552051544, mad: 0.02888995222747326,
  n_dates: 50, anomaly_level: 'high',
})

const HIGHLIGHTS_ANOMALY = deepFreeze({
  disclaimer: DISCLAIMER_TEST,
  run_id: 6, mode: 'anomaly', metric: 'robust_z',
  ranking: "descending robust z against this location's own TEST seasonal baseline; not a risk level",
  n_requested: 5, min_separation_m: 3000, cohort_size: 209594,
  pins: [
    ANOMALY_PIN,
    { ...ANOMALY_PIN, rank: 2, pixel_centre_lat: 13.309356400000098, pixel_centre_lng: 100.21515468562336,
      cell_lat: 13.3085, cell_lng: 100.2151, robust_z: 11.24, metric_value: 11.24, anomaly_level: 'watch', edge_of_no_data: true },
  ],
  reason: null, excluded_degenerate: 90, excluded_low_signal: 671, quality_note: null,
  counts: {
    measured: 209594, assessable: 208194, no_baseline: 0, insufficient_dates: 639, zero_mad: 0,
    not_after_history: 0, too_old: 0, invalid: 90, low_signal: 671, watch: 17022, high: 6056,
    flagged_share: 0.11084853550054276,
  },
  baseline: { ...TEST_BASELINE },
})

const NDCI_PIN = deepFreeze({
  rank: 1, cell_lat: 13.57444225833009, cell_lng: 100.61939665894349,
  pixel_centre_lat: 13.575257640000011, pixel_centre_lng: 100.61939643562042,
  index_values: { ndci: 0.8257874250411987, bda2: 10.48, bda3: 29.07, b2_b3: 0.1499 },
  percentile: 99.94704046871571, metric_value: 0.8257874250411987, date_ms: 1791345267299,
  acquired_date: '2026-10-07', acquired_at: '2026-10-07T03:54:27.299000Z', edge_of_no_data: true,
  risk_tier: null, visible_bands_dn: { red: 177, green: 887, blue: 133 },
})

const HIGHLIGHTS_NDCI = deepFreeze({
  disclaimer: DISCLAIMER_PLAIN,
  run_id: 6, mode: 'ndci', metric: 'ndci', ranking: 'descending value within this run; not a risk level',
  n_requested: 5, min_separation_m: 3000, cohort_size: 209594, pins: [NDCI_PIN],
  reason: 'only 1 separable measured cells', baseline: null, excluded_degenerate: 90,
  excluded_low_signal: 671, quality_note: null,
})

const METHODS_BASELINE = deepFreeze({
  ...TEST_BASELINE, isTest: true, status: 'ready',
  methods: { latest_scene_policy: { max_cloud_fraction: 0.5, settle_hours: 36, poll_interval_hours: 1 } },
})

const LOADED = deepFreeze({
  raster: { loading: false, error: null },
  summary: { loading: false, error: null },
  riskMap: { loading: false, error: null },
  highlights: { loading: false, error: null },
})

function model(patch = {}) {
  return buildOverviewModel({
    raster: RASTER, summary: SUMMARY, riskMap: RISK_MAP, highlights: HIGHLIGHTS_NDCI,
    baseline: null, now: NOW, requests: LOADED, ...patch,
  })
}

const card = (m, id) => m.facts.find((c) => c.id === id)
const keys = (messages) => messages.map((x) => x.key)
const T = { en: createT('en'), th: createT('th') }
const say = (m, lang = 'en') => renderMessage(T[lang], m)

// ------------------------------------------------------------ key walker

/** Every i18n key a model names: `key` of a message, any `*Key` field, and
 * `status.<key>` for a chip descriptor. Raw API errors and functions are
 * skipped (they are not text). */
function collectKeys(node, out = new Set(), seen = new Set()) {
  if (node === null || typeof node !== 'object' || seen.has(node)) return out
  seen.add(node)
  if (Array.isArray(node)) {
    node.forEach((n) => collectKeys(n, out, seen))
    return out
  }
  const isChip = typeof node.key === 'string' && 'tone' in node && 'icon' in node
  for (const [field, value] of Object.entries(node)) {
    if (field === 'error' || field === 'raw' || typeof value === 'function') continue
    if (field === 'key' && typeof value === 'string') out.add(isChip ? `status.${value}` : value)
    else if (/Key$/.test(field) && typeof value === 'string') out.add(value)
    else collectKeys(value, out, seen)
  }
  return out
}

function lookup(dict, key) {
  return key.split('.').reduce((node, part) => (node && typeof node === 'object' ? node[part] : undefined), dict)
}

/** Every formatted value in a model: objects with `text` and `isNull`. */
function collectValues(node, out = [], seen = new Set()) {
  if (node === null || typeof node !== 'object' || seen.has(node)) return out
  seen.add(node)
  if (typeof node.text === 'string' && typeof node.isNull === 'boolean') out.push(node)
  for (const [field, value] of Object.entries(node)) {
    if (field === 'error' || typeof value === 'function') continue
    collectValues(value, out, seen)
  }
  return out
}

// ---------------------------------------------------------------- tests

test('healthy run: four key facts with sources, the used scene, a fresh poll', () => {
  const m = model()
  assert.deepEqual(m.facts.map((c) => c.id), ['newest_scene', 'measured_area', 'scenes', 'sites'])
  for (const c of m.facts) {
    assert.equal(c.state, 'ready', c.id)
    assert.ok(c.source && Array.isArray(c.source.rows) && c.source.url, `${c.id} has a source ref`)
  }
  assert.equal(card(m, 'newest_scene').value.text, '2026-10-07')
  assert.equal(card(m, 'newest_scene').source.field, 'newest_scene_date')
  assert.equal(card(m, 'measured_area').value.text, `64.2${NBSP}%`)
  assert.equal(card(m, 'measured_area').source.field, 'coverage.measured_fraction')
  assert.ok(keys(card(m, 'measured_area').notes).includes('overview.fact.not_measured_note'))
  assert.ok(keys(card(m, 'measured_area').notes).includes('overview.fact.measured_pixels'))
  assert.equal(card(m, 'scenes').value.text, '32')
  assert.equal(say(card(m, 'scenes').notes.find((n) => n.key === 'overview.fact.scenes_days')),
    'Cells come from 3 acquisition days (2026-09-29–2026-10-07); each cell keeps its own date.')
  assert.equal(say(card(m, 'scenes').notes.find((n) => n.key === 'overview.fact.scenes_share')),
    `Largest share: 2026-10-07, 77.6${NBSP}% of the cells.`)
  assert.equal(card(m, 'scenes').link.to, '/map')
  assert.equal(card(m, 'sites').value.text, '6')
  assert.equal(say(card(m, 'sites').unit), 'of 7 sites')

  assert.equal(m.latestScene.state, 'ready')
  assert.equal(m.latestScene.line.key, 'overview.scene.used')
  assert.equal(say(m.latestScene.line),
    `Newest assessed acquisition 2026-10-07: used in the raster shown (cloud over water 41${NBSP}% ≤ 50${NBSP}%).`)
  assert.equal(m.latestScene.tone, 'neutral')

  assert.equal(m.poll.health, 'ok')
  assert.equal(m.poll.line.key, 'overview.poll.ok')
  assert.equal(say(m.poll.line), 'Last successful check for newer scenes: 2026-10-09 19:03Z (56 min ago).')
  assert.equal(m.banner.state, 'ready')
  assert.equal(m.banner.key, 'banner.indices_available')
})

test('loading: every block is loading and nothing is claimed', () => {
  const loading = { loading: true, error: null }
  const m = buildOverviewModel({
    raster: null, summary: null, riskMap: null, highlights: null, baseline: null, now: NOW,
    requests: { raster: loading, summary: loading, riskMap: loading, highlights: { loading: false, error: null } },
  })
  assert.equal(m.banner.state, 'loading')
  for (const c of m.facts) assert.equal(c.state, 'loading', c.id)
  assert.equal(m.latestScene.state, 'loading')
  assert.equal(m.poll.state, 'loading')
  assert.equal(m.preview.state, 'loading')
  assert.equal(m.preview.pins.state, 'loading', 'pins wait for the raster run')
  assert.equal(m.sites.state, 'loading')
  assert.equal(m.disclaimer, null)
})

test('the banner waits for the summary too: no "summary could not be loaded" while it loads', () => {
  const m = model({ summary: null, requests: { ...LOADED, summary: { loading: true, error: null } } })
  assert.equal(m.banner.state, 'loading')
  assert.equal(card(m, 'sites').state, 'loading')
  assert.equal(card(m, 'newest_scene').state, 'ready')
})

test('no raster response: errors name the endpoint; nothing reads as measured or empty', () => {
  const error = { response: { status: 500, data: { detail: 'boom' } } }
  const m = model({ raster: null, highlights: null, requests: { ...LOADED, raster: { loading: false, error } } })
  assert.equal(m.banner.key, 'banner.raster_unknown')
  for (const id of ['newest_scene', 'measured_area', 'scenes']) {
    const c = card(m, id)
    assert.equal(c.state, 'error', id)
    assert.equal(c.error.endpoint, '/raster-scan')
    assert.equal(c.error.error, error)
  }
  assert.equal(card(m, 'sites').state, 'ready', 'a raster failure degrades only its own blocks')
  assert.equal(m.preview.state, 'error')
  assert.equal(m.latestScene.state, 'error')
  assert.equal(m.poll.state, 'error')
  assert.equal(m.preview.pins.state, 'no_raster')
})

test('no raster run: "—" with the empty reason, never 0; the poll is still reported', () => {
  const m = model({ raster: { ...NO_RUN, poll: POLL_OK }, highlights: null })
  assert.equal(m.banner.key, 'banner.no_raster')
  for (const id of ['newest_scene', 'measured_area', 'scenes']) {
    const c = card(m, id)
    assert.equal(c.state, 'empty', id)
    assert.equal(c.value.text, '—', id)
    assert.equal(c.notes[0].key, 'overview.state.raster_empty', id)
  }
  assert.equal(m.preview.state, 'empty')
  assert.equal(m.preview.empty.key, 'overview.state.raster_empty')
  assert.equal(m.preview.pins.state, 'no_raster')
  assert.equal(m.latestScene.state, 'empty')
  assert.equal(m.latestScene.line.key, 'overview.scene.none')
  assert.equal(m.poll.state, 'ready')
  assert.equal(m.poll.health, 'ok')
})

test('stale run: the last good raster is shown and marked stale, with why', () => {
  const m = model({ raster: { ...RASTER, stale_run_id: 7 } })
  assert.equal(m.banner.key, 'banner.stale_run')
  for (const id of ['newest_scene', 'measured_area', 'scenes']) {
    const c = card(m, id)
    assert.equal(c.state, 'stale', id)
    assert.ok(c.chips.some((chip) => chip.key === 'stale'), `${id} carries the stale chip`)
    assert.equal(c.value.text === '—', false, `${id} still shows its value`)
    assert.ok(c.notes.some((n) => n.key === 'overview.stale.raster' && n.params.stale_run === '7'), id)
  }
  assert.equal(m.preview.state, 'stale')
  assert.equal(m.preview.staleNote.key, 'overview.stale.raster')
  assert.ok(m.preview.image.url.endsWith('/raster-scan/overlay.png?run_id=6'))
})

test('poll error: failing with the error kind; newer scenes may exist unchecked -- never "no newer scene"', () => {
  const poll = {
    ...POLL_OK, last_error: 'ee.EEException: Earth Engine client library not initialized',
    last_error_at: '2026-10-09T19:40:00+00:00', last_error_kind: 'gee_auth',
  }
  const m = model({ raster: { ...RASTER, poll } })
  assert.equal(m.poll.health, 'failing')
  assert.equal(m.poll.tone, 'attention')
  assert.equal(m.poll.line.key, 'overview.poll.failing')
  assert.equal(m.poll.line.params.kind, 'gee_auth')
  assert.equal(m.poll.serverText, poll.last_error)
  const text = say(m.poll.line)
  assert.match(text, /newer scenes may exist that were not checked/i)
  assert.match(text, /gee_auth/)
  assert.ok(card(m, 'newest_scene').notes.some((n) => n.key === 'overview.fact.newest_scene_unchecked'))
  assert.equal(m.banner.key, 'banner.poll_failing')

  const neverOk = model({ raster: { ...RASTER, poll: { ...poll, last_poll_ok_at: null } } })
  assert.equal(neverOk.poll.line.key, 'overview.poll.failing_never_ok')

  // A later success clears the failure, and the earlier failure is noted.
  const recovered = model({ raster: { ...RASTER, poll: { ...poll, last_error_at: '2026-10-09T18:00:00Z' } } })
  assert.equal(recovered.poll.health, 'ok')
  assert.ok(recovered.poll.notes.some((n) => n.key === 'overview.poll.recovered'))
  assert.ok(!card(recovered, 'newest_scene').notes.some((n) => n.key === 'overview.fact.newest_scene_unchecked'))

  // No model, in any case, says there is no newer scene.
  for (const lang of ['en', 'th']) {
    for (const k of collectKeys(m)) {
      const value = lookup(lang === 'en' ? en : th, k)
      if (typeof value === 'string' && lang === 'en') assert.doesNotMatch(value, /no newer scene/i, k)
    }
  }
})

test('poll old or never: the age is stated and newer scenes may exist unchecked', () => {
  const old = model({ raster: { ...RASTER, poll: { ...POLL_OK, last_poll_ok_at: '2026-10-09T10:30:00Z' } } })
  assert.equal(old.poll.health, 'old')
  assert.equal(old.poll.line.key, 'overview.poll.old')
  assert.equal(say(old.poll.line),
    'The last successful check for newer scenes was 9 h ago (2026-10-09 10:30Z), so newer scenes may exist that were not checked.')
  const never = model({ raster: { ...RASTER, poll: null } })
  assert.equal(never.poll.health, 'never')
  assert.equal(never.poll.state, 'empty')
  assert.equal(never.poll.line.key, 'overview.poll.never')
  assert.match(say(never.poll.line), /newer scenes may exist that were not checked/)
  // The same rule as the banner.
  assert.equal(classifyPoll(RASTER.poll, NOW).state, 'ok')
  assert.equal(classifyPoll(null, NOW).state, 'never')
})

test('newest scene rejected for cloud: not used, cloud > threshold, earlier data shown; settled flag', () => {
  const scene = {
    ...SCENE_USED, acquisition_date: '2026-10-08', decision: 'rejected_cloud', cloud_fraction: 0.83,
    used_in_run_id: null, used_in_served_run: false, settled: false, reason: 'cloud over water above threshold',
  }
  const m = model({ raster: { ...RASTER, latest_scene: scene } })
  assert.equal(m.latestScene.line.key, 'overview.scene.rejected_cloud')
  assert.equal(say(m.latestScene.line),
    `Newest assessed acquisition 2026-10-08: not used (cloud over water 83${NBSP}% > 50${NBSP}%).`)
  assert.equal(m.latestScene.tone, 'attention')
  assert.deepEqual(keys(m.latestScene.notes), ['overview.scene.shown', 'overview.scene.provisional', 'overview.scene.assessed_at'])
  assert.equal(say(m.latestScene.notes[0]), 'The raster shown (run 6) has its newest scene on 2026-10-07.')
  assert.equal(m.latestScene.serverReason, 'cloud over water above threshold')
  assert.equal(m.banner.key, 'banner.scene_rejected_cloud')

  // Equal-looking percentages get a decimal so "50 % > 50 %" never appears.
  const close = model({ raster: { ...RASTER, latest_scene: { ...scene, cloud_fraction: 0.503 } } })
  assert.equal(close.latestScene.line.params.cloud, `50.3${NBSP}%`)
  assert.equal(close.latestScene.line.params.threshold, `50.0${NBSP}%`)

  const noWater = model({ raster: { ...RASTER, latest_scene: { ...scene, decision: 'rejected_no_water', cloud_fraction: null } } })
  assert.equal(noWater.latestScene.line.key, 'overview.scene.rejected_no_water')
  assert.equal(noWater.latestScene.line.params.min, '1,000')
})

test('used scene and its variants: settled with the server\'s settle hours; pending; re-assessed after use', () => {
  const used = model({ baseline: METHODS_BASELINE })
  assert.deepEqual(keys(used.latestScene.notes), ['overview.scene.settled_hours', 'overview.scene.assessed_at'])
  assert.equal(used.latestScene.notes[0].params.hours, '36')
  assert.equal(model().latestScene.notes[0].key, 'overview.scene.settled', 'no constant invented without /methods')

  const pending = model({ raster: { ...RASTER, latest_scene: { ...SCENE_USED, acquisition_date: '2026-10-08', used_in_run_id: null, used_in_served_run: false } } })
  assert.equal(pending.latestScene.line.key, 'overview.scene.pending')
  assert.equal(pending.latestScene.tone, 'attention')

  const otherRun = model({ raster: { ...RASTER, latest_scene: { ...SCENE_USED, used_in_run_id: 7, used_in_served_run: false } } })
  assert.equal(otherRun.latestScene.line.key, 'overview.scene.used_other_run')
  assert.equal(otherRun.latestScene.line.params.run, '7')

  const reassessed = model({ raster: { ...RASTER, latest_scene: { ...SCENE_USED, decision: 'rejected_cloud', cloud_fraction: 0.62, reassessed_after_use: true } } })
  assert.equal(reassessed.latestScene.line.key, 'overview.scene.reassessed_cloud')
  assert.match(say(reassessed.latestScene.line), /re-assessed as not passing/)
  assert.ok(!/not used/.test(say(reassessed.latestScene.line)), 'never simply "not used" after use')
})

test('test baseline on: TEST banner lines, anomaly pins with (TEST) chips, the TEST disclaimer', () => {
  const m = model({ baseline: METHODS_BASELINE, highlights: HIGHLIGHTS_ANOMALY })
  assert.equal(m.isTest, true)
  assert.ok(m.banner.lines.some((l) => l.key === 'truth.test_banner'))
  const pins = m.preview.pins
  assert.equal(pins.state, 'ready')
  assert.equal(pins.mode, 'anomaly')
  assert.equal(pins.legendKey, 'overview.pins.legend_anomaly')
  assert.match(en.overview.pins.legend_anomaly, /\(TEST\)/)
  assert.match(th.overview.pins.legend_anomaly, /\(TEST\)/)
  assert.deepEqual(pins.items.map((p) => p.chip.key), ['anomaly_high_test', 'anomaly_watch_test'])
  assert.equal(pins.items[0].z.text, '14.34')
  assert.equal(pins.items[0].ndci.text, '0.654')
  assert.ok(pins.notes.some((n) => n.key === 'overview.pins.anomaly_counts'))
  assert.equal(pins.notes.find((n) => n.key === 'overview.pins.anomaly_counts').params.flagged, '23,078')
  assert.deepEqual(m.disclaimer, { text: DISCLAIMER_TEST, endpoint: '/raster-scan/highlights' })
  for (const p of pins.items) assert.equal('risk_tier' in p, false, 'no code path carries a tier')
})

test('ndci pins: a ranking within one scan, not TEST; fewer than requested says why, verbatim', () => {
  const m = model()
  const pins = m.preview.pins
  assert.equal(pins.mode, 'ndci')
  assert.equal(pins.legendKey, 'overview.pins.legend_ndci')
  assert.doesNotMatch(en.overview.pins.legend_ndci, /TEST/)
  assert.match(en.overview.pins.legend_ndci, /not a risk level/)
  assert.equal(pins.items[0].chip, null)
  assert.equal(pins.items[0].z, null)
  assert.equal(pins.items[0].edge, true)
  assert.equal(pins.items[0].href, '/map?run=6&pin=1')
  assert.equal(pins.serverReason, 'only 1 separable measured cells')
  assert.ok(pins.notes.some((n) => n.key === 'overview.pins.fewer' && n.params.count === '1' && n.params.n === String(PIN_COUNT)))
  assert.deepEqual(m.disclaimer, { text: DISCLAIMER_PLAIN, endpoint: '/raster-scan/highlights' })
})

test('no pins: the empty state with the server reason; pins of another run are not drawn', () => {
  const none = model({ highlights: { ...HIGHLIGHTS_NDCI, pins: [], reason: 'no measured cells' } })
  assert.equal(none.preview.pins.state, 'empty')
  assert.equal(none.preview.pins.empty.key, 'overview.pins.none')
  assert.equal(none.preview.pins.serverReason, 'no measured cells')
  assert.deepEqual(none.preview.pins.items, [])

  const other = model({ highlights: { ...HIGHLIGHTS_NDCI, run_id: 5 } })
  assert.equal(other.preview.pins.state, 'other_run')
  assert.deepEqual(other.preview.pins.items, [])
  assert.equal(other.preview.pins.empty.params.pins_run, '5')

  const unknown = model({ highlights: { ...HIGHLIGHTS_NDCI, mode: 'risk' } })
  assert.equal(unknown.preview.pins.state, 'unknown_mode')
  assert.deepEqual(unknown.preview.pins.items, [])

  const failed = model({ highlights: null, requests: { ...LOADED, highlights: { loading: false, error: { response: { status: 404 } } } } })
  assert.equal(failed.preview.pins.state, 'error')
  assert.equal(failed.preview.pins.error.endpoint, '/raster-scan/highlights?n=5&run_id=6')
  assert.equal(failed.preview.state, 'ready', 'a pin failure degrades the pins only')
})

test('map geometry: pins placed by the raster bounds; legend from the API swatches only', () => {
  const m = model()
  const p = m.preview
  assert.ok(Math.abs(p.box.aspect - (101.02812976061746 - 99.91242253062555) / (13.615681814999999 - 12.503567845000363)) < 1e-9)
  const pin = p.pins.items[0]
  assert.ok(pin.inFigure)
  assert.ok(Math.abs(pin.x - ((100.61939643562042 - 99.91242253062555) / (101.02812976061746 - 99.91242253062555)) * 100) < 1e-6)
  assert.ok(Math.abs(pin.y - ((13.615681814999999 - 13.575257640000011) / (13.615681814999999 - 12.503567845000363)) * 100) < 1e-6)
  const outside = model({ highlights: { ...HIGHLIGHTS_NDCI, pins: [{ ...NDCI_PIN, pixel_centre_lat: 14.2 }] } })
  assert.equal(outside.preview.pins.items[0].inFigure, false)
  assert.deepEqual(p.legend.swatches.map((s) => s.hex), ['#0a1929', '#48c9a9', '#d64545'])
  assert.equal(p.legend.min, `≤${NBSP}−0.050`)
  assert.equal(p.legend.max, `≥${NBSP}0.150`)
  const hostile = model({ raster: { ...RASTER, legend: { value: { domain: [-0.05, 0.15], swatches: [{ value: 0, hex: 'red;background:url(x)' }, { value: 1, hex: '#abc' }] } } } })
  assert.deepEqual(hostile.preview.legend.swatches.map((s) => s.hex), ['#abc'])
  assert.equal(p.sites.length, 7)
  assert.equal(p.extent.key, 'overview.map.extent')
  assert.equal(say(p.extent), '12.50°–13.62° N, 99.91°–101.03° E')
  const noBounds = model({ raster: { ...RASTER, bounds: [[13, 100], [12, 101]] } })
  assert.equal(noBounds.preview.state, 'empty')
  assert.equal(noBounds.preview.empty.key, 'overview.map.no_bounds')
})

test('sites strip: ok / no_imagery / no_data_yet / stale map onto the closed vocabulary, with links', () => {
  const m = model()
  assert.equal(m.sites.state, 'stale')
  assert.equal(m.sites.items.length, 7)
  const by = Object.fromEntries(m.sites.items.map((s) => [s.id, s]))
  assert.deepEqual(by.bangsaen.chips.map((c) => c.key), ['measured', 'not_evaluated'])
  assert.deepEqual(by.siracha.chips.map((c) => c.key), ['no_usable_data'])
  assert.deepEqual(by.chaam.chips.map((c) => c.key), ['not_checked_yet'])
  assert.deepEqual(by.bangpakong_mouth.chips.map((c) => c.key), ['measured', 'not_evaluated', 'stale'])
  assert.equal(by.bangsaen.date.text, '2026-09-29')
  assert.equal(by.siracha.date.text, '—')
  assert.equal(by.siracha.date.reason, 'no_imagery')
  assert.equal(by.chaam.date.reason, 'no_data_yet')
  assert.equal(by.bangsaen.href, '/sites/bangsaen')
  assert.equal(by.bangsaen.source.endpoint, '/risk-map')
  assert.ok(m.sites.notes.some((n) => n.key === 'overview.stale.sites_strip' && n.params.n === '1'))

  const fresh = model({ riskMap: { ...RISK_MAP, features: RISK_MAP.features.map((f) => ({ ...f, properties: { ...f.properties, stale: false } })) } })
  assert.equal(fresh.sites.state, 'ready')
  const empty = model({ riskMap: { ...RISK_MAP, features: [] } })
  assert.equal(empty.sites.state, 'empty')
  assert.equal(empty.sites.empty.key, 'overview.state.sites_empty')
  const failed = model({ riskMap: null, requests: { ...LOADED, riskMap: { loading: false, error: {} } } })
  assert.equal(failed.sites.state, 'error')
  assert.equal(failed.sites.error.endpoint, '/risk-map')
})

test('sites card: no_usable_data and not_checked_yet are separate rows, never merged', () => {
  const m = model({ summary: { ...SUMMARY, risk_level_counts: { ...SUMMARY.risk_level_counts, not_evaluated: 4, no_usable_data: 1, not_checked_yet: 2 } } })
  const c = card(m, 'sites')
  assert.equal(c.value.text, '4')
  assert.deepEqual(c.breakdown.map((b) => [b.id, b.value.text]), [['no_usable_data', '1'], ['not_checked_yet', '2']])
  assert.deepEqual(c.breakdown.map((b) => b.labelKey), ['status.no_usable_data', 'status.not_checked_yet'])
  assert.ok(!c.breakdown.some((b) => b.value.text === '3'), 'never one merged "3"')
  // A real zero stays a zero.
  assert.equal(card(model(), 'sites').breakdown[1].value.text, '0')

  const stale = model({ summary: { ...SUMMARY, stale_site_count: 2 } })
  assert.equal(card(stale, 'sites').state, 'stale')
  assert.ok(card(stale, 'sites').notes.some((n) => n.key === 'overview.stale.sites' && n.params.n === '2'))

  const missing = model({ summary: { ...SUMMARY, risk_level_counts: { no_usable_data: 1 } } })
  assert.equal(card(missing, 'sites').value.text, '—', 'an absent count is unknown, never 0')
  assert.equal(card(missing, 'sites').breakdown[1].value.text, '—')
})

test('no 0 for nulls: every unknown value in every case renders "—"', () => {
  const cases = [
    model({ raster: NO_RUN, summary: { ...SUMMARY, total_sites: null, risk_level_counts: {} }, highlights: null }),
    model({ raster: { ...RASTER, coverage: null, scene_count: null, scene_dates: null, newest_scene_date: null } }),
    model({ highlights: { ...HIGHLIGHTS_NDCI, pins: [{ ...NDCI_PIN, index_values: { ndci: null } }] } }),
  ]
  for (const m of cases) {
    const values = collectValues(m)
    assert.ok(values.length > 5)
    for (const v of values) {
      if (v.raw === null || v.raw === undefined) assert.equal(v.text, '—', JSON.stringify(v))
      assert.notEqual(v.isNull && v.text, '0')
    }
  }
  const unknownCoverage = cases[1]
  assert.equal(card(unknownCoverage, 'measured_area').state, 'empty')
  assert.ok(card(unknownCoverage, 'measured_area').notes.some((n) => n.key === 'overview.fact.coverage_unknown'))
  assert.ok(card(unknownCoverage, 'scenes').notes.some((n) => n.key === 'overview.fact.scenes_days_unknown'))
})

test('all strings are i18n keys present in TH and EN, with every placeholder filled', () => {
  const error = { response: { status: 503, data: { detail: 'Earth Engine is not configured' } } }
  const scenes = ['rejected_cloud', 'rejected_no_water', 'odd_decision'].map((decision) => model({
    raster: { ...RASTER, latest_scene: { ...SCENE_USED, decision, used_in_run_id: null, used_in_served_run: false } },
  }))
  const cases = [
    model(),
    model({ baseline: METHODS_BASELINE, highlights: HIGHLIGHTS_ANOMALY }),
    model({ raster: { ...RASTER, stale_run_id: 7, poll: { ...POLL_OK, last_error: 'x', last_error_at: '2026-10-09T19:59:00Z', last_error_kind: 'unexpected' } } }),
    model({ raster: NO_RUN, highlights: null }),
    model({ raster: null, summary: null, riskMap: null, highlights: null, requests: { raster: { error }, summary: { error }, riskMap: { error } } }),
    model({ raster: { ...RASTER, latest_scene: { ...SCENE_USED, decision: 'rejected_cloud', reassessed_after_use: true } } }),
    model({ raster: { ...RASTER, latest_scene: { ...SCENE_USED, decision: 'rejected_no_water', reassessed_after_use: true } } }),
    model({ highlights: { ...HIGHLIGHTS_NDCI, pins: [] } }),
    model({ highlights: { ...HIGHLIGHTS_NDCI, run_id: 5 } }),
    model({ highlights: { ...HIGHLIGHTS_NDCI, mode: 'x' } }),
    model({ summary: { ...SUMMARY, stale_site_count: 3, risk_level_counts: { ...SUMMARY.risk_level_counts, watch: 1 } } }),
    model({ raster: { ...RASTER, coverage: { measured_fraction: 0.5, measured_pixels: null, polygon_pixels: 10 } } }),
    ...scenes,
  ]
  const all = new Set()
  for (const m of cases) collectKeys(m, all)
  assert.ok(all.size > 40, `many keys collected (${all.size})`)
  for (const key of all) {
    assert.equal(typeof lookup(en, key), 'string', `en.js lacks ${key}`)
    assert.equal(typeof lookup(th, key), 'string', `th.js lacks ${key}`)
  }
  // Rendered through t(), no message leaves a raw key or an unfilled {param}.
  missingKeys.clear()
  const messages = []
  const walk = (node, seen = new Set()) => {
    if (!node || typeof node !== 'object' || seen.has(node)) return
    seen.add(node)
    if (typeof node.key === 'string' && node.params && typeof node.params === 'object') messages.push(node)
    for (const [field, v] of Object.entries(node)) if (field !== 'error' && typeof v !== 'function') walk(v, seen)
  }
  cases.forEach((m) => walk(m))
  for (const lang of ['en', 'th']) {
    for (const message of messages) {
      const out = say(message, lang)
      assert.doesNotMatch(out, /\{\w+\}/, `${lang}:${message.key} left a placeholder: ${out}`)
    }
  }
  assert.deepEqual([...missingKeys], [])
})

test('ageMessage and renderMessage: nested messages resolve; no negative ages', () => {
  assert.equal(ageMessage(30 * 1000).key, 'overview.age.under_minute')
  assert.deepEqual(ageMessage(56 * 60000), { key: 'overview.age.minutes', params: { n: '56' } })
  assert.deepEqual(ageMessage(9 * 3600000 + 1), { key: 'overview.age.hours', params: { n: '9' } })
  assert.deepEqual(ageMessage(3 * 86400000), { key: 'overview.age.days', params: { n: '3' } })
  assert.equal(ageMessage(-5000).key, 'overview.age.under_minute')
  assert.equal(ageMessage(null).key, 'overview.age.unknown')
  assert.equal(renderMessage(T.en, { key: 'common.of', params: { n: { key: 'overview.age.hours', params: { n: '2' } }, total: '7' } }), '2 h of 7')
  assert.equal(renderMessage(T.en, null), '')
})

test('disclaimer: the server text of a loaded response, verbatim; the highlights first while pins show', () => {
  assert.deepEqual(model({ highlights: null }).disclaimer, { text: DISCLAIMER_TEST, endpoint: '/summary' })
  assert.deepEqual(model({ highlights: null, summary: null, riskMap: null }).disclaimer, { text: DISCLAIMER_PLAIN, endpoint: '/raster-scan' })
})

// ------------------------------------------------------------- markup

let server
let OverviewView
let StaticLangProvider

before(async () => {
  server = await createServer({
    configFile: false,
    plugins: [react()],
    cacheDir: 'node_modules/.vite-overview-tests',
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true, watch: null, hmr: false, ws: false },
  })
  OverviewView = (await server.ssrLoadModule('/src/pages/OverviewPage.jsx')).OverviewView
  ;({ StaticLangProvider } = await server.ssrLoadModule('/src/i18n/LangContext.jsx'))
})

after(async () => server?.close())

function render(m, lang = 'en') {
  return renderToStaticMarkup(createElement(MemoryRouter, null,
    createElement(StaticLangProvider, { lang }, createElement(OverviewView, { model: m, onRetry: {} }))))
}

const visible = (html) => html.replace(/<[^>]+>/g, ' ').replace(/&#x27;/g, "'").replace(/&quot;/g, '"')
  .replace(/&amp;/g, '&').replace(/\s+/g, ' ')

test('OverviewView: one h1, four fact cards, the figure with numbered neutral pins, seven site links', () => {
  const html = render(model({ baseline: METHODS_BASELINE, highlights: HIGHLIGHTS_ANOMALY }))
  assert.equal((html.match(/<h1/g) ?? []).length, 1)
  assert.equal((html.match(/data-fact="/g) ?? []).length, 4)
  assert.equal((html.match(/class="pw-ov-pin"/g) ?? []).length, 2)
  assert.match(html, /src="http:\/\/localhost:8000\/raster-scan\/overlay\.png\?run_id=6"/)
  for (const f of RISK_MAP.features) assert.match(html, new RegExp(`href="/sites/${f.properties.site_id}"`))
  assert.match(html, /href="\/map"/)
  const text = visible(html)
  assert.ok(text.includes(en.overview.pins.legend_anomaly))
  assert.ok(text.includes('Anomaly vs own history: high (TEST)'))
  assert.ok(text.includes(en.overview.fact.not_measured_note))
  assert.ok(html.includes(`64.2${NBSP}%`), 'the measured share with its unit, NBSP-joined')
  assert.doesNotMatch(html, /risk-(normal|elevated|watch|warning)|RISK_COLOR/)
})

test('OverviewView: distinct loading, error, empty and stale copy per block, in both languages', () => {
  const loading = { loading: true, error: null }
  const states = {
    loading: buildOverviewModel({ now: NOW, requests: { raster: loading, summary: loading, riskMap: loading } }),
    error: buildOverviewModel({ now: NOW, requests: { raster: { error: { response: { status: 500 } } }, summary: { error: {} }, riskMap: { error: {} } } }),
    empty: model({ raster: NO_RUN, highlights: null, riskMap: { ...RISK_MAP, features: [] } }),
    stale: model({ raster: { ...RASTER, stale_run_id: 7 } }),
  }
  for (const lang of ['en', 'th']) {
    const dict = lang === 'en' ? en : th
    const out = Object.fromEntries(Object.entries(states).map(([k, m]) => [k, visible(render(m, lang))]))
    assert.ok(out.loading.includes(dict.overview.state.raster_loading))
    assert.ok(out.loading.includes(dict.overview.state.sites_loading))
    assert.ok(out.error.includes(dict.overview.state.raster_error))
    assert.ok(out.error.includes(dict.overview.state.sites_error))
    assert.ok(out.error.includes('GET /raster-scan'))
    assert.ok(out.empty.includes(dict.overview.state.raster_empty))
    assert.ok(out.empty.includes(dict.overview.state.sites_empty))
    assert.ok(out.stale.includes(dict.status.stale))
    for (const k of Object.keys(out)) assert.doesNotMatch(out[k], /overview\.[a-z_.]+/, `${lang}/${k}: a raw key leaked`)
  }
})

test('OverviewView: an unknown value renders "—" with its reason, never 0', () => {
  const html = render(model({ summary: { ...SUMMARY, risk_level_counts: { no_usable_data: 1 } } }))
  const factHtml = html.slice(html.indexOf('data-fact="sites"'))
  assert.match(factHtml, /data-null="true"/)
  assert.doesNotMatch(visible(factHtml.slice(0, factHtml.indexOf('</article>'))), /\b0 of 7/)
})

test('the overview sources never reference the risk tokens and route "/" to the page', async () => {
  for (const file of ['../src/pages/OverviewPage.jsx', '../src/components/OverviewMapPreview.jsx', '../src/lib/overviewModel.js']) {
    const source = await readFile(new URL(file, import.meta.url), 'utf8')
    assert.doesNotMatch(source, /risk-(normal|elevated|watch|warning)|RISK_COLOR/, file)
  }
  const main = await readFile(new URL('../src/main.jsx', import.meta.url), 'utf8')
  assert.match(main, /<Route index element={<OverviewPage \/>} \/>/)
})
