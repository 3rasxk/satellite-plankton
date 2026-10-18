/**
 * The glass chrome's data (src/lib/mapListModel.js): station sorting, the
 * left card's headline and count chips, the default layer and the top
 * bar's freshness chip.
 *
 * Claims, not markup: the chips name real categories only (no risk class,
 * nothing classified on the client); an unknown count is left out rather
 * than shown as 0; sorting puts unknown z last; the freshness dot is "ok"
 * only for a healthy newer-scene poll, and no wording says that no newer
 * scene exists.
 */
import test from 'node:test'
import assert from 'node:assert/strict'

import en from '../src/i18n/en.js'
import th from '../src/i18n/th.js'
import { createT } from '../src/i18n/index.js'
import { buildPinsModel } from '../src/lib/mapModel.js'
import { renderMessage } from '../src/lib/overviewModel.js'
import {
  buildSiteListModel, buildCountChips, buildMapHeadline, buildUpdateChip, defaultLayer, siteMarkerKind, siteCounts,
  LAYER_ORDER,
} from '../src/lib/mapListModel.js'
import { HIGHLIGHTS_ANOMALY, HIGHLIGHTS_NDCI, RASTER } from './fixtures/map_payloads.js'

const T = { en: createT('en'), th: createT('th') }

function site(id, name, z, over = {}) {
  return {
    type: 'Feature',
    geometry: { type: 'Point', coordinates: [100.5, 13.2] },
    properties: {
      site_id: id, name, status: 'ok', risk_level: null, stale: false,
      signal_anomaly_level: z === null ? null : 'normal', signal_robust_z: z, signal_anomaly_reason: z === null ? 'insufficient_independent_dates' : null,
      index_values: { ndci: 0.05, '2bda': 1, '3bda': 0.1, b2_b3_ratio: 0.9 }, cloud_fraction: 0, actual_date: '2026-10-07',
      ...over,
    },
  }
}

const BASELINE = { mode: 'test', valid: true, version: 'TEST-1', reason: null, min_season_dates_by_location: {} }
const NO_READING = { index_values: null, signal_anomaly_level: null, signal_robust_z: null, actual_date: null, cloud_fraction: null }

const RISK_MAP = {
  type: 'FeatureCollection',
  baseline: BASELINE,
  features: [
    site('b', 'Bang Saen', 1.0),
    site('c', 'Chao Phraya mouth', 2.4, { signal_anomaly_level: 'watch', stale: true }),
    site('a', 'Ang Sila', null),
    site('s', 'Si Racha', null, { ...NO_READING, status: 'no_imagery' }),
    site('h', 'Cha-am', null, { ...NO_READING, status: 'no_data_yet' }),
    site('p', 'Pattaya', -1.2),
  ],
}

test('sites: sorted by robust z (TEST) descending while a valid TEST baseline gives a z; unknown z last, stably', () => {
  const m = buildSiteListModel({ riskMap: RISK_MAP, request: {} })
  assert.equal(m.state, 'ready')
  assert.equal(m.sortedBy, 'anomaly')
  assert.deepEqual(m.items.map((s) => s.id), ['c', 'b', 'p', 'a', 's', 'h'])
})

test('sites: sorted by name without a TEST baseline (the z values are not used at all)', () => {
  const m = buildSiteListModel({ riskMap: { ...RISK_MAP, baseline: null }, request: {} })
  assert.equal(m.sortedBy, 'name')
  assert.deepEqual(m.items.map((s) => s.name), ['Ang Sila', 'Bang Saen', 'Cha-am', 'Chao Phraya mouth', 'Pattaya', 'Si Racha'])
  assert.ok(m.items.every((s) => s.anomaly.shown === false), 'no anomaly chip without a TEST baseline')
})

test('sites: marker kinds follow the status; an unknown status is never a reading', () => {
  assert.equal(siteMarkerKind('ok'), 'reading')
  assert.equal(siteMarkerKind('no_data_yet'), 'not_checked')
  for (const s of ['no_imagery', 'error', 'no_water_pixels', 'brand_new_status', null]) assert.equal(siteMarkerKind(s), 'no_data')
  const m = buildSiteListModel({ riskMap: RISK_MAP, request: {} })
  const byId = Object.fromEntries(m.items.map((s) => [s.id, s]))
  assert.equal(byId.s.kind, 'no_data')
  assert.equal(byId.h.kind, 'not_checked')
  assert.equal(byId.s.ndci.raw, null, 'no reading: NDCI stays null, never 0')
  assert.equal(byId.s.ndci.text, '—')
})

test('sites: loading, error and empty states', () => {
  assert.equal(buildSiteListModel({ riskMap: null, request: { loading: true } }).state, 'loading')
  const err = buildSiteListModel({ riskMap: null, request: { error: new Error('x') } })
  assert.equal(err.state, 'error')
  assert.equal(err.error.endpoint, '/risk-map')
  assert.equal(buildSiteListModel({ riskMap: { features: [] } }).state, 'empty')
})

test('count chips: real categories only, unknown counts left out, never a risk class', () => {
  const sites = buildSiteListModel({ riskMap: RISK_MAP, request: {} })
  assert.deepEqual(sites.counts, { total: 6, measured: 4, noUsable: 1, notChecked: 1, stale: 1 })
  const pins = buildPinsModel({ highlights: HIGHLIGHTS_ANOMALY, request: {}, runId: HIGHLIGHTS_ANOMALY.run_id, n: 5 })
  const chips = buildCountChips({ sites, pins, highlights: HIGHLIGHTS_ANOMALY })
  assert.deepEqual(chips.map((c) => c.id), ['anomaly_high', 'anomaly_watch', 'sites_measured', 'sites_no_usable', 'sites_not_checked', 'sites_stale'])
  assert.equal(chips[0].chip.key, 'anomaly_high_test', 'anomaly counts are always TEST-labelled')
  assert.equal(chips[0].count, '6,056')
  assert.equal(chips[1].count, '17,022')
  for (const c of chips) {
    assert.doesNotMatch(JSON.stringify(c), /risk|normal_risk|elevated|warning/i)
    assert.ok(Object.hasOwn(en.status, c.chip.key), `${c.chip.key} is a status-vocabulary key`)
  }
  // NDCI mode: no anomaly counts at all.
  const ndciPins = buildPinsModel({ highlights: HIGHLIGHTS_NDCI, request: {}, runId: HIGHLIGHTS_NDCI.run_id, n: 5 })
  assert.ok(!buildCountChips({ sites, pins: ndciPins, highlights: HIGHLIGHTS_NDCI }).some((c) => c.group === 'pins'))
  // A missing count is left out, never shown as 0.
  const partial = { ...HIGHLIGHTS_ANOMALY, counts: { ...HIGHLIGHTS_ANOMALY.counts, high: null } }
  const ids = buildCountChips({ sites, pins, highlights: partial }).map((c) => c.id)
  assert.ok(!ids.includes('anomaly_high'))
  assert.ok(ids.includes('anomaly_watch'))
  // Pins of another run (or still loading) contribute nothing.
  assert.ok(!buildCountChips({ sites, pins: { state: 'loading' }, highlights: HIGHLIGHTS_ANOMALY }).some((c) => c.group === 'pins'))
  assert.deepEqual(buildCountChips({}), [])
})

test('count chips: zero-count site categories other than "measured" are omitted', () => {
  const sites = { state: 'ready', counts: siteCounts([{ kind: 'reading' }, { kind: 'reading' }]) }
  assert.deepEqual(buildCountChips({ sites }).map((c) => [c.id, c.count]), [['sites_measured', '2']])
})

test('headline: sites with a reading, then the pins of the scan, in both languages', () => {
  const sites = buildSiteListModel({ riskMap: RISK_MAP, request: {} })
  const pins = buildPinsModel({ highlights: HIGHLIGHTS_ANOMALY, request: {}, runId: HIGHLIGHTS_ANOMALY.run_id, n: 5 })
  const h = buildMapHeadline({ sites, pins })
  assert.equal(renderMessage(T.en, h.headline), '4 of 6 stations have an index reading')
  assert.match(renderMessage(T.en, h.subline), /^3 anomaly pins \(TEST\) in this scan/)
  assert.ok(!renderMessage(T.th, h.headline).includes('{'), 'every Thai param is filled')
  const ndci = buildPinsModel({ highlights: HIGHLIGHTS_NDCI, request: {}, runId: HIGHLIGHTS_NDCI.run_id, n: 5 })
  assert.match(renderMessage(T.en, buildMapHeadline({ sites, pins: ndci }).subline), /highest-NDCI pins in this scan/)
  assert.equal(buildMapHeadline({ sites: { state: 'loading' } }).headline.key, 'glass.list.headline_loading')
  assert.equal(buildMapHeadline({ sites: { state: 'error' } }).headline.key, 'glass.list.headline_error')
  const none = { state: 'ready', counts: siteCounts([{ kind: 'no_data' }]) }
  assert.equal(buildMapHeadline({ sites: none }).headline.key, 'glass.list.headline_none')
  for (const dict of [en, th]) {
    for (const v of Object.values(dict.glass.list)) assert.doesNotMatch(v, /risk(?!-map)|เสี่ยง/i)
  }
})

test('default layer: True Color only when the served run stored its own RGB composite', () => {
  assert.equal(defaultLayer(RASTER), 'true_color')
  assert.equal(defaultLayer({ ...RASTER, true_color_url: null }), 'ndci')
  assert.equal(defaultLayer(null), 'ndci')
  assert.deepEqual([...LAYER_ORDER], ['true_color', 'ndci'])
})

test('freshness chip: ok only for a healthy poll; old, failing, never and errors are attention, with the Overview wording', () => {
  const okAt = Date.parse(RASTER.poll.last_poll_ok_at)
  const ok = buildUpdateChip({ raster: RASTER, request: {}, now: okAt + 25 * 60000 })
  assert.equal(ok.tone, 'ok')
  assert.equal(renderMessage(T.en, ok.short), 'Updated 25 min ago')
  assert.equal(ok.detail.key, 'overview.poll.ok')

  const old = buildUpdateChip({ raster: RASTER, request: {}, now: okAt + 4 * 3600000 })
  assert.equal(old.tone, 'attention')
  assert.equal(old.detail.key, 'overview.poll.old')
  assert.match(renderMessage(T.en, old.detail), /newer scenes may exist that were not checked/)

  const failing = buildUpdateChip({
    raster: { ...RASTER, poll: { ...RASTER.poll, last_error: 'boom', last_error_kind: 'gee', last_error_at: '2026-10-10T14:30:00+00:00' } },
    request: {},
    now: okAt + 60 * 60000,
  })
  assert.equal(failing.tone, 'attention')
  assert.equal(failing.state, 'failing')

  const never = buildUpdateChip({ raster: { ...RASTER, poll: null }, request: {}, now: okAt })
  assert.equal(never.tone, 'attention')
  assert.equal(never.short.key, 'glass.updated.never')

  assert.equal(buildUpdateChip({ raster: null, request: { loading: true } }).state, 'loading')
  const err = buildUpdateChip({ raster: null, request: { error: new Error('x') } })
  assert.equal(err.state, 'error')
  assert.equal(err.tone, 'attention')

  for (const dict of [en, th]) {
    for (const v of Object.values(dict.glass.updated)) {
      assert.doesNotMatch(v, /no newer scene|up to date|ไม่มีภาพใหม่/i, 'never implies that no newer scene exists')
    }
  }
})
